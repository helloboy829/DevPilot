"""Private registry API boundaries using synthetic records only."""

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
from deerflow.persistence.component_tests.model import ComponentRow


@pytest_asyncio.fixture
async def api(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api-registry.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: ComponentRow.__table__.create(c))
    await upgrade_evaluation_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf.begin() as session:
        session.add(
            ComponentRow(
                id="c1",
                user_id=str(UUID(int=1)),
                name="Synthetic component",
                transport="http_post",
                api_url="https://example.invalid?secret=SYNTHETIC_URL",
                api_token="SYNTHETIC_TOKEN",
                response_mode="blocking",
                validation_type="manual_review",
            )
        )
    app = FastAPI()
    app.state.evaluation_repo = EvaluationRepository(sf)
    app.state.actor = 1
    app.state.internal = False
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW]

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if app.state.actor:
            user = User(id=UUID(int=app.state.actor), email="fixture@example.com", password_hash="x", system_role="user")
            request.state.user = user
            request.state.auth_source = AUTH_SOURCE_INTERNAL if app.state.internal else AUTH_SOURCE_AUTH_DISABLED
            request.state.auth = AuthContext(user=user, permissions=app.state.permissions)
        return await call_next(request)

    app.include_router(evaluation_projects.router)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://fixture") as client:
        project = (await client.post("/api/evaluation/projects", json={"name": "Synthetic project"})).json()
        base = "/api/evaluation/projects/" + project["id"]
        ds = (await client.post(base + "/datasets", json={"name": "QA", "purpose": "baseline", "source": {"label": "Fixture", "reference": "fixture:qa", "authorization_basis": "Owned synthetic", "attested": True}})).json()
        ds_path = base + "/datasets/" + ds["id"]
        imported = await client.put(ds_path + "/samples", json={"revision": 1, "format": "jsonl", "content": '{"sample_id":"q1","input":"Synthetic Q","expected":"SYNTHETIC_GOLD","source_ref":"record:1"}'})
        dataset = imported.json()
        dataset = (await client.post(ds_path + "/freeze", json={"revision": 2, "content_hash": dataset["content_hash"], "reviewed": True})).json()
        yield client, app, base, dataset
    await engine.dispose()


async def setup_binding(client, base, dataset):
    candidate = (await client.get(base + "/component-candidates")).json()["components"][0]
    response = await client.post(base + "/components", json={"source_component_id": "c1", "kind": "agent"})
    assert response.status_code == 200
    component = response.json()
    payload = {"version_label": "v1", "dataset_id": dataset["id"], "dataset_revision": dataset["revision"], "dataset_hash": dataset["content_hash"], "component_fingerprint": candidate["component_fingerprint"], "confirmed": True}
    return component, payload


@pytest.mark.asyncio
async def test_registry_api_scope_permissions_internal_and_immutability(api):
    client, app, base, dataset = api
    component, payload = await setup_binding(client, base, dataset)
    path = base + "/components/" + component["id"] + "/submissions"
    app.state.internal = True
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.internal = False
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_WRITE]
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW]
    result = await client.post(path, json=payload)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    assert "SYNTHETIC_GOLD" not in result.text and "api_token" not in result.text and "SYNTHETIC_URL" not in result.text
    stored_path = base + "/submissions/" + result.json()["id"]
    assert (await client.patch(stored_path, json={"version_label": "rewrite"})).status_code == 405
    assert (await client.delete(stored_path)).status_code == 405
    assert (await client.post(path, json=payload)).status_code == 409
    app.state.actor = 2
    for route in (base + "/components", base + "/component-candidates", path, stored_path, base + "/registry-audit"):
        assert (await client.get(route)).status_code == 404
    app.state.actor = 0
    assert (await client.get(base + "/components")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"confirmed": 1}, {"confirmed": False}, {"component_snapshot": {"token": "SYNTHETIC_HIDDEN"}}, {"dataset_hash": "SYNTHETIC_HIDDEN"}])
async def test_client_cannot_forge_snapshot_or_confirmation(api, change):
    client, _, base, dataset = api
    component, payload = await setup_binding(client, base, dataset)
    response = await client.post(base + "/components/" + component["id"] + "/submissions", json={**payload, **change})
    assert response.status_code == 422
    assert "SYNTHETIC_HIDDEN" not in response.text
    assert "no-store" in response.headers["cache-control"]
