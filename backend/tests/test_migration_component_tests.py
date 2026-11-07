"""Verify component-test upgrades on clean and partially initialized databases."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

import deerflow.persistence.models  # noqa: F401 -- registers table metadata
from deerflow.persistence.base import Base
from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision, _upgrade, bootstrap_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("preexisting_tables", [False, True])
async def test_component_test_upgrade_is_complete_and_repeatable(tmp_path: Path, preexisting_tables: bool):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'upgrade.db').as_posix()}")
    try:
        await asyncio.to_thread(_upgrade, _get_alembic_config(engine), "0011_mcp_tasks")
        if preexisting_tables:
            async with engine.begin() as conn:
                for name in ("component_tests", "component_test_runs"):
                    await conn.run_sync(lambda sync_conn, name=name: Base.metadata.tables[name].create(sync_conn))

        await bootstrap_schema(engine, backend="sqlite")
        await bootstrap_schema(engine, backend="sqlite")
        async with engine.connect() as conn:
            assert (await conn.execute(sa.text("SELECT version_num FROM alembic_version"))).scalar_one() == _get_head_revision()
            tables = await conn.run_sync(lambda c: set(sa.inspect(c).get_table_names()))
            assert {"runs", "mcp_tasks", "component_tests", "component_test_runs"} <= tables
            columns = await conn.run_sync(lambda c: {x["name"] for x in sa.inspect(c).get_columns("component_test_runs")})
            assert {"user_id", "component_id", "status", "params", "result", "raw_path"} <= columns
            indexes = await conn.run_sync(lambda c: {x["name"] for x in sa.inspect(c).get_indexes("component_test_runs")})
            assert {"ix_component_test_runs_user_id", "ix_component_test_runs_status", "ix_component_test_runs_component_id"} <= indexes
    finally:
        await engine.dispose()
