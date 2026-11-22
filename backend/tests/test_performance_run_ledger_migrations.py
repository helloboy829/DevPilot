"""SQLite migration reversibility and metadata parity for PERF-02."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.evaluation import schema, tables
from deerflow.config.database_config import DatabaseConfig


@pytest.mark.asyncio
async def test_performance_run_ledger_migration_is_reversible_and_matches_metadata(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'performance-run-ledger.db'}")
    try:
        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
            differences = await connection.run_sync(
                lambda conn: compare_metadata(
                    MigrationContext.configure(
                        conn,
                        opts={"include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "devpilot_alembic_version")},
                    ),
                    tables.metadata,
                )
            )
        expected = {
            "evaluation_performance_runs",
            "evaluation_performance_dispatches",
            "evaluation_performance_response_artifacts",
            "evaluation_performance_run_audit",
            "evaluation_performance_evidence_access_grants",
        }
        assert expected <= names
        assert differences == []

        def downgrade():
            config = Config()
            config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
            config.attributes.update(engine_url=engine.url, postgres_schema="")
            command.downgrade(config, "eval_0024")

        await asyncio.to_thread(downgrade)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert expected.isdisjoint(names)

        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert expected <= names
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_performance_run_ledger_postgresql_migration_is_reversible_and_matches_metadata():
    import psycopg
    from psycopg import sql

    source = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    admin_url = source.render_as_string(hide_password=False)
    database = "devpilot_perf_ledger_test_" + uuid4().hex

    def create():
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

    def drop():
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))

    await asyncio.to_thread(create)
    url = source.set(database=database).render_as_string(hide_password=False)
    engine = create_async_engine(DatabaseConfig(backend="postgres", postgres_url=url).app_sqlalchemy_url)
    try:
        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            differences = await connection.run_sync(
                lambda conn: compare_metadata(
                    MigrationContext.configure(
                        conn,
                        opts={"include_object": lambda obj, name, kind, reflected, compared: not (kind == "table" and name == "devpilot_alembic_version")},
                    ),
                    tables.metadata,
                )
            )
            assert differences == []
            assert (await connection.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0027"

        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes.update(engine_url=engine.url, postgres_schema="")
        await asyncio.to_thread(command.downgrade, config, "eval_0026")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
            assert "evaluation_performance_evidence_access_grants" not in names
            assert (await connection.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0026"

        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0027"
    finally:
        await engine.dispose()
        await asyncio.to_thread(drop)
