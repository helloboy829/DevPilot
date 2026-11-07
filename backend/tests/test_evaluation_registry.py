"""Synthetic contract tests for project/component submission bindings."""

import json

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation import tables as t
from app.evaluation.datasets import DatasetImport, SourceDeclaration, parse_samples
from app.evaluation.registry import ComponentLinkCreate, SubmissionCreate
from app.evaluation.registry_repository import RegistryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.schema import upgrade_evaluation_schema
from deerflow.persistence.component_tests.model import ComponentRow


@pytest_asyncio.fixture
async def registry(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: ComponentRow.__table__.create(conn))
    await upgrade_evaluation_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf.begin() as session:
        session.add(
            ComponentRow(
                id="c1",
                user_id="owner",
                name="Synthetic component",
                transport="http_post",
                api_url="https://example.invalid/private?token=SYNTHETIC_URL_SECRET",
                api_token="SYNTHETIC_TOKEN_SECRET",
                response_mode="blocking",
                supports_streaming=False,
                validation_type="reference_text",
                acceptance_criteria={"private": "SYNTHETIC_RULE_SECRET"},
            )
        )
        session.add(ComponentRow(id="other", user_id="other", name="Other private component", transport="http_post", api_url="https://example.invalid", validation_type="manual_review"))
    repository = RegistryRepository(sf)
    project = await repository.create_project("owner", "Synthetic project")
    source = SourceDeclaration(label="Fixture", reference="fixture:qa", authorization_basis="Synthetic owned data", attested=True)
    dataset = await repository.create_dataset("owner", project["id"], "QA", "baseline", source)
    rows = parse_samples(DatasetImport(revision=1, format="json", content=json.dumps([{"sample_id": "q1", "input": "Synthetic Q", "expected": "SYNTHETIC_GOLD_SECRET", "source_ref": "record:1"}])))
    dataset = await repository.replace_samples("owner", project["id"], dataset["id"], 1, rows)
    dataset = await repository.freeze("owner", project["id"], dataset["id"], 2, dataset["content_hash"])
    yield repository, engine, project, dataset
    await engine.dispose()


async def link_and_payload(repository, project, dataset):
    link = await repository.link_component("owner", project["id"], ComponentLinkCreate(source_component_id="c1", kind="llm"))
    candidates = await repository.component_candidates("owner", project["id"])
    payload = SubmissionCreate(version_label="v1", dataset_id=dataset["id"], dataset_revision=dataset["revision"], dataset_hash=dataset["content_hash"], component_fingerprint=candidates[0]["component_fingerprint"], confirmed=True)
    return link, payload


@pytest.mark.asyncio
async def test_candidates_only_select_safe_owner_fields(registry):
    repository, _, project, _ = registry
    rows = await repository.component_candidates("owner", project["id"])
    assert len(rows) == 1 and rows[0]["source_component_id"] == "c1"
    serialized = json.dumps(rows)
    assert all(secret not in serialized for secret in ("SYNTHETIC_URL_SECRET", "SYNTHETIC_TOKEN_SECRET", "SYNTHETIC_RULE_SECRET"))
    assert "api_url" not in serialized and "api_token" not in serialized
    with pytest.raises(NotFound):
        await repository.component_candidates("other", project["id"])


@pytest.mark.asyncio
async def test_submission_is_server_snapshot_and_remains_after_source_edit(registry):
    repository, engine, project, dataset = registry
    link, payload = await link_and_payload(repository, project, dataset)
    result = await repository.create_submission("owner", project["id"], link["id"], payload)
    assert result["dataset_hash"] == dataset["content_hash"]
    assert result["component_snapshot"]["name"] == "Synthetic component"
    assert result["component_snapshot"]["kind"] == "llm"
    assert result["component_snapshot"]["supports_streaming"] is False
    assert result["dataset_purpose"] == "baseline"
    assert len(result["submission_hash"]) == 64
    async with engine.begin() as conn:
        await conn.execute(update(ComponentRow).where(ComponentRow.id == "c1").values(name="New live name", api_token="NEW_SYNTHETIC_SECRET"))
    stored = await repository.get_submission("owner", project["id"], result["id"])
    assert stored == result
    serialized = json.dumps(stored)
    assert "SECRET" not in serialized and "api_url" not in serialized
    audit = await repository.registry_audit("owner", project["id"])
    assert [row["action"] for row in audit] == ["component_linked", "submission_created"]
    assert "component_snapshot" not in json.dumps(audit)


@pytest.mark.asyncio
async def test_conflicts_and_owner_project_checks(registry):
    repository, _, project, dataset = registry
    link, payload = await link_and_payload(repository, project, dataset)
    with pytest.raises(Conflict):
        await repository.link_component("owner", project["id"], ComponentLinkCreate(source_component_id="c1", kind="llm"))
    with pytest.raises(NotFound):
        await repository.link_component("owner", project["id"], ComponentLinkCreate(source_component_id="other", kind="agent"))
    other_project = await repository.create_project("owner", "Second synthetic project")
    for operation in (
        repository.list_project_components("other", project["id"]),
        repository.create_submission("other", project["id"], link["id"], payload),
        repository.create_submission("owner", other_project["id"], link["id"], payload),
        repository.registry_audit("other", project["id"]),
    ):
        with pytest.raises(NotFound):
            await operation
    result = await repository.create_submission("owner", project["id"], link["id"], payload)
    with pytest.raises(NotFound):
        await repository.get_submission("other", project["id"], result["id"])
    with pytest.raises(NotFound):
        await repository.get_submission("owner", other_project["id"], result["id"])
    with pytest.raises(Conflict):
        await repository.create_submission("owner", project["id"], link["id"], payload.model_copy(update={"version_label": "V1"}))
    assert len(await repository.list_submissions("owner", project["id"], link["id"])) == 1
    assert len(await repository.registry_audit("owner", project["id"])) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["draft", "revision", "hash", "component", "gold", "project"])
