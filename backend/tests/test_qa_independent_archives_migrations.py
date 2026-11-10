"""Additive independent archives: SQLite/PostgreSQL parity and data preservation."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_qa_independent_archives import frozen, report, second_archive, source
from test_review_tasks import tasks as tasks

from app.evaluation import schema
from app.evaluation import tables as t
from app.evaluation.qa_independent_archives import IndependentReportRepository, IndependentRetestCreate, IndependentRetestRepository
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.component_tests.model import ComponentRow
from deerflow.persistence.user.model import UserRow

NEW = {t.independent_report_archives.name, t.independent_retest_archives.name}


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        (command.downgrade if target == "eval_0011" else command.upgrade)(config, target)


async def rows(engine, tables):
    async with engine.connect() as conn:
        return {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in tables}


async def seed_legacy(tasks):
    first = await frozen(tasks, second_decision="fail")
    second = await second_archive(tasks)
    engine, project = tasks[2], tasks[3]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: UserRow.__table__.create(c))
        await conn.execute(insert(UserRow.__table__).values(id=str(uuid4()), email="synthetic@example.invalid", password_hash="SYNTHETIC_PASSWORD_HASH", system_role="user"))
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        await conn.execute(
            insert(t.report_archives).values(
                id="e" * 32,
                owner_id="owner",
                project_id=project,
                root_id="e" * 32,
                revision=1,
                title="Synthetic legacy draft",
                template_id="verified-qa-project-en",
                template_version="1.0.0",
                created_at_ms=1,
                request_hash="a" * 64,
                archive_hash="b" * 64,
                document={"synthetic_legacy": True},
            )
        )
        await conn.execute(
            insert(t.retest_archives).values(
                id="f" * 32,
                owner_id="owner",
                project_id=project,
                component_id=first["assessment"]["component_id"],
                baseline_run_id=first["run_id"],
                retest_run_id=second["run_id"],
                baseline_label="Synthetic",
                retest_label="Synthetic v2",
                created_at_ms=1,
                request_hash="a" * 64,
                archive_hash="b" * 64,
                document={"synthetic_legacy": True},
            )
        )
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    assert NEW.isdisjoint(names)
    old = [ComponentRow.__table__, UserRow.__table__, *[table for table in t.metadata.sorted_tables if table.name in names]]
    return first, second, old


async def cycle(engine, old, before):
    legacy = MetaData()
    for table in (ComponentRow.__table__, UserRow.__table__):
        table.to_metadata(legacy)
    for target in ("head", "head", "eval_0011", "head"):
        await asyncio.to_thread(migrate, engine.url, target)
        assert await rows(engine, old) == before
        async with engine.connect() as conn:
            names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
            assert NEW.isdisjoint(names) if target == "eval_0011" else NEW.issubset(names)
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == ("eval_0011" if target == "eval_0011" else "eval_0014")
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
            if target == "head":

                def parity(c):
                    ctx = MigrationContext.configure(c, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
                    return compare_metadata(ctx, [t.metadata, legacy])

                assert await conn.run_sync(parity) == []
                for table in (t.independent_report_archives, t.independent_retest_archives):
                    actual = await conn.run_sync(lambda c: inspect(c).get_indexes(table.name))
                    assert {i["name"] for i in actual if not i.get("duplicates_constraint")} == {i.name for i in table.indexes}


async def archive_and_constraints(sf, engine, project, first, second):
    report_repo, retest_repo = IndependentReportRepository(sf), IndependentRetestRepository(sf)
    saved = await report_repo.create_archive("owner", project, uuid4().hex, report(first))
    compared = await retest_repo.create_retest("owner", project, uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assert (await report_repo.get_archive("owner", project, saved["id"])) == saved
    assert (await retest_repo.get_retest("owner", project, compared["id"])) == compared
    for table, key, changes in (
        (t.independent_report_archives, saved["id"], [{"id": uuid4().hex}, {"id": uuid4().hex, "root_id": uuid4().hex, "revision": 0}, {"id": uuid4().hex, "root_id": uuid4().hex, "supersedes_id": "0" * 32}]),
        (t.independent_retest_archives, compared["id"], [{"id": uuid4().hex}, {"id": uuid4().hex, "baseline_assessment_id": "0" * 32}, {"id": uuid4().hex, "retest_run_id": first["run_id"]}, {"id": uuid4().hex, "created_at_ms": 0}]),
    ):
        async with engine.connect() as conn:
            row = dict((await conn.execute(select(table).where(table.c.id == key))).mappings().one())
        for change in changes:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(table).values(**{**row, **change}))


@pytest.mark.parametrize("prepared", ["eval_0011"], indirect=True)
@pytest.mark.asyncio
async def test_sqlite_additive_upgrade_downgrade_repeat_and_old_accounts_rows(tasks):
    first, second, old = await seed_legacy(tasks)
    engine = tasks[2]
    before = await rows(engine, old)
    await cycle(engine, old, before)
    await archive_and_constraints(tasks[1].sf, engine, tasks[3], first, second)
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_key_check"))).all() == []
    before_final = await rows(engine, old)
    assert {k: v for k, v in before_final.items() if k != t.dispatch_audit.name} == {k: v for k, v in before.items() if k != t.dispatch_audit.name}
    assert all(row in before_final[t.dispatch_audit.name] for row in before[t.dispatch_audit.name])
    assert len(before_final[t.dispatch_audit.name]) == len(before[t.dispatch_audit.name]) + 3
    await asyncio.to_thread(migrate, engine.url, "eval_0011")
    assert await rows(engine, old) == before_final
    await asyncio.to_thread(migrate, engine.url, "head")
    assert await rows(engine, old) == before_final


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.parametrize("prepared", ["eval_0011"], indirect=True)
@pytest.mark.asyncio
async def test_postgresql_owned_database_additive_real_history_parity_and_constraints(tasks):
    import psycopg
    from psycopg import sql
    from sqlalchemy.ext.asyncio import async_sessionmaker

    first, second, old = await seed_legacy(tasks)
    seed = await rows(tasks[2], old)
    source_url = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    database = "devpilot_ind_archive_test_" + uuid4().hex

    def database_action(action):
        assert action in {"CREATE", "DROP"}
        with psycopg.connect(source_url.render_as_string(hide_password=False), autocommit=True) as conn:
            conn.execute(sql.SQL(action + " DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(database_action, "CREATE")
    engine = create_async_engine(DatabaseConfig(backend="postgres", postgres_url=source_url.set(database=database).render_as_string(hide_password=False)).app_sqlalchemy_url)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: ComponentRow.__table__.create(c))
            await conn.run_sync(lambda c: UserRow.__table__.create(c))
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        with schema._MIGRATION_LOCK:
            # Explicit historical start, never the provided shared database.
            config = Config()
            config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
            config.attributes["engine_url"] = engine.url
            config.attributes["postgres_schema"] = ""
            await asyncio.to_thread(command.upgrade, config, "eval_0011")
        async with engine.begin() as conn:
            for table in old:
                if seed[table.name]:
                    await conn.execute(insert(table), seed[table.name])
        before = await rows(engine, old)
        await cycle(engine, old, before)
        await archive_and_constraints(async_sessionmaker(engine, expire_on_commit=False), engine, tasks[3], first, second)
        before_final = await rows(engine, old)
        assert {k: v for k, v in before_final.items() if k != t.dispatch_audit.name} == {k: v for k, v in before.items() if k != t.dispatch_audit.name}
        assert all(row in before_final[t.dispatch_audit.name] for row in before[t.dispatch_audit.name])
        assert len(before_final[t.dispatch_audit.name]) == len(before[t.dispatch_audit.name]) + 3
        await asyncio.to_thread(migrate, engine.url, "eval_0011")
        assert await rows(engine, old) == before_final
        await asyncio.to_thread(migrate, engine.url, "head")
        assert await rows(engine, old) == before_final
    finally:
        await engine.dispose()
        await asyncio.to_thread(database_action, "DROP")
