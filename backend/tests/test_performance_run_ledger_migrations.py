"""SQLite migration reversibility and metadata parity for PERF-02."""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from app.evaluation import schema, tables


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
            "evaluation_performance_run_audit",
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
