"""Additive App ledger preserves eval_0009 and matches SQLite/PostgreSQL schemas."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_qa_evidence import observation, review

from app.evaluation import schema
from app.evaluation import tables as t
from deerflow.config.database_config import DatabaseConfig

TASK_TABLES = {table.name for table in (t.review_tasks, t.review_task_assignments, t.review_task_decisions, t.review_task_resolutions, t.review_task_audit)}


def migrate(url, revision):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = ""
        if revision == "eval_0009":
            command.downgrade(config, revision)
        else:
            command.upgrade(config, revision)


@pytest.mark.parametrize("prepared", ["eval_0009"], indirect=True)
@pytest.mark.asyncio
async def test_additive_upgrade_downgrade_and_repeat_preserve_every_previous_table(captured):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, review(case))
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
    async with engine.connect() as conn:
        previous_names = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
    old = [table for table in t.metadata.sorted_tables if table.name in previous_names]

    async def snapshot():
        async with engine.connect() as conn:
            return {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in old}

    before = await snapshot()
    for revision in ("head", "head", "eval_0009", "head"):
        await asyncio.to_thread(migrate, engine.url, revision)
        assert await snapshot() == before
        async with engine.connect() as conn:
            tables = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
            expected = "eval_0009" if revision == "eval_0009" else "eval_0013"
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == expected
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
            assert TASK_TABLES.isdisjoint(tables) if revision == "eval_0009" else TASK_TABLES.issubset(tables)
    assert (await repo.open_case("owner", project, run["id"], 1))["reviews"][0]["note"] == "SYNTHETIC_REVIEW_NOTE"


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_postgresql_owned_database_schema_parity_and_harness_ledger():
    import psycopg
    from psycopg import sql

    # Never migrate the provided shared database; create and drop only our exact UUID database.
    source = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    admin_url = source.render_as_string(hide_password=False)
    database = "devpilot_review_test_" + uuid4().hex

    def create():
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

    def drop():
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(create)
    url = source.set(database=database).render_as_string(hide_password=False)
    engine = create_async_engine(DatabaseConfig(backend="postgres", postgres_url=url).app_sqlalchemy_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS')"))
        await schema.upgrade_evaluation_schema(engine)
        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as conn:

            def compare(connection):
                context = MigrationContext.configure(connection, opts={"version_table": "devpilot_alembic_version", "include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "alembic_version")})
                return compare_metadata(context, t.metadata)

            assert await conn.run_sync(compare) == []
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0013"
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS"
        await asyncio.to_thread(migrate, engine.url, "eval_0009")
        async with engine.connect() as conn:
            assert TASK_TABLES.isdisjoint(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        await schema.upgrade_evaluation_schema(engine)
    finally:
        await engine.dispose()
        await asyncio.to_thread(drop)
