"""Private human review API; synthetic fixtures only, never a target request."""

from uuid import UUID

import pytest
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api

from app.evaluation.dispatch_journal import JournalLimits
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.qa_evidence import EvidenceRepository
from app.gateway.authz import Permissions


async def setup_evidence(api, monkeypatch):
    client, app, base, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    plan = (await client.post(path, json=payload)).json()
    repo = EvidenceRepository(app.state.evaluation_repo.sf)
    owner = str(UUID(int=1))
    project = base.rsplit("/", 1)[1]
    run = await repo.record_run(owner, project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=129))
    ticket = await repo.record_dispatch(owner, project, run["id"], 1, body_bytes=20)
    await repo.record_attempt(owner, project, run["id"], ticket, AttemptObservation("output_collected", 200, 30, 12.0, "SYNTHETIC_OUTPUT"))
    return base + "/review-runs/" + run["id"]


@pytest.mark.asyncio
async def test_metadata_then_explicit_human_case_review_is_private_and_revisioned(api, monkeypatch):
    client, app, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    listing = await client.get(base + "/review-runs")
    assert listing.status_code == 200 and len(listing.json()["runs"]) == 1
    metadata = await client.get(root + "/cases")
    assert metadata.status_code == 200
    assert "SYNTHETIC_GOLD" not in metadata.text and "SYNTHETIC_OUTPUT" not in metadata.text
    opened = await client.get(root + "/cases/1")
    assert opened.status_code == 200 and "no-store" in opened.headers["cache-control"]
    case = opened.json()
    assert case["expected"] == "SYNTHETIC_GOLD" and case["output"] == "SYNTHETIC_OUTPUT"
    payload = {"case_hash": case["case_hash"], "expected_revision": 0, "decision": "pass", "note": "SYNTHETIC_NOTE", "confirmed": True}
    result = await client.post(root + "/cases/1/reviews", json=payload)
    assert result.status_code == 200 and result.json()["revision"] == 1
    assert (await client.post(root + "/cases/1/reviews", json=payload)).status_code == 409
    assert (await client.get(root + "/cases/1")).json()["reviews"][0]["note"] == "SYNTHETIC_NOTE"
    assert (await client.post(root + "/execute", json={})).status_code == 404
    assert (await client.post(root + "/cases/1/output", json={"output": "SYNTHETIC_FORGED"})).status_code == 404
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(root + "/cases")).status_code == 200
    assert (await client.get(root + "/cases/1")).status_code == 403
    assert (await client.post(root + "/cases/1/reviews", json=payload)).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(root + "/cases/1")).status_code == 200
    assert (await client.post(root + "/cases/1/reviews", json=payload)).status_code == 403
    app.state.internal = True
    assert (await client.get(root + "/cases/1")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(root + "/cases/1")).status_code == 404
    assert (await client.get(base + "/review-runs")).status_code == 404
    app.state.actor = 0
    assert (await client.get(root + "/cases")).status_code == 401


@pytest.mark.asyncio
async def test_unavailable_key_keeps_metadata_accessible_and_errors_private(api, monkeypatch):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    for path in (base + "/review-runs", root + "/cases"):
        response = await client.get(path)
        assert response.status_code == 200 and "encrypted_payload" not in response.text
    failed = await client.get(root + "/cases/1")
    assert failed.status_code == 503 and "no-store" in failed.headers["cache-control"] and "SYNTHETIC" not in failed.text


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"expected_revision": True}, {"note": "SYNTHETIC_SECRET" * 2000}, {"output": "SYNTHETIC_FORGED"}])
@pytest.mark.asyncio
async def test_validation_never_echoes_sensitive_input(api, monkeypatch, changes):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    case = (await client.get(root + "/cases/1")).json()
    response = await client.post(root + "/cases/1/reviews", json={"case_hash": case["case_hash"], "expected_revision": 0, "decision": "pass", "note": "Synthetic", "confirmed": True, **changes})
    assert response.status_code == 422 and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
