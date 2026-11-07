"""Authenticated request vault routes. All targets, tokens and accounts synthetic."""

import pytest
from cryptography.fernet import Fernet
from test_evaluation_registry_router import api as api
from test_evaluation_registry_router import setup_binding

from app.gateway.authz import Permissions


def request_payload():
    return {"version_label": "v1", "confirmed": True, "request": {"url": "https://example.test/SYNTHETIC_PATH?token=SYNTHETIC_QUERY", "method": "POST", "headers": [["Authorization", "Bearer SYNTHETIC_TOKEN"]], "body": "SYNTHETIC_BODY"}}


@pytest.mark.asyncio
async def test_save_list_metadata_no_plaintext_read_or_mutation_endpoint(api, monkeypatch):
    client, app, base, dataset = api
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    component, _ = await setup_binding(client, base, dataset)
    path = base + "/components/" + component["id"] + "/request-versions"
    response = await client.post(path, json=request_payload())
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert "SYNTHETIC" not in response.text and "encrypted_payload" not in response.text
    assert response.json()["scope"] == "request_definition_only"
    stored_path = base + "/request-versions/" + response.json()["id"]
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(stored_path)).json() == response.json()
    assert (await client.get(path)).json()["request_versions"] == [response.json()]
    events = (await client.get(stored_path + "/audit")).json()["events"]
    assert len(events) == 1 and events[0]["action"] == "request_version_created"
    for method, suffix in (("patch", ""), ("delete", ""), ("post", "/open"), ("post", "/execute")):
        result = await getattr(client, method)(stored_path + suffix)
        assert result.status_code in {404, 405}
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(stored_path)).status_code == 200
    assert (await client.get(stored_path + "/audit")).status_code == 403
    assert (await client.post(path, json=request_payload())).status_code == 403
    app.state.actor = 2
    assert (await client.get(stored_path)).status_code == 404
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_save_requires_human_confirmation_permissions_and_operator_key(api, monkeypatch):
    client, app, base, dataset = api
    component, _ = await setup_binding(client, base, dataset)
    path = base + "/components/" + component["id"] + "/request-versions"
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)
    missing = await client.post(path, json=request_payload())
    assert missing.status_code == 503 and "no-store" in missing.headers["cache-control"]
    assert (await client.get(path)).json()["request_versions"] == []
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", "SYNTHETIC_BAD_KEY")
    invalid = await client.post(path, json=request_payload())
    assert invalid.status_code == 503 and "SYNTHETIC" not in invalid.text
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    app.state.internal = True
    assert (await client.post(path, json=request_payload())).status_code == 403
    app.state.internal = False
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_WRITE]
    assert (await client.post(path, json=request_payload())).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
    assert (await client.post(path, json=request_payload())).status_code == 200
    assert (await client.post(path, json=request_payload())).status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": 1},
        {"confirmed": False},
        {"request": {"url": "file:///SYNTHETIC_SECRET"}},
        {"request": {"url": "https://example.test", "body": "SYNTHETIC_SECRET", "headers": [["Host", "SYNTHETIC_SECRET"]]}},
        {"protected_hash": "SYNTHETIC_SECRET"},
    ],
)
async def test_invalid_request_values_not_echoed(api, change):
    client, _, base, dataset = api
    component, _ = await setup_binding(client, base, dataset)
    response = await client.post(base + "/components/" + component["id"] + "/request-versions", json={**request_payload(), **change})
    assert response.status_code == 422
    assert "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.asyncio
async def test_size_bound_is_private_and_has_no_partial_save(api):
    client, _, base, dataset = api
    component, _ = await setup_binding(client, base, dataset)
    path = base + "/components/" + component["id"] + "/request-versions"
    response = await client.post(path, content=b"SYNTHETIC_SECRET" * 220000, headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert (await client.get(path)).json()["request_versions"] == []
