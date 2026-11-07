"""App-owned, versioned migrations; synchronous Alembic work stays off the loop."""

import asyncio
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

# Alembic's module proxies are process-global, so serialize in-process commands.
_MIGRATION_LOCK = threading.Lock()


def _upgrade(url, postgres_schema):
    with _MIGRATION_LOCK:
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.attributes["engine_url"] = url
        config.attributes["postgres_schema"] = postgres_schema
        command.upgrade(config, "head")


async def upgrade_evaluation_schema(engine: AsyncEngine, *, postgres_schema: str = "") -> None:
    if engine.echo:
        raise ValueError("Evaluation data requires database.echo_sql=false to protect sample contents")
    if engine.dialect.name not in {"sqlite", "postgresql"}:
        raise ValueError("Evaluation persistence requires SQLite or PostgreSQL")
    if engine.dialect.name == "sqlite" and engine.url.database in {None, "", ":memory:"}:
        raise ValueError("Evaluation data requires a persistent database")
    await asyncio.to_thread(_upgrade, engine.url, postgres_schema)
