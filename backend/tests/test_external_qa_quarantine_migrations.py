"""eval_0014/eval_0015 are additive, preserve ALL previous rows and the Harness ledger."""

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
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_authorized_qa_exports import OWNER
from test_authorized_qa_exports_migrations import seed as seed_export
from test_evaluation_registry_router import api as api
from test_external_qa_quarantine import declared_pair, request_for

from app.evaluation import schema
from app.evaluation import tables as t
from app.evaluation.authorized_exports import ExportCreate
from app.evaluation.external_qa_quarantine import ExternalQAIntakeCreate, ExternalQAIntakeRepository
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.component_tests.model import ComponentRow
from deerflow.persistence.user.model import UserRow

NEW = {t.external_qa_intakes.name, t.external_qa_intake_audit.name, t.run_approvals.name, t.approval_audit.name}
OLD = [ComponentRow.__table__, UserRow.__table__, *[table for table in t.metadata.sorted_tables if table.name not in NEW]]


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        (command.downgrade if target == "eval_0013" else command.upgrade)(config, target)


async def rows(engine):
    async with engine.connect() as conn:
        return {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in OLD}


async def seed(api, monkeypatch):
    export_repo, path, payload = await seed_export(api, monkeypatch)
    engine = export_repo.sf.kw["bind"]
    # seed_export leaves eval_0012; explicitly add only the historical export slice.
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = engine.url
        config.attributes["postgres_schema"] = ""
        await asyncio.to_thread(command.upgrade, config, "eval_0013")
    project, export_id = path.split("/")[-3], path.rsplit("/", 1)[1]
    source = await export_repo.create(OWNER, project, export_id, ExportCreate.model_validate(payload))
    return engine, source


async def cycle(engine):
    before = await rows(engine)
    legacy = MetaData()
    for table in (ComponentRow.__table__, UserRow.__table__):
        table.to_metadata(legacy)
    for target in ("head", "head", "eval_0013", "head"):
        await asyncio.to_thread(migrate, engine.url, target)
        assert await rows(engine) == before
        async with engine.connect() as conn:
            names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
            assert NEW.isdisjoint(names) if target == "eval_0013" else NEW.issubset(names)
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == ("eval_0013" if target == "eval_0013" else "eval_0015")
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
            if target == "head":

                def parity(c):
                    ctx = MigrationContext.configure(c, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
                    return compare_metadata(ctx, [t.metadata, legacy])

                assert await conn.run_sync(parity) == []
                for table in (t.external_qa_intakes, t.external_qa_intake_audit):
                    indexes = await conn.run_sync(lambda c: inspect(c).get_indexes(table.name))
                    assert {i["name"] for i in indexes if not i.get("duplicates_constraint")} == {i.name for i in table.indexes}


async def exercise(engine, source):
    repo = ExternalQAIntakeRepository(async_sessionmaker(engine, expire_on_commit=False), clock_ms=lambda: 20_000)
    intake_id = uuid4().hex
    receipt = await repo.create(OWNER, source["project_id"], intake_id, ExternalQAIntakeCreate.model_validate(request_for(source, *declared_pair(source))))
    assert (await repo.get(OWNER, source["project_id"], intake_id)) == receipt
    assert [e["sequence"] for e in await repo.audit(OWNER, source["project_id"], intake_id)] == [1]
    async with engine.connect() as conn:
        row = dict((await conn.execute(select(t.external_qa_intakes))).mappings().one())
        audit = dict((await conn.execute(select(t.external_qa_intake_audit))).mappings().one())
    for table, original, changes in (
        (
            t.external_qa_intakes,
            row,
            [
                {"id": uuid4().hex},  # Same export/original-run/canonical snapshot is unique.
                {"id": uuid4().hex, "snapshot_hash": "f" * 64, "project_id": "missing"},
                {"id": uuid4().hex, "export_id": uuid4().hex},
                {"id": uuid4().hex, "snapshot_hash": "f" * 64, "created_at_ms": 0},
                {"id": uuid4().hex, "snapshot_hash": "f" * 64, "canonical_receipt": ""},
                {"id": uuid4().hex, "snapshot_hash": "f" * 64, "canonical_reconciliation": "x" * 8193},
            ],
        ),
        (
            t.external_qa_intake_audit,
            audit,
            [
                {"id": uuid4().hex},
                {"id": uuid4().hex, "sequence": 0},
                {"id": uuid4().hex, "sequence": 2, "action": "approved"},
                {"id": uuid4().hex, "sequence": 2, "intake_id": uuid4().hex},
            ],
        ),
    ):
        for change in changes:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(table).values(**{**original, **change}))


@pytest.mark.asyncio
async def test_sqlite_fk_on_additive_migration_preserves_all_prior_rows(api, monkeypatch):
    engine, source = await seed(api, monkeypatch)
    await cycle(engine)
    before = await rows(engine)
    await exercise(engine, source)
    assert await rows(engine) == before
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
        assert (await conn.execute(text("PRAGMA foreign_key_check"))).all() == []
    await asyncio.to_thread(migrate, engine.url, "eval_0013")
    assert await rows(engine) == before
    await asyncio.to_thread(migrate, engine.url, "head")
    assert await rows(engine) == before


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_postgres_owned_database_preserves_export_history_and_schema_parity(api, monkeypatch):
    import psycopg
    from psycopg import sql

    sqlite, source_receipt = await seed(api, monkeypatch)
    source_rows = await rows(sqlite)
    url = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    database = "devpilot_quarantine_test_" + uuid4().hex

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
            await asyncio.to_thread(command.upgrade, config, "eval_0013")
        async with engine.begin() as conn:
            for table in OLD:
                if source_rows[table.name]:
                    await conn.execute(insert(table), source_rows[table.name])
        await cycle(engine)
        before = await rows(engine)
        await exercise(engine, source_receipt)
        assert await rows(engine) == before
        await asyncio.to_thread(migrate, engine.url, "eval_0013")
        assert await rows(engine) == before
        await asyncio.to_thread(migrate, engine.url, "head")
        assert await rows(engine) == before
    finally:
        await engine.dispose()
        await asyncio.to_thread(database_action, "DROP")
