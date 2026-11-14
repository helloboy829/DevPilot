"""eval_0015 is additive: downgrade drops only approval tables, old rows stay."""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import MetaData, event, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from test_evaluation_registry_router import api as api
from test_qa_approvals_router import APPROVAL, setup_approval
from test_qa_approvals_router import payload as approval_payload

from app.evaluation import schema
from app.evaluation import tables as t
from deerflow.persistence.component_tests.model import ComponentRow
from deerflow.persistence.user.model import UserRow

NEW = {t.run_approvals.name, t.approval_audit.name}
OLD = [ComponentRow.__table__, UserRow.__table__, *[table for table in t.metadata.sorted_tables if table.name not in NEW | {"devpilot_alembic_version"}]]


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        (command.downgrade if target == "eval_0014" else command.upgrade)(config, target)


async def rows(engine):
    async with engine.connect() as conn:
        return {table.name: [dict(row) for row in (await conn.execute(select(table).order_by(*table.primary_key.columns))).mappings()] for table in OLD}


async def prepare_harness_tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ComponentRow.__table__.create(c, checkfirst=True))
        await conn.run_sync(lambda c: UserRow.__table__.create(c, checkfirst=True))


@pytest.mark.asyncio
async def test_downgrade_preserves_history_and_upgrade_restores_empty_approval_tables(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    created = await client.post(root + "/approvals/" + APPROVAL, json=approval_payload(assessment))
    assert created.status_code == 200 and created.json()["revision"] == 1
    engine = app.state.evaluation_repo.sf.kw["bind"]
    await prepare_harness_tables(engine)
    before = await rows(engine)
    await asyncio.to_thread(migrate, engine.url, "eval_0014")
    async with engine.connect() as conn:
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        assert NEW.isdisjoint(names)
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0014"
    assert await rows(engine) == before
    await asyncio.to_thread(migrate, engine.url, "head")
    legacy = MetaData()
    for table in (ComponentRow.__table__, UserRow.__table__):
        table.to_metadata(legacy)
    async with engine.connect() as conn:
        names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        assert NEW.issubset(names)
        assert (await conn.execute(select(t.run_approvals))).all() == []
        assert (await conn.execute(select(t.approval_audit))).all() == []
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0015"

        def parity(c):
            context = MigrationContext.configure(c, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
            return compare_metadata(context, [t.metadata, legacy])

        assert await conn.run_sync(parity) == []
    assert await rows(engine) == before
    recreated = await client.post(root + "/approvals/" + APPROVAL, json=approval_payload(assessment))
    assert recreated.status_code == 200 and recreated.json()["revision"] == 1


@pytest.mark.asyncio
async def test_approval_tables_enforce_foreign_keys_revision_and_decision_checks(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    assert (await client.post(root + "/approvals/" + APPROVAL, json=approval_payload(assessment))).status_code == 200
    engine = app.state.evaluation_repo.sf.kw["bind"]
    await prepare_harness_tables(engine)

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    await engine.dispose()
    async with engine.connect() as conn:
        assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
    async with engine.connect() as conn:
        row = dict((await conn.execute(select(t.run_approvals))).mappings().one())
        audit = dict((await conn.execute(select(t.approval_audit))).mappings().one())
    for table, original, changes in (
        (
            t.run_approvals,
            row,
            [
                {"id": "f" * 32},  # Duplicate (run_id, revision) is unique.
                {"id": "f" * 32, "revision": 2, "decision": "passed"},
                {"id": "f" * 32, "revision": 0},
                {"id": "f" * 32, "revision": 2, "assessment_id": "f" * 32},
                {"id": "f" * 32, "revision": 2, "run_id": "missing-run"},
            ],
        ),
        (
            t.approval_audit,
            audit,
            [
                {"sequence": 0},
                {"sequence": 2, "action": "export_created"},
                {"sequence": 2, "run_id": "missing-run"},
            ],
        ),
    ):
        for change in changes:
            with pytest.raises(IntegrityError):
                async with engine.begin() as conn:
                    await conn.execute(insert(table).values(**{**original, **change}))
