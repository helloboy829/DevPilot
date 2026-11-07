from __future__ import annotations

import asyncio
import json

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation.datasets import DatasetImport, SourceDeclaration, parse_samples
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound
from app.evaluation.schema import upgrade_evaluation_schema


def source():
    return SourceDeclaration(label="Synthetic source", reference="fixture:qa-v1", authorization_basis="Synthetic data owned by tester", attested=True)


def content(question="Synthetic question", answer="Synthetic answer"):
    return json.dumps([{"sample_id": "q1", "input": question, "expected": answer, "source_ref": "record:1"}])


def samples(raw=None):
    return parse_samples(DatasetImport(revision=1, format="json", content=raw or content()))


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'evaluation.db'}")
    await upgrade_evaluation_schema(engine)
    result = EvaluationRepository(async_sessionmaker(engine, expire_on_commit=False))
    yield result, engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_migration_is_app_owned_repeatable_and_preserves_foreign_tables(repo):
    repository, engine = repo
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE foreign_fixture (id INTEGER)"))
        await conn.execute(text("INSERT INTO foreign_fixture VALUES (7)"))
    project = await repository.create_project("owner", "Synthetic project")
    await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        assert "devpilot_alembic_version" in tables
        assert "alembic_version" not in tables
        assert (await conn.execute(text("SELECT id FROM foreign_fixture"))).scalar() == 7
    assert (await repository.list_projects("owner"))[0]["id"] == project["id"]


@pytest.mark.asyncio
async def test_owner_scope_includes_every_child_and_gold(repo):
    repository, _ = repo
    project = await repository.create_project("owner", "Synthetic project")
    ds = await repository.create_dataset("owner", project["id"], "QA v1", "baseline", source())
    await repository.replace_samples("owner", project["id"], ds["id"], 1, samples())
    assert await repository.list_projects("other") == []
    for operation in (
        repository.list_datasets("other", project["id"]),
        repository.get_dataset("other", project["id"], ds["id"]),
        repository.read_samples("other", project["id"], ds["id"], references=True),
        repository.replace_samples("other", project["id"], ds["id"], 2, samples()),
        repository.freeze("other", project["id"], ds["id"], 2, "0" * 64),
        repository.audit("other", project["id"], ds["id"]),
    ):
        with pytest.raises(NotFound):
            await operation
    with pytest.raises(NotFound):
        await repository.create_dataset("other", project["id"], "QA", "baseline", source())
    assert "expected" not in (await repository.read_samples("owner", project["id"], ds["id"]))[0]
    assert (await repository.read_samples("owner", project["id"], ds["id"], references=True))[0]["expected"] == "Synthetic answer"


@pytest.mark.asyncio
async def test_revision_freeze_hash_audit_and_restart(repo):
    repository, engine = repo
    project = await repository.create_project("owner", "Synthetic project")
    pid = project["id"]
    ds = await repository.create_dataset("owner", pid, "QA", "acceptance", source())
    did = ds["id"]
    with pytest.raises(Conflict):
        await repository.freeze("owner", pid, did, 1, "0" * 64)
    imported = await repository.replace_samples("owner", pid, did, 1, samples())
    assert imported["revision"] == 2
    assert imported["sample_count"] == 1
    assert len(imported["content_hash"]) == 64
    with pytest.raises(Conflict):
        await repository.replace_samples("owner", pid, did, 1, samples(content("Changed")))
    with pytest.raises(Conflict):
        await repository.freeze("owner", pid, did, 2, "0" * 64)
    frozen = await repository.freeze("owner", pid, did, 2, imported["content_hash"])
    assert frozen["status"] == "frozen"
    assert frozen["frozen_by"] == "owner"
    assert frozen["revision"] == 3
    with pytest.raises(Conflict):
        await repository.replace_samples("owner", pid, did, 3, samples())
    with pytest.raises(Conflict):
        await repository.freeze("owner", pid, did, 3, imported["content_hash"])
    await engine.dispose()
    new_repo = EvaluationRepository(async_sessionmaker(engine, expire_on_commit=False))
    assert (await new_repo.get_dataset("owner", pid, did)) == frozen
    assert [row["action"] for row in await new_repo.audit("owner", pid, did)] == ["dataset_created", "samples_replaced", "dataset_frozen"]
    assert "Synthetic answer" not in json.dumps(await new_repo.audit("owner", pid, did))


@pytest.mark.asyncio
async def test_concurrent_import_has_exactly_one_winner(repo):
    repository, _ = repo
    p = await repository.create_project("owner", "Project")
    d = await repository.create_dataset("owner", p["id"], "QA", "baseline", source())
    results = await asyncio.gather(*[repository.replace_samples("owner", p["id"], d["id"], 1, samples(content(q))) for q in ("Q A", "Q B")], return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, Conflict) for r in results) == 1
    assert len(await repository.read_samples("owner", p["id"], d["id"])) == 1


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        "[]",
        "null",
        '[{"sample_id":"q1","input":"q","expected":"","source_ref":"r"}]',
        '[{"sample_id":"q1","input":"q","expected":"a","source_ref":"r","unknown":true}]',
        '[{"sample_id":"q1","input":"q","expected":"a","source_ref":"r","input":"hidden"}]',
        '[{"sample_id":"q1","input":"q","expected":NaN,"source_ref":"r"}]',
    ],
)
def test_invalid_imports_fail_without_echo(raw):
    with pytest.raises(ValueError) as error:
        samples(raw)
    assert "hidden" not in str(error.value)


