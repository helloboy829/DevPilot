"""Assessment ledger is additive and old independent review history is preserved."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from _migration_snapshot import snapshot_rows
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, insert, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_review_tasks import A, B, submit
from test_review_tasks import tasks as tasks

from app.evaluation import schema
from app.evaluation import tables as t
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.models import ComponentRow

AFTER_EVAL_0010 = {
    t.run_assessments.name,
    t.independent_report_archives.name,
    t.independent_retest_archives.name,
    t.exports.name,
    t.export_audit.name,
    t.external_qa_intakes.name,
    t.external_qa_intake_audit.name,
    t.run_approvals.name,
    t.approval_audit.name,
    t.approval_signoff_policies.name,
    t.approval_requests.name,
    t.approval_request_events.name,
    t.approval_request_views.name,
    t.response_artifacts.name,
    t.evidence_access_grants.name,
    t.evidence_access_audit.name,
    t.material_batches.name,
    t.material_components.name,
    t.material_artifacts.name,
    t.material_artifact_components.name,
    t.material_preview_receipts.name,
    t.performance_scenarios.name,
    t.performance_scenario_audit.name,
}


def migrate(url, down=False, target=None):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        (command.downgrade if down else command.upgrade)(config, target or ("eval_0010" if down else "head"))


@pytest.mark.parametrize("prepared", ["eval_0010"], indirect=True)
@pytest.mark.asyncio
async def test_additive_upgrade_repeat_downgrade_preserve_all_previous_tables(tasks):
    task_repo, repo, engine, project, run, _, _, task = tasks
    await submit(task_repo, A, task)
    await submit(task_repo, B, task)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    old = [table for table in t.metadata.sorted_tables if table.name in names and table.name not in AFTER_EVAL_0010] + [ComponentRow.__table__]
    legacy = MetaData()
    ComponentRow.__table__.to_metadata(legacy)

    async def snapshot():
        async with engine.connect() as conn:
            return await conn.run_sync(lambda connection: snapshot_rows(connection, old))

    before = await snapshot()
    for down in (False, False, True, False):
        await asyncio.to_thread(migrate, engine.url, down)
        assert await snapshot() == before
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == ("eval_0010" if down else "eval_0024")
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
            assert (t.run_assessments.name in tables) != down
            assert (t.evidence_access_grants.name in tables) != down
            assert (t.evidence_access_audit.name in tables) != down
            if not down:

                def parity(c):
                    context = MigrationContext.configure(c, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
                    return compare_metadata(context, [t.metadata, legacy])

                assert await conn.run_sync(parity) == []


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.parametrize("prepared", ["eval_0010"], indirect=True)
@pytest.mark.asyncio
async def test_postgresql_additive_upgrade_preserves_real_review_rows_and_constraints(tasks):
    import psycopg
    from psycopg import sql
    from sqlalchemy.exc import IntegrityError

    task_repo, _, source_engine, project, run, _, _, task = tasks
    await submit(task_repo, A, task)
    await submit(task_repo, B, task)
    async with source_engine.connect() as conn:
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        old = [table for table in t.metadata.sorted_tables if table.name in names and table.name not in AFTER_EVAL_0010]
        seed = await conn.run_sync(lambda connection: snapshot_rows(connection, [ComponentRow.__table__, *old]))
    source = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    admin_url = source.render_as_string(hide_password=False)
    database = "devpilot_assessment_test_" + uuid4().hex

    def database_action(action):
        assert action in {"CREATE", "DROP"}
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL(action + " DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(database_action, "CREATE")
    url = source.set(database=database).render_as_string(hide_password=False)
    engine = None
    try:
        engine = create_async_engine(DatabaseConfig(backend="postgres", postgres_url=url).app_sqlalchemy_url)
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: ComponentRow.__table__.create(c))
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        await asyncio.to_thread(migrate, engine.url, target="eval_0010")
        async with engine.begin() as conn:
            for table in [ComponentRow.__table__, *old]:
                if seed[table.name]:
                    await conn.execute(insert(table), seed[table.name])
        async with engine.connect() as conn:
            before = await conn.run_sync(lambda connection: snapshot_rows(connection, [ComponentRow.__table__, *old]))
        for down in (False, False, True, False):
            await asyncio.to_thread(migrate, engine.url, down)
            async with engine.connect() as conn:
                assert await conn.run_sync(lambda connection: snapshot_rows(connection, [ComponentRow.__table__, *old])) == before
                assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
                assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == ("eval_0010" if down else "eval_0024")
        row = {"id": "c" * 32, "owner_id": "owner", "project_id": project, "run_id": run["id"], "revision": 1, "created_at_ms": 1, "request_hash": "a" * 64, "summary_hash": "b" * 64, "document": {}, "assessment_hash": "d" * 64}
        async with engine.begin() as conn:
            await conn.execute(insert(t.run_assessments).values(**row))
        for change in ({"id": "e" * 32}, {"id": "e" * 32, "revision": 0}, {"id": "e" * 32, "revision": 1001}, {"id": "e" * 32, "revision": 2, "created_at_ms": 0}, {"id": "e" * 32, "revision": 2, "project_id": "other"}):
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(t.run_assessments).values(**{**row, **change}))
    finally:
        if engine is not None:
            await engine.dispose()
        await asyncio.to_thread(database_action, "DROP")
