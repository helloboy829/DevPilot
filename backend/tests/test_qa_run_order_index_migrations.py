"""SQLite migration regression for owner-visible run ordering."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.evaluation import schema


def _config(url):
    value = Config()
    value.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
    value.attributes.update(engine_url=make_url(url), postgres_schema="")
    return value


def test_run_order_index_supports_keyset_page_query(tmp_path):
    database = tmp_path / "run-order-index.db"
    url = f"sqlite+aiosqlite:///{database.as_posix()}"
    with schema._MIGRATION_LOCK:
        command.upgrade(_config(url), "eval_0019")
        command.upgrade(_config(url), "head")

    engine = create_engine(make_url(url).set(drivername="sqlite"))
    try:
        with engine.connect() as connection:
            indexes = connection.execute(text("PRAGMA index_list('evaluation_dispatch_runs')")).all()
            index_names = {row[1] for row in indexes}
            assert "ix_evaluation_dispatch_run_project_started_id" in index_names

            plan = connection.execute(
                text("EXPLAIN QUERY PLAN SELECT id FROM evaluation_dispatch_runs WHERE project_id = :project_id ORDER BY started_at_ms DESC, id ASC LIMIT 51"),
                {"project_id": "synthetic-project"},
            ).all()
            assert any("ix_evaluation_dispatch_run_project_started_id" in row[3] for row in plan)
            assert not any("USE TEMP B-TREE FOR ORDER BY" in row[3] for row in plan)
    finally:
        engine.dispose()
