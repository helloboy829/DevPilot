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

MATERIAL_TABLES = {
    "evaluation_material_batches",
    "evaluation_material_components",
    "evaluation_material_artifacts",
    "evaluation_material_artifact_components",
}
PREVIEW_TABLE = "evaluation_material_preview_receipts"


def migrate(url, target):
    with schema._MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
        config.attributes.update(engine_url=url, postgres_schema="")
        (command.downgrade if target == "eval_0021" else command.upgrade)(config, target)


@pytest.mark.asyncio
async def test_material_intake_migration_is_reversible_and_matches_metadata(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'material-intake.db'}")
    try:
        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            found_tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert MATERIAL_TABLES <= found_tables
        assert PREVIEW_TABLE in found_tables
        assert MATERIAL_TABLES <= set(tables.metadata.tables)
        assert PREVIEW_TABLE in tables.metadata.tables
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

        await asyncio.to_thread(migrate, engine.url, "eval_0021")
        async with engine.connect() as connection:
            downgraded_tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert MATERIAL_TABLES.isdisjoint(downgraded_tables)
        assert PREVIEW_TABLE not in downgraded_tables

        await asyncio.to_thread(migrate, engine.url, "head")
        async with engine.connect() as connection:
            upgraded_tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert MATERIAL_TABLES <= upgraded_tables
    finally:
        await engine.dispose()


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URI"), reason="Dedicated PostgreSQL test server not configured")
@pytest.mark.asyncio
async def test_material_intake_postgresql_schema_parity_and_reversible_upgrade():
    import psycopg
    from psycopg import sql

    source = make_url(os.environ["TEST_POSTGRES_URI"]).set(drivername="postgresql", database="postgres")
    admin_url = source.render_as_string(hide_password=False)
    database = "devpilot_material_test_" + uuid4().hex

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

        await asyncio.to_thread(migrate, engine.url, "eval_0021")
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert MATERIAL_TABLES.isdisjoint(names)
        assert PREVIEW_TABLE not in names

        await schema.upgrade_evaluation_schema(engine)
        async with engine.connect() as connection:
            names = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert MATERIAL_TABLES <= names
        assert PREVIEW_TABLE in names
    finally:
        await engine.dispose()
        await asyncio.to_thread(drop)
