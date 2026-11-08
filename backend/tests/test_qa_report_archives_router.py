"""Synthetic private report archive API; no business payloads or target calls."""

from uuid import uuid4

import pytest
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence

from app.gateway.authz import Permissions


async def source(api, monkeypatch):
    client = api[0]
    run_path = await setup_evidence(api, monkeypatch)
    case = (await client.get(run_path + "/cases/1")).json()
    reviewed = await client.post(run_path + "/cases/1/reviews", json={"case_hash": case["case_hash"], "expected_revision": 0, "decision": "pass", "note": "Synthetic review", "confirmed": True})
    assert reviewed.status_code == 200
    summary = (await client.get(run_path + "/summary")).json()
    return {"title": "Synthetic archive", "template_id": "verified-qa-project-en", "template_version": "1.0.0", "sources": [{"run_id": summary["run_id"], "summary_hash": summary["summary_hash"]}], "confirmed": True}


@pytest.mark.asyncio
async def test_explicit_archive_reopen_metadata_and_permissions(api, monkeypatch):
    client, app, base, _ = api
    payload = await source(api, monkeypatch)
    catalog = await client.get(base + "/report-templates")
    assert catalog.status_code == 200 and len(catalog.json()["templates"]) == 2
    path = base + "/report-archives/" + uuid4().hex
    response = await client.put(path, json=payload)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    saved = response.json()
    assert saved["acceptance"] == "not_approved" and saved["revision"] == 1
    assert "SYNTHETIC_OUTPUT" not in response.text and "SYNTHETIC_GOLD" not in response.text
    assert (await client.get(path)).json() == saved
    assert (await client.put(path, json=payload)).json() == saved
    listing = await client.get(base + "/report-archives")
    assert len(listing.json()["archives"]) == 1 and "markdown" not in listing.text
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
    assert (await client.get(path)).status_code == 200
    assert (await client.put(path, json=payload)).status_code == 403
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    assert (await client.get(base + "/report-archives")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_private_validation_and_historical_read_without_request_key(api, monkeypatch):
    client, _, base, _ = api
    payload = await source(api, monkeypatch)
    path = base + "/report-archives/" + uuid4().hex
    assert (await client.put(path, json={**payload, "confirmed": 1})).status_code == 422
    assert (await client.put(path, json={**payload, "metrics": {"pass_rate": 1}})).status_code == 422
    assert (await client.put(path, json={**payload, "sources": []})).status_code == 422
    assert (await client.put(base + "/report-archives/not-valid", json=payload)).status_code == 422
    assert (await client.put(path, json=payload)).status_code == 200
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(path)).status_code == 200
    assert (await client.put(base + "/report-archives/" + uuid4().hex, json=payload)).status_code == 503
    changed = await client.put(path, json={**payload, "title": "Different"})
    assert changed.status_code == 409 and "no-store" in changed.headers["cache-control"]
