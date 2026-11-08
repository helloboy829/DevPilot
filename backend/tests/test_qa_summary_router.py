"""Private, independently authorized human summary read API."""

import pytest
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence

from app.gateway.authz import Permissions


@pytest.mark.asyncio
async def test_summary_is_explicit_private_and_has_no_raw_evidence(api, monkeypatch):
    client, app, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    response = await client.get(root + "/summary")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    result = response.json()
    assert result["human_pass_rate"] == {"numerator": 0, "denominator": 1, "value": 0}
    assert result["counts"]["unreviewed"] == 1
    assert result["acceptance"] == "not_approved"
    assert "SYNTHETIC" not in response.text
    assert "encrypted_payload" not in response.text
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(root + "/summary")).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(root + "/summary")).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(root + "/summary")).status_code == 200
    app.state.internal = True
    assert (await client.get(root + "/summary")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(root + "/summary")).status_code == 404
    app.state.actor = 0
    assert (await client.get(root + "/summary")).status_code == 401


@pytest.mark.asyncio
async def test_missing_key_does_not_fall_back_to_unverified_counts(api, monkeypatch):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    response = await client.get(root + "/summary")
    assert response.status_code == 503
    assert "no-store" in response.headers["cache-control"]
    assert "SYNTHETIC" not in response.text
    assert (await client.get(root + "/cases")).status_code == 200
