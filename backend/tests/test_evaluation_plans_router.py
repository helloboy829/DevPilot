"""Authenticated frozen-plan API, all data synthetic and no outbound calls."""

import pytest
from cryptography.fernet import Fernet
from test_evaluation_plans import draft, limits
from test_evaluation_registry_router import api as api
from test_evaluation_registry_router import setup_binding

from app.gateway.authz import Permissions


async def setup_plan(api, monkeypatch):
    client, _, base, dataset = api
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    component, _ = await setup_binding(client, base, dataset)
    response = await client.post(
        base + "/components/" + component["id"] + "/request-versions",
        json={"version_label": "Synthetic request", "confirmed": True, "request": {"url": "https://example.test/SYNTHETIC_PATH", "method": "POST", "headers": [["Authorization", "Bearer SYNTHETIC_SECRET"]], "body": '{"q":"placeholder"}'}},
    )
    assert response.status_code == 200
    return base + "/components/" + component["id"] + "/plans", draft(response.json(), dataset, limits=limits(request_count=1, concurrency=1))


@pytest.mark.asyncio
async def test_plan_create_read_metadata_permissions_and_no_execution_api(api, monkeypatch):
    client, app, base, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    response = await client.post(path, json=payload)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["scope"] == "frozen_definition_only"
    assert "SYNTHETIC" not in response.text and "encrypted_payload" not in response.text
    stored = base + "/plans/" + response.json()["id"]
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(stored)).json() == response.json()
    assert (await client.get(path)).json()["plans"] == [response.json()]
    assert [e["action"] for e in (await client.get(stored + "/audit")).json()["events"]] == ["plan_frozen"]
    for method, suffix in (("patch", ""), ("delete", ""), ("post", "/execute"), ("post", "/open")):
        assert (await getattr(client, method)(stored + suffix)).status_code in {404, 405}
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(stored)).status_code == 200
    assert (await client.get(stored + "/audit")).status_code == 403
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.actor = 2
    for target in (stored, path):
        assert (await client.get(target)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_plan_creation_requires_human_confirmation_and_key(api, monkeypatch):
    client, app, _, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    app.state.internal = True
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.internal = False
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_WRITE]
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    failed = await client.post(path, json=payload)
    assert failed.status_code == 503 and "SYNTHETIC" not in failed.text
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert (await client.post(path, json=payload)).status_code == 503
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_READ)
    assert (await client.get(path)).json()["plans"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,status",
    [
        ({"confirmed": 1}, 422),
        ({"confirmed": False}, 422),
        ({"dataset_revision": 999}, 409),
        ({"binding": {"schema": "qa-json-binding.v1", "input_pointer": "/SYNTHETIC_MISSING", "output_pointer": "/a"}}, 422),
        ({"binding": {"schema": "qa-json-binding.v1", "input_pointer": "/q", "output_pointer": "/a", "expected": "SYNTHETIC_GOLD"}}, 422),
        ({"limits": limits(request_count=1, max_total_body_bytes=1)}, 422),
        ({"response_mode": "SYNTHETIC_UNSUPPORTED"}, 422),
    ],
)
async def test_plan_errors_are_private_and_do_not_create_partial_plans(api, monkeypatch, change, status):
    client, _, _, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    response = await client.post(path, json={**payload, **change})
    assert response.status_code == status
    assert "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert (await client.get(path)).json()["plans"] == []
