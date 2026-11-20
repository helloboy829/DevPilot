"""Additive assigned-signature schema, history preservation and DB constraints."""

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
from test_approval_requests import APPROVER, REQUEST, SIGNATURE, VIEW, cmd, pending, signature
from test_dispatch_journal import prepared as prepared
from test_qa_assessments import assessments as assessments
from test_qa_assessments import complete as complete
from test_qa_evidence import captured as captured
from test_review_tasks import tasks as tasks

from app.evaluation import schema
from app.evaluation import tables as t
from app.evaluation.qa_approvals import ApprovalCreate
from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.component_tests.model import ComponentRow

NEW = {t.approval_requests.name, t.approval_request_events.name, t.approval_request_views.name, t.response_artifacts.name}
OLD = [ComponentRow.__table__, *[table for table in t.metadata.sorted_tables if table.name not in NEW]]


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes.update(engine_url=url, postgres_schema="")
        (command.downgrade if target == "eval_0016" else command.upgrade)(config, target)


async def old_rows(engine):
    async with engine.connect() as conn:
        return {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in OLD}


@pytest.mark.asyncio
async def test_assigned_signature_downgrade_upgrade_preserves_all_old_rows_and_schema_parity(tasks):
    repo, project, run, assessment, _, receipt = await pending(tasks)
    await repo.create_approval(
        "owner", project, run["id"], "7" * 32, ApprovalCreate(assessment_id=assessment["id"], assessment_hash=assessment["assessment_hash"], approver_id=APPROVER, decision="approved", expected_previous_revision=0, confirmed=True)
    )
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    engine = repo.sf.kw["bind"]
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
    before = await old_rows(engine)
    await asyncio.to_thread(migrate, engine.url, "eval_0016")
    async with engine.connect() as conn:
        assert NEW.isdisjoint(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0016"
    assert await old_rows(engine) == before
    await asyncio.to_thread(migrate, engine.url, "head")
    await schema.upgrade_evaluation_schema(engine)
    assert await old_rows(engine) == before
    harness = MetaData()
    ComponentRow.__table__.to_metadata(harness)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0020"
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
        for table in (t.approval_requests, t.approval_request_events, t.approval_request_views):
            assert (await conn.execute(select(table))).all() == []

        def parity(connection):
            context = MigrationContext.configure(connection, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
            return compare_metadata(context, [t.metadata, harness])

        assert await conn.run_sync(parity) == []


@pytest.mark.asyncio
async def test_request_view_event_foreign_keys_state_and_unique_operation_constraints(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    async with repo.sf() as session:
        rows = {table.name: dict((await session.execute(select(table))).mappings().one()) for table in (t.approval_requests, t.approval_request_events, t.approval_request_views)}
    for table, changes in (
        (
            t.approval_requests,
            [
                {},
                {"id": "6" * 32, "run_id": "missing"},
                {"id": "6" * 32, "assessment_id": "6" * 32},
                {"id": "6" * 32, "owner_id": APPROVER},
                {"id": "6" * 32, "status": "approved"},
                {"id": "6" * 32, "expires_at_ms": receipt["created_at_ms"]},
            ],
        ),
        (t.approval_request_events, [{}, {"revision": 2}, {"revision": 0, "operation_id": "6" * 32}, {"revision": 2, "operation_id": "6" * 32, "action": "sent"}, {"request_id": "6" * 32}]),
        (t.approval_request_views, [{}, {"id": "6" * 32, "request_id": "6" * 32}, {"id": "6" * 32, "request_revision": 2}, {"id": "6" * 32, "expires_at_ms": 0}]),
    ):
        for change in changes:
            with pytest.raises(IntegrityError):
                async with repo.sf.begin() as session:
                    await session.execute(insert(table).values({**rows[table.name], **change}))


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_postgresql_assigned_signature_migration_parity_and_constraints(tasks):
    import psycopg
    from psycopg import sql

    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    source_engine = repo.sf.kw["bind"]
    async with source_engine.connect() as conn:
        source_names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        component_rows = [dict(row) for row in (await conn.execute(select(ComponentRow.__table__))).mappings()]
        source_rows = {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in t.metadata.sorted_tables if table.name in source_names}

    source = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    admin_url = source.render_as_string(hide_password=False)
    database = "devpilot_approval_request_test_" + uuid4().hex

    def database_action(action):
        assert action in {"CREATE", "DROP"}
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL(action + " DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(database_action, "CREATE")
    engine = None
    try:
        engine = create_async_engine(
            DatabaseConfig(
                backend="postgres",
                postgres_url=source.set(database=database).render_as_string(hide_password=False),
            ).app_sqlalchemy_url
        )
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: ComponentRow.__table__.create(c))
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))

        await schema.upgrade_evaluation_schema(engine)

        harness = MetaData()
        ComponentRow.__table__.to_metadata(harness)
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0020"
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"

            def parity(connection):
                context = MigrationContext.configure(
                    connection,
                    opts={
                        "version_table": "devpilot_alembic_version",
                        "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version"),
                    },
                )
                return compare_metadata(context, [t.metadata, harness])

            assert await conn.run_sync(parity) == []

        async with engine.begin() as conn:
            for row in component_rows:
                await conn.execute(insert(ComponentRow.__table__).values(**row))
            for table in t.metadata.sorted_tables:
                for row in source_rows.get(table.name, []):
                    await conn.execute(insert(table).values(**row))

        from app.evaluation.approval_requests import ApprovalRequestRepository
        from app.evaluation.qa_approvals import ApprovalRepository

        pg_repo = ApprovalRequestRepository(
            async_sessionmaker(engine, expire_on_commit=False),
            protection=repo.protection,
            evidence_protection=repo.evidence_protection,
            clock_ms=repo.clock_ms,
        )
        await pg_repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
        await pg_repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))

        async with engine.connect() as conn:
            assert await ApprovalRepository._has_authenticated_approval(conn, receipt["run_id"])

        request_row = source_rows[t.approval_requests.name][0]
        event_row = source_rows[t.approval_request_events.name][0]
        view_row = source_rows[t.approval_request_views.name][0]

        invalid_requests = (
            {"owner_id": APPROVER},
            {"run_id": "missing-run"},
            {"assessment_id": "6" * 32},
            {"status": "approved"},
            {"expires_at_ms": request_row["created_at_ms"]},
            {"status": "approved", "revision": 2, "latest_approval_id": "6" * 32},
        )
        for changes in invalid_requests:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(t.approval_requests).values({**request_row, "id": "8" * 32, **changes}))

        for changes in (
            {"request_id": "6" * 32},
            {"revision": 2, "operation_id": event_row["operation_id"]},
            {"action": "sent"},
        ):
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(t.approval_request_events).values({**event_row, **changes}))

        with pytest.raises(IntegrityError):
            async with engine.begin() as conn:
                await conn.execute(insert(t.approval_request_views).values({**view_row, "request_id": "6" * 32}))
    finally:
        if engine is not None:
            await engine.dispose()
        await asyncio.to_thread(database_action, "DROP")
