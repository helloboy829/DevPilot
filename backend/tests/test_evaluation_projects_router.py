from __future__ import annotations

import json
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation.repository import EvaluationRepository
from app.evaluation.schema import upgrade_evaluation_schema
from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_INTERNAL
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import evaluation_projects


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'routes.db'}")
    await upgrade_evaluation_schema(engine)
    app = FastAPI()
    app.state.evaluation_repo = EvaluationRepository(async_sessionmaker(engine, expire_on_commit=False))
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
async def test_auth_and_permissions_are_separate_from_chat(api):
    client, app = api
    app.state.actor = 0
    response = await client.get("/api/evaluation/projects")
    assert response.status_code == 401
    assert "no-store" in response.headers["cache-control"]
    app.state.actor = 1
    app.state.permissions = [Permissions.THREADS_READ, Permissions.THREADS_WRITE]
    assert (await client.get("/api/evaluation/projects")).status_code == 403


@pytest.mark.asyncio
async def test_api_workflow_reference_gate_and_freeze(api):
    client, app = api
    path, dataset = await setup_data(client)
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    response = await client.get(path + "/samples")
    assert response.status_code == 200
    assert "SECRET_SYNTHETIC_GOLD" not in response.text
    assert (await client.get(path + "/references")).status_code == 403
    assert (await client.get(path + "/audit")).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
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
