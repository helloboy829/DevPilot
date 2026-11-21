import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation.material_intake import MaterialBatchCreate
from app.evaluation.material_repository import MaterialIntakeRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.schema import upgrade_evaluation_schema


@pytest_asyncio.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'material-repository.db'}")
    await upgrade_evaluation_schema(engine)
    repository = MaterialIntakeRepository(async_sessionmaker(engine, expire_on_commit=False))
    yield repository
    await engine.dispose()


def manifest():
    return MaterialBatchCreate.model_validate(
        {
            "name": "Synthetic intake",
            "components": [{"component_id": "model-a", "name": "Model A", "kind": "llm", "purpose": "QA", "attachment_ids": ["att_local"]}],
            "attachments": [
                {
                    "attachment_id": "att_local",
                    "file_name": "cases.jsonl",
                    "authorization_basis": "user_provided",
                    "purpose": "evaluation_data",
                    "sensitivity": "internal",
                    "retention_until": "2030-01-01T00:00:00Z",
                }
            ],
        }
    )


@pytest.mark.asyncio
async def test_material_batch_freezes_component_denominator_and_returns_generated_artifact_id(repo):
    created = await repo.create("owner-a", manifest())
    assert created["component_count"] == 1
    assert created["components"][0]["status"] == "pending"
    artifact = created["artifacts"][0]
    assert artifact["id"] != "att_local"
    assert artifact["status"] == "pending_upload"
    assert "owner_id" not in created
    assert "storage_key" not in artifact
    assert created["components"][0]["artifact_ids"] == [artifact["id"]]


@pytest.mark.asyncio
async def test_material_batch_reads_are_owner_scoped(repo):
    created = await repo.create("owner-a", manifest())
    assert [row["id"] for row in await repo.list("owner-a")] == [created["id"]]
    assert await repo.list("owner-b") == []
    with pytest.raises(NotFound):
        await repo.get("owner-b", created["id"])


@pytest.mark.asyncio
async def test_material_batch_pagination_is_bounded(repo):
    first = await repo.create("owner-a", manifest())
    second = await repo.create("owner-a", manifest())
    first_page = await repo.list("owner-a", limit=1, offset=0)
    second_page = await repo.list("owner-a", limit=1, offset=1)
    assert len(first_page) == 1
    assert len(second_page) == 1
    assert len(await repo.list("owner-a", limit=1, offset=2)) == 0
    assert {first_page[0]["id"], second_page[0]["id"]} == {first["id"], second["id"]}


@pytest.mark.asyncio
async def test_material_upload_is_owner_scoped_and_idempotent(repo):
    created = await repo.create("owner-a", manifest())
    artifact_id = created["artifacts"][0]["id"]
    digest = "a" * 64

    await repo.record_upload("owner-a", created["id"], artifact_id, sha256=digest, size_bytes=12)
    await repo.record_upload("owner-a", created["id"], artifact_id, sha256=digest, size_bytes=12)
    stored = await repo.get("owner-a", created["id"])

    assert stored["artifacts"][0]["status"] == "uploaded"
    assert stored["artifacts"][0]["sha256"] == digest
    assert stored["artifacts"][0]["size_bytes"] == 12
    assert "storage_key" not in stored["artifacts"][0]
    with pytest.raises(NotFound):
        await repo.record_upload("owner-b", created["id"], artifact_id, sha256=digest, size_bytes=12)


@pytest.mark.asyncio
async def test_material_upload_cannot_rebind_an_artifact_to_different_content(repo):
    created = await repo.create("owner-a", manifest())
    artifact_id = created["artifacts"][0]["id"]
    await repo.record_upload("owner-a", created["id"], artifact_id, sha256="a" * 64, size_bytes=12)

    with pytest.raises(Conflict):
        await repo.record_upload("owner-a", created["id"], artifact_id, sha256="b" * 64, size_bytes=13)
