from __future__ import annotations

import json
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncByteStream, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation import tables as evaluation_tables
from app.evaluation.material_artifact_store import MaterialArtifactStore
from app.evaluation.material_repository import MaterialIntakeRepository
from app.evaluation.repository import EvaluationRepository
from app.evaluation.schema import upgrade_evaluation_schema
from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import evaluation_materials, evaluation_projects


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}")
    await upgrade_evaluation_schema(engine)
    app = FastAPI()
    sf = async_sessionmaker(engine, expire_on_commit=False)
    app.state.evaluation_repo = EvaluationRepository(sf)
    app.state.evaluation_material_repo = MaterialIntakeRepository(sf)
    app.state.evaluation_material_store = MaterialArtifactStore(tmp_path / "material-artifacts", max_file_size_bytes=16)
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW]
    app.state.actor = 1
    app.state.internal = False

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if app.state.actor:
            user = User(id=UUID(int=app.state.actor), email="synthetic@example.com", password_hash="x", system_role="user")
            request.state.user = user
            request.state.auth_source = AUTH_SOURCE_INTERNAL if app.state.internal else AUTH_SOURCE_AUTH_DISABLED
            request.state.auth = AuthContext(user=user, permissions=app.state.permissions)
        return await call_next(request)

    app.include_router(evaluation_projects.router)
    app.include_router(evaluation_materials.router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
        yield client, app
    await engine.dispose()


async def setup_data(client):
    project = (await client.post("/api/evaluation/projects", json={"name": "Synthetic project"})).json()
    base = f"/api/evaluation/projects/{project['id']}/datasets"
    dataset = (await client.post(base, json={"name": "Synthetic QA", "purpose": "baseline", "source": {"label": "Fixture", "reference": "fixture:1", "authorization_basis": "Synthetic owned data", "attested": True}})).json()
    path = base + "/" + dataset["id"]
    result = await client.put(path + "/samples", json={"revision": 1, "format": "json", "content": json.dumps([{"sample_id": "q1", "input": "Synthetic Q", "expected": "SECRET_SYNTHETIC_GOLD", "source_ref": "record:1"}])})
    assert result.status_code == 200
    return path, result.json()


@pytest.mark.asyncio
async def test_every_authenticated_member_can_access_evaluation_without_role_grants(api):
    client, app = api
    app.state.actor = 0
    response = await client.get("/api/evaluation/projects")
    assert response.status_code == 401
    assert "no-store" in response.headers["cache-control"]
    app.state.actor = 1
    app.state.permissions = [Permissions.THREADS_READ, Permissions.THREADS_WRITE]
    assert (await client.get("/api/evaluation/projects")).status_code == 200


@pytest.mark.asyncio
async def test_api_workflow_reference_gate_and_freeze(api):
    client, app = api
    path, dataset = await setup_data(client)
    app.state.permissions = []
    response = await client.get(path + "/samples")
    assert response.status_code == 200
    assert "SECRET_SYNTHETIC_GOLD" not in response.text
    assert (await client.get(path + "/audit")).status_code == 200
    assert "SECRET_SYNTHETIC_GOLD" in (await client.get(path + "/references")).text
    freeze = {"revision": dataset["revision"], "content_hash": dataset["content_hash"], "reviewed": True}
    response = await client.post(path + "/freeze", json=freeze)
    assert response.status_code == 200
    assert response.json()["status"] == "frozen"
    assert "no-store" in response.headers["cache-control"]
    assert (await client.post(path + "/freeze", json=freeze)).status_code == 409
    assert "SECRET_SYNTHETIC_GOLD" not in (await client.get(path + "/audit")).text
    app.state.actor = 2
    for suffix in ("", "/samples", "/references", "/audit"):
        assert (await client.get(path + suffix)).status_code == 404
    assert (await client.post(path + "/freeze", json=freeze)).status_code == 404


@pytest.mark.asyncio
async def test_internal_agent_cannot_attest_review(api):
    client, app = api
    path, dataset = await setup_data(client)
    app.state.internal = True
    response = await client.post(path + "/freeze", json={"revision": 2, "content_hash": dataset["content_hash"], "reviewed": True})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_validation_does_not_echo_gold_and_no_memory_fallback(api):
    client, app = api
    path, _ = await setup_data(client)
    for body in ({"revision": 2, "format": "json", "content": "SECRET_SYNTHETIC_GOLD"}, {"revision": "SECRET_SYNTHETIC_GOLD", "format": "json", "content": "[]"}):
        response = await client.put(path + "/samples", json=body)
        assert response.status_code == 422
        assert "SECRET_SYNTHETIC_GOLD" not in response.text
        assert "no-store" in response.headers["cache-control"]
    app.state.evaluation_repo = None
    assert (await client.get("/api/evaluation/projects")).status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", [False, 1, 1.0, "true", None])
async def test_authorization_declaration_and_review_consent_required(api, confirmation):
    client, _ = api
    path, dataset = await setup_data(client)
    response = await client.post(path + "/freeze", json={"revision": 2, "content_hash": dataset["content_hash"], "reviewed": confirmation})
    assert response.status_code == 422
    response = await client.post(path.rsplit("/", 1)[0], json={"name": "QA", "purpose": "acceptance", "source": {"label": "s", "reference": "r", "authorization_basis": "b", "attested": confirmation}})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_raw_request_size_is_bounded_before_json_parse(api):
    client, _ = api
    response = await client.post("/api/evaluation/projects", content=b"x" * 3_100_001, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_internal_agents_cannot_read_gold(api):
    client, app = api
    path, _ = await setup_data(client)
    app.state.internal = True
    assert (await client.get(path + "/references")).status_code == 403
    response = await client.get(path + "/samples")
    assert response.status_code == 200
    assert "SECRET_SYNTHETIC_GOLD" not in response.text


def material_payload(name="Synthetic intake"):
    return {
        "name": name,
        "components": [{"component_id": "model-a", "name": "Model A", "kind": "llm", "purpose": "QA", "attachment_ids": ["att_local"]}],
        "attachments": [
            {
                "attachment_id": "att_local",
                "file_name": "cases.jsonl",
                "authorization_basis": "user_provided",
                "purpose": "evaluation_data",
                "sensitivity": "internal",
                "retention_until": "2099-01-01T00:00:00Z",
            }
        ],
    }


@pytest.mark.asyncio
async def test_material_batch_api_is_private_owner_scoped_and_hides_storage_metadata(api):
    client, app = api
    created_response = await client.post("/api/evaluation/material-batches", json=material_payload())
    assert created_response.status_code == 200
    created = created_response.json()
    assert created["component_count"] == 1
    assert created["components"][0]["status"] == "pending"
    assert "owner_id" not in created
    assert "storage_key" not in created["artifacts"][0]
    assert "no-store" in created_response.headers["cache-control"]

    listed = await client.get("/api/evaluation/material-batches?limit=1&offset=0")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["batches"]] == [created["id"]]
    assert "owner_id" not in listed.text
    detail = await client.get(f"/api/evaluation/material-batches/{created['id']}")
    assert detail.json() == created

    app.state.actor = 2
    assert (await client.get(f"/api/evaluation/material-batches/{created['id']}")).status_code == 404
    assert (await client.get("/api/evaluation/material-batches")).json() == {"batches": []}


@pytest.mark.asyncio
async def test_material_batch_api_requires_human_authentication(api):
    client, app = api
    app.state.actor = 0
    assert (await client.get("/api/evaluation/material-batches")).status_code == 401
    app.state.actor = 1
    app.state.internal = True
    response = await client.post("/api/evaluation/material-batches", json=material_payload())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_material_upload_is_private_idempotent_and_keeps_storage_key_hidden(api):
    client, app = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"

    first = await client.post(path, files={"file": ("cases.jsonl", b"synthetic data", "application/octet-stream")})
    second = await client.post(path, files={"file": ("cases.jsonl", b"synthetic data", "application/octet-stream")})
    assert first.status_code == second.status_code == 200
    assert first.json()["artifacts"][0]["status"] == "uploaded"
    assert "storage_key" not in first.text
    assert next(app.state.evaluation_material_store.root.rglob("*.bin")).read_bytes() == b"synthetic data"

    app.state.actor = 2
    assert (await client.post(path, files={"file": ("cases.jsonl", b"synthetic data")})).status_code == 404
    app.state.actor = 1
    app.state.internal = True
    assert (await client.post(path, files={"file": ("cases.jsonl", b"synthetic data")})).status_code == 403


@pytest.mark.asyncio
async def test_material_upload_rejects_conflicts_oversize_and_missing_storage(api):
    client, app = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"
    assert (await client.post(path, files={"file": ("cases.jsonl", b"0123456789abcdefg")})).status_code == 413

    success = await client.post(path, files={"file": ("cases.jsonl", b"one")})
    assert success.status_code == 200
    assert (await client.post(path, files={"file": ("cases.jsonl", b"two")})).status_code == 409

    app.state.evaluation_material_store = None
    other = (await client.post("/api/evaluation/material-batches", json=material_payload("No store"))).json()
    other_path = f"/api/evaluation/material-batches/{other['id']}/attachments/{other['artifacts'][0]['id']}"
    assert (await client.post(other_path, files={"file": ("cases.jsonl", b"data")})).status_code == 503


@pytest.mark.asyncio
async def test_material_upload_stops_oversized_stream_before_consuming_the_multipart_body(api):
    client, _ = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"
    boundary = "synthetic-boundary"
    prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="cases.jsonl"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
    body = prefix + (b"x" * (128 * 1024)) + f"\r\n--{boundary}--\r\n".encode()

    class ChunkedBody(AsyncByteStream):
        def __init__(self):
            self.yielded = 0

        async def __aiter__(self):
            for start in range(0, len(body), 4096):
                chunk = body[start : start + 4096]
                self.yielded += len(chunk)
                yield chunk

        async def aclose(self):
            return None

    stream = ChunkedBody()
    response = await client.post(
        path,
        content=stream,
        headers={
            "content-type": f"multipart/form-data; boundary={boundary}",
            "content-length": "1",
        },
    )

    assert response.status_code == 413
    assert stream.yielded < len(body)


@pytest.mark.asyncio
async def test_material_preview_requires_explicit_consent_and_returns_ephemeral_content(api):
    client, app = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    upload_path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"
    assert (await client.post(upload_path, files={"file": ("cases.jsonl", b'{"x":1}\n')})).status_code == 200

    preview_path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}/preview"
    operation_id = "9ba2289e-7545-4ab9-bdaa-efdfdf3c6350"
    denied = await client.post(preview_path, json={"operation_id": operation_id, "open_content": False})
    assert denied.status_code == 422
    assert '"x"' not in denied.text

    response = await client.post(preview_path, json={"operation_id": operation_id, "open_content": True})
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["parse_status"] == "parsed"
    assert response.json()["blocks"] == [{"text": '{"x":1}', "source_location": {"line": 1}}]
    assert response.json()["result_hash"]
    assert "owner_id" not in response.text
    assert "storage_key" not in response.text

    owner = str(UUID(int=1))
    artifact = (await app.state.evaluation_material_repo.get(owner, created["id"]))["artifacts"][0]
    assert artifact["parse_status"] == "parsed"
    receipt = await client.get(f"/api/evaluation/material-batches/previews/{operation_id}")
    assert receipt.status_code == 200
    assert '"x"' not in receipt.text
    assert receipt.json()["parse_status"] == "parsed"
    app.state.actor = 2
    assert (await client.get(f"/api/evaluation/material-batches/previews/{operation_id}")).status_code == 404
    app.state.actor = 1
    assert (await client.post(preview_path, json={"operation_id": operation_id, "open_content": True})).status_code == 409


