"""Independent revision ledger; only owns evaluation tables, never Harness tables."""

import asyncio

from alembic import context
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.evaluation.tables import metadata
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args


def include_object(object_, name, type_, reflected, compare_to):
    table_name = name if type_ == "table" else getattr(getattr(object_, "table", None), "name", None)
    return table_name in metadata.tables


def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata, version_table="devpilot_alembic_version", include_object=include_object, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def run():
    url = context.config.attributes["engine_url"]
    schema = context.config.attributes.get("postgres_schema", "")
    kwargs = {"poolclass": NullPool, "hide_parameters": True}
    if url.get_backend_name() == "postgresql":
        kwargs["connect_args"] = build_asyncpg_connect_args(schema)
    engine = create_async_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def sqlite_settings(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

    try:
        async with engine.begin() as connection:
            if engine.dialect.name == "postgresql":
                await connection.exec_driver_sql("SELECT pg_advisory_xact_lock(719623057)")
            else:
                # SQLite batch migrations may rebuild a parent table that already
                # has child foreign keys.  Disable enforcement for this isolated
                # migration transaction, then verify the complete graph after the
                # commit on a fresh connection before allowing the engine to close.
                await connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                await connection.exec_driver_sql("BEGIN IMMEDIATE")
            await connection.run_sync(migrate)
        if engine.dialect.name == "sqlite":
            async with engine.connect() as connection:
                await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
                violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).all()
                if violations:
                    raise RuntimeError(f"SQLite foreign-key check failed after evaluation migration: {violations!r}")
    finally:
        await engine.dispose()


asyncio.run(run())