def test_jsonl_and_duplicates_and_bounds():
    raw = content()[1:-1]
    assert parse_samples(DatasetImport(revision=1, format="jsonl", content=raw))[0].sample_id == "q1"
    repeated = json.loads(content()) * 2
    with pytest.raises(ValueError):
        samples(json.dumps(repeated))
    repeated[1] = dict(repeated[1], sample_id="q2", input="  SYNTHETIC   question ")
    with pytest.raises(ValueError):
        samples(json.dumps(repeated))
    with pytest.raises(ValueError):
        samples(json.dumps([dict(json.loads(content())[0], sample_id=f"q{i}", input=f"q{i}") for i in range(501)]))
    with pytest.raises(ValueError):
        SourceDeclaration(label="s", reference="r", authorization_basis=" ", attested=True)


@pytest.mark.asyncio
async def test_freeze_recomputes_persisted_hash_and_rejects_corruption(repo):
    from sqlalchemy import update

    from app.evaluation.tables import references

    repository, engine = repo
    p = await repository.create_project("owner", "Synthetic project")
    d = await repository.create_dataset("owner", p["id"], "QA", "baseline", source())
    imported = await repository.replace_samples("owner", p["id"], d["id"], 1, samples())
    async with engine.begin() as conn:
        await conn.execute(update(references).values(expected="tampered fixture"))
    with pytest.raises(Conflict):
        await repository.freeze("owner", p["id"], d["id"], 2, imported["content_hash"])
    assert (await repository.get_dataset("owner", p["id"], d["id"]))["status"] == "draft"


@pytest.mark.asyncio
async def test_app_migrations_coexist_with_harness_restart(tmp_path):
    from deerflow.config.database_config import DatabaseConfig
    from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config

    config = DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path))
    try:
        await init_engine_from_config(config)
        await upgrade_evaluation_schema(get_engine())
        repository = EvaluationRepository(get_session_factory())
        created = await repository.create_project("owner", "Synthetic coexistence")
        await close_engine()
        await init_engine_from_config(config)
        await upgrade_evaluation_schema(get_engine())
        assert (await EvaluationRepository(get_session_factory()).list_projects("owner"))[0]["id"] == created["id"]
        async with get_engine().connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar() == "eval_0001"
            assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar() != "eval_0001"
    finally:
        await close_engine()


@pytest.mark.asyncio
async def test_app_schema_matches_versioned_metadata(repo):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.evaluation.tables import metadata

    _, engine = repo
    async with engine.connect() as conn:

        def compare(connection):
            context = MigrationContext.configure(connection, opts={"version_table": "devpilot_alembic_version"})
            return compare_metadata(context, metadata)

        assert await conn.run_sync(compare) == []


def test_unicode_size_depth_unknown_fields_and_stable_hash():
    from app.evaluation.datasets import dataset_hash

    with pytest.raises(ValueError):
        samples("[" * 2000)
    with pytest.raises(ValueError):
        samples(content("\u4e2d" * 170_000))
    a = samples()
    b = parse_samples(DatasetImport(revision=4, format="jsonl", content=content()[1:-1]))
    assert dataset_hash(source().model_dump(), "baseline", a) == dataset_hash(source().model_dump(), "baseline", b)
    assert dataset_hash(source().model_dump(), "acceptance", a) != dataset_hash(source().model_dump(), "baseline", a)


@pytest.mark.asyncio
async def test_sql_echo_is_rejected_before_private_data_access(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'echo.db'}", echo=True)
    try:
        with pytest.raises(ValueError, match="echo_sql=false"):
            await upgrade_evaluation_schema(engine)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_schema_bootstrap_and_unknown_revision(repo):
    _, engine = repo
    await asyncio.gather(upgrade_evaluation_schema(engine), upgrade_evaluation_schema(engine))
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE devpilot_alembic_version SET version_num='future_schema'"))
    with pytest.raises(Exception):
        await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar() == "future_schema"


@pytest.mark.asyncio
async def test_migration_io_is_offloaded_and_schema_is_forwarded(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.evaluation import schema

    offload = AsyncMock()
    monkeypatch.setattr(schema.asyncio, "to_thread", offload)
    engine = SimpleNamespace(echo=False, dialect=SimpleNamespace(name="postgresql"), url="synthetic URL")
    await schema.upgrade_evaluation_schema(engine, postgres_schema="evaluation_fixture")
    offload.assert_awaited_once_with(schema._upgrade, engine.url, "evaluation_fixture")