@pytest.mark.asyncio
async def test_material_preview_is_owner_scoped_and_rejects_internal_or_expired_access(api):
    client, app = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    upload_path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"
    assert (await client.post(upload_path, files={"file": ("cases.jsonl", b'{"x":1}\n')})).status_code == 200
    path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}/preview"
    payload = {"operation_id": "4b412e19-1c2f-45ec-a127-c5ce27a5058a", "open_content": True}

    app.state.actor = 2
    assert (await client.post(path, json=payload)).status_code == 404
    app.state.actor = 1
    app.state.internal = True
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.internal = False
    async with app.state.evaluation_material_repo.sf.begin() as session:
        await session.execute(update(evaluation_tables.material_artifacts).where(evaluation_tables.material_artifacts.c.id == artifact_id).values(retention_until="2000-01-01T00:00:00+00:00"))
    response = await client.post(path, json=payload)
    assert response.status_code == 410
    assert '"x"' not in response.text


@pytest.mark.asyncio
async def test_material_upload_rejects_expired_retention(api):
    client, app = api
    created = (await client.post("/api/evaluation/material-batches", json=material_payload())).json()
    artifact_id = created["artifacts"][0]["id"]
    async with app.state.evaluation_material_repo.sf.begin() as session:
        await session.execute(update(evaluation_tables.material_artifacts).where(evaluation_tables.material_artifacts.c.id == artifact_id).values(retention_until="2000-01-01T00:00:00+00:00"))
    path = f"/api/evaluation/material-batches/{created['id']}/attachments/{artifact_id}"
    assert (await client.post(path, files={"file": ("cases.jsonl", b"data")})).status_code == 410
    assert not list(app.state.evaluation_material_store.root.rglob("*.bin"))


@pytest.mark.asyncio
async def test_database_errors_do_not_echo_submitted_values(api, monkeypatch, caplog):
    from sqlalchemy.exc import SQLAlchemyError

    client, app = api

    async def fail(*_args):
        raise SQLAlchemyError("SECRET_SYNTHETIC_GOLD")

    monkeypatch.setattr(app.state.evaluation_repo, "create_project", fail)
    response = await client.post("/api/evaluation/projects", json={"name": "Synthetic"})
    assert response.status_code == 503
    assert "SECRET_SYNTHETIC_GOLD" not in response.text
    assert "SECRET_SYNTHETIC_GOLD" not in caplog.text
    assert "no-store" in response.headers["cache-control"]