async def test_submission_refuses_unfrozen_stale_or_tampered_bindings(registry, change):
    repository, engine, project, dataset = registry
    link, payload = await link_and_payload(repository, project, dataset)
    async with engine.begin() as conn:
        if change == "draft":
            await conn.execute(update(t.datasets).where(t.datasets.c.id == dataset["id"]).values(status="draft"))
        elif change == "revision":
            payload = payload.model_copy(update={"dataset_revision": 1})
        elif change == "hash":
            payload = payload.model_copy(update={"dataset_hash": "0" * 64})
        elif change == "component":
            await conn.execute(update(ComponentRow).where(ComponentRow.id == "c1").values(supports_streaming=True))
        elif change == "gold":
            await conn.execute(update(t.references).where(t.references.c.dataset_id == dataset["id"]).values(expected="Tampered synthetic gold"))
        else:
            other = await repository.create_project("owner", "Other project")
            other_ds = await repository.create_dataset("owner", other["id"], "Other QA", "baseline", SourceDeclaration(label="Fixture", reference="fixture:2", authorization_basis="Owned", attested=True))
            payload = payload.model_copy(update={"dataset_id": other_ds["id"]})
    with pytest.raises((Conflict, NotFound)):
        await repository.create_submission("owner", project["id"], link["id"], payload)
    assert await repository.list_submissions("owner", project["id"], link["id"]) == []
    assert len(await repository.registry_audit("owner", project["id"])) == 1


@pytest.mark.asyncio
async def test_registry_upgrade_preserves_qa_and_harness_ledger(registry):
    repository, engine, project, dataset = registry
    await upgrade_evaluation_schema(engine)
    assert (await repository.get_dataset("owner", project["id"], dataset["id"]))["status"] == "frozen"
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar() == "eval_0003"
        assert "alembic_version" not in await conn.run_sync(lambda c: inspect(c).get_table_names())


def test_submission_contract_is_strict_and_no_client_snapshot():
    from pydantic import ValidationError

    base = dict(version_label="v1", dataset_id="d1", dataset_revision=3, dataset_hash="a" * 64, component_fingerprint="b" * 64, confirmed=True)
    for change in ({"confirmed": 1}, {"confirmed": "true"}, {"component_snapshot": {}}, {"dataset_revision": True}, {"version_label": " "}):
        with pytest.raises(ValidationError):
            SubmissionCreate(**{**base, **change})


@pytest.mark.asyncio
async def test_upgrade_from_deployed_eval_0001_retains_frozen_data(tmp_path, monkeypatch):
    from app.evaluation import schema

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'old.db'}")
    original = schema.command.upgrade
    monkeypatch.setattr(schema.command, "upgrade", lambda config, _revision: original(config, "eval_0001"))
    try:
        await upgrade_evaluation_schema(engine)
        repository = RegistryRepository(async_sessionmaker(engine, expire_on_commit=False))
        project = await repository.create_project("owner", "Pre-upgrade synthetic")
        dataset = await repository.create_dataset("owner", project["id"], "Old QA", "baseline", SourceDeclaration(label="Fixture", reference="fixture:old", authorization_basis="Owned", attested=True))
        rows = parse_samples(DatasetImport(revision=1, format="jsonl", content='{"sample_id":"q1","input":"Synthetic Q","expected":"Synthetic A","source_ref":"record:1"}'))
        dataset = await repository.replace_samples("owner", project["id"], dataset["id"], 1, rows)
        dataset = await repository.freeze("owner", project["id"], dataset["id"], 2, dataset["content_hash"])
        monkeypatch.setattr(schema.command, "upgrade", original)
        await upgrade_evaluation_schema(engine)
        assert await repository.get_dataset("owner", project["id"], dataset["id"]) == dataset
        assert (await repository.read_samples("owner", project["id"], dataset["id"], references=True))[0]["expected"] == "Synthetic A"
        assert await repository.list_project_components("owner", project["id"]) == []
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar() == "eval_0003"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_duplicate_submission_has_one_atomic_winner(registry):
    import asyncio

    repository, _, project, dataset = registry
    linked, payload = await link_and_payload(repository, project, dataset)
    result = await asyncio.gather(*[repository.create_submission("owner", project["id"], linked["id"], payload) for _ in range(2)], return_exceptions=True)
    assert sum(isinstance(row, dict) for row in result) == 1
    assert sum(isinstance(row, Conflict) for row in result) == 1
    assert len(await repository.registry_audit("owner", project["id"])) == 2


@pytest.mark.asyncio
async def test_database_rejects_cross_project_submission_binding(registry):
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    repository, engine, project, dataset = registry
    linked, payload = await link_and_payload(repository, project, dataset)
    result = await repository.create_submission("owner", project["id"], linked["id"], payload)
    other = await repository.create_project("owner", "Other synthetic project")
    async with engine.connect() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.commit()
        values = {**result, "id": "forged", "label_key": "forged", "version_label": "forged", "project_id": other["id"]}
        with pytest.raises(IntegrityError):
            await conn.execute(insert(t.submissions).values(**values))
        await conn.rollback()


def test_normalized_label_key_must_fit_database_column():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SubmissionCreate(version_label="\ufdfa" * 80, dataset_id="d1", dataset_revision=3, dataset_hash="a" * 64, component_fingerprint="b" * 64, confirmed=True)
