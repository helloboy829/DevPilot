"""eval_0013 preserves prior SQLite/PostgreSQL rows, ledgers and schema parity."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, event, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_authorized_qa_exports import OWNER, setup_export
from test_evaluation_registry_router import api as api

from app.evaluation import schema
from app.evaluation import tables as t
from app.evaluation.authorized_exports import ExportCreate, ExportRepository
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.component_tests.model import ComponentRow
from deerflow.persistence.user.model import UserRow

NEW = {t.exports.name, t.export_audit.name}
# Freeze this revision's historical table population; eval_0014/eval_0015 have
# their own full-head parity/preservation regressions and must not be queried
# after downgrade.
APP_TABLES = [table for table in t.metadata.sorted_tables if table.name not in {t.external_qa_intakes.name, t.external_qa_intake_audit.name, t.run_approvals.name, t.approval_audit.name}]
OLD = [ComponentRow.__table__, UserRow.__table__, *[table for table in APP_TABLES if table.name not in NEW]]


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        (command.downgrade if target == "eval_0012" else command.upgrade)(config, target)


async def rows(engine):
    async with engine.connect() as conn:
        return {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in OLD}


async def seed(api, monkeypatch):
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    engine = repo.sf.kw["bind"]

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.connect() as conn:
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: UserRow.__table__.create(c))
        await conn.execute(insert(UserRow.__table__).values(id=OWNER, email="synthetic@example.invalid", password_hash="SYNTHETIC_PASSWORD_HASH", system_role="user"))
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
    await asyncio.to_thread(migrate, engine.url, "eval_0012")
    return repo, path, payload


async def cycle(engine):
    before = await rows(engine)
    historical = MetaData()
    for table in APP_TABLES:
        table.to_metadata(historical)
    legacy = MetaData()
    for table in (ComponentRow.__table__, UserRow.__table__):
        table.to_metadata(legacy)
    for target in ("eval_0013", "eval_0013", "eval_0012", "eval_0013"):
        await asyncio.to_thread(migrate, engine.url, target)
        assert await rows(engine) == before
        async with engine.connect() as conn:
            names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
            assert NEW.isdisjoint(names) if target == "eval_0012" else NEW.issubset(names)
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == ("eval_0012" if target == "eval_0012" else "eval_0013")
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
            if target == "eval_0013":

                def parity(c):
                    ctx = MigrationContext.configure(c, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
                    return compare_metadata(ctx, [historical, legacy])

                assert await conn.run_sync(parity) == []
                for table in (t.exports, t.export_audit):
                    indexes = await conn.run_sync(lambda c: inspect(c).get_indexes(table.name))
                    assert {i["name"] for i in indexes if not i.get("duplicates_constraint")} == {i.name for i in table.indexes}


async def exercise(repo, path, payload, engine):
    project, export_id = path.split("/")[-3], path.split("/")[-1]
    receipt = await repo.create(OWNER, project, export_id, ExportCreate.model_validate(payload))
    package = await repo.open_bundle(OWNER, project, export_id, receipt["receipt_hash"])
    assert package.startswith(b"PK")
    assert [e["sequence"] for e in await repo.audit(OWNER, project, export_id)] == [1, 2]
    async with engine.connect() as conn:
        row = dict((await conn.execute(select(t.exports))).mappings().one())
        audit = dict((await conn.execute(select(t.export_audit).where(t.export_audit.c.sequence == 1))).mappings().one())
    for table, original, changes in (
        (t.exports, row, [{"id": uuid4().hex, "project_id": "missing"}, {"id": uuid4().hex, "plan_id": "missing"}, {"id": uuid4().hex, "created_at_ms": 0}]),
        (t.export_audit, audit, [{"id": uuid4().hex}, {"id": uuid4().hex, "sequence": 0}, {"id": uuid4().hex, "sequence": 3, "action": "invalid"}, {"id": uuid4().hex, "sequence": 3, "export_id": uuid4().hex}]),
    ):
        for change in changes:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(table).values(**{**original, **change}))


@pytest.mark.asyncio
async def test_sqlite_additive_migration_real_frozen_rows_constraints_and_parity(api, monkeypatch):
    repo, path, payload = await seed(api, monkeypatch)
    engine = repo.sf.kw["bind"]
    await cycle(engine)
    before = await rows(engine)
    await exercise(repo, path, payload, engine)
    assert await rows(engine) == before
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_key_check"))).all() == []
    await asyncio.to_thread(migrate, engine.url, "eval_0012")
    assert await rows(engine) == before
    await asyncio.to_thread(migrate, engine.url, "eval_0013")
    assert await rows(engine) == before


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_postgres_owned_database_preserves_all_previous_rows_and_real_export(api, monkeypatch):
    import psycopg
    from psycopg import sql

    repo, path, payload = await seed(api, monkeypatch)
    source = await rows(repo.sf.kw["bind"])
    url = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    database = "devpilot_export_test_" + uuid4().hex

    def database_action(action):
        assert action in {"CREATE", "DROP"}
        with psycopg.connect(url.render_as_string(hide_password=False), autocommit=True) as conn:
            conn.execute(sql.SQL(action + " DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(database_action, "CREATE")
    engine = create_async_engine(DatabaseConfig(backend="postgres", postgres_url=url.set(database=database).render_as_string(hide_password=False)).app_sqlalchemy_url)
    try:
        async with engine.begin() as conn:
            for table in (ComponentRow.__table__, UserRow.__table__):
                await conn.run_sync(lambda c, table=table: table.create(c))
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        with schema._MIGRATION_LOCK:
            config = Config()
            config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
            config.attributes["engine_url"] = engine.url
            config.attributes["postgres_schema"] = ""
            await asyncio.to_thread(command.upgrade, config, "eval_0012")
        async with engine.begin() as conn:
            for table in OLD:
                if source[table.name]:
                    await conn.execute(insert(table), source[table.name])
        await cycle(engine)
        postgres_repo = ExportRepository(async_sessionmaker(engine, expire_on_commit=False), policy=repo._policy, protection=repo._export_protection, clock_ms=repo.clock_ms)
        before = await rows(engine)
        await exercise(postgres_repo, path, payload, engine)
        assert await rows(engine) == before
        await asyncio.to_thread(migrate, engine.url, "eval_0012")
        assert await rows(engine) == before
        await asyncio.to_thread(migrate, engine.url, "eval_0013")
        assert await rows(engine) == before
    finally:
        await engine.dispose()
        await asyncio.to_thread(database_action, "DROP")
