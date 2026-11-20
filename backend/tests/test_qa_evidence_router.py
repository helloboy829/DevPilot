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
    from app.evaluation.qa_artifact_store import ResponseArtifactStore

    client, app, base, _ = api
    monkeypatch.setenv("DEVPILOT_QA_ARTIFACT_DIR", str(app.state.test_artifact_root))
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    path, payload = await setup_plan(api, monkeypatch)
    plan = (await client.post(path, json=payload)).json()
    repo = EvidenceRepository(app.state.evaluation_repo.sf)
    owner = str(UUID(int=1))
    project = base.rsplit("/", 1)[1]
    run = await repo.record_run(owner, project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=129))
    ticket = await repo.record_dispatch(owner, project, run["id"], 1, body_bytes=20)
    request_body = b"SYNTHETIC_REQUEST"
    response_body = b"SYNTHETIC_RAW_RESPONSE"
    import hashlib

    request_hash = hashlib.sha256(request_body).hexdigest()
    await repo.record_request_capture(owner, project, run["id"], ticket, body_sha256=request_hash, body_bytes=len(request_body), contract_version="qa-json-request.v1")
    await repo.record_attempt(
        owner,
        project,
        run["id"],
        ticket,
        AttemptObservation(
            "output_collected",
            200,
            len(response_body),
            12.0,
            "SYNTHETIC_OUTPUT",
            request_body_sha256=request_hash,
            request_body_bytes=len(request_body),
            response_body=response_body,
            response_capture_status="complete",
            response_content_type="application/json",
            response_content_encoding="identity",
            response_body_sha256=hashlib.sha256(response_body).hexdigest(),
            response_body_hash_scope="full",
        ),
    )
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
    assert (await client.get(root + "/cases/1")).status_code == 200
    assert (await client.post(root + "/cases/1/reviews", json=payload)).status_code == 409
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(root + "/cases/1")).status_code == 200
    assert (await client.post(root + "/cases/1/reviews", json=payload)).status_code == 409
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


@pytest.mark.asyncio
async def test_response_evidence_requires_explicit_grant_and_is_actor_bound(api, monkeypatch):
    client, app, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    run_id = root.rsplit("/", 1)[1]
    cases = (await client.get(f"{base}/runs/{run_id}/cases")).json()["items"]
    evidence_hash = cases[0]["response_evidence"]["sha256"]
    assert cases[0]["response_evidence"]["status"] == "complete"
    grant_path = f"{root}/cases/1/evidence-access"

    def read_path(access_id):
        return f"{base}/evidence/{access_id}"

    grant = await client.post(grant_path, json={"kind": "response", "evidence_hash": evidence_hash, "confirmed": True})
    assert grant.status_code == 200, grant.text
    token = grant.json()["access_id"]
    assert "SYNTHETIC_RAW_RESPONSE" not in grant.text

    wrong_project_path = f"/api/evaluation/projects/{'f' * 32}/evidence/{token}"
    assert (await client.get(wrong_project_path)).status_code == 404
    app.state.actor = 2
    assert (await client.get(read_path(token))).status_code == 404
    app.state.actor = 1
    response = await client.get(read_path(token))
    assert response.status_code == 200
    assert response.content == b"SYNTHETIC_RAW_RESPONSE"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["content-type"] == "application/octet-stream"
    assert "attachment" in response.headers["content-disposition"]
    assert (await client.get(read_path(token))).status_code == 404


@pytest.mark.asyncio
async def test_evidence_grant_requires_intact_artifact_receipt(api, monkeypatch):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    from app.evaluation.qa_artifact_store import ResponseArtifactStore

    monkeypatch.setattr(ResponseArtifactStore, "inspect", lambda *_args: None)
    run_id = root.rsplit("/", 1)[1]
    cases = (await client.get(f"{base}/runs/{run_id}/cases")).json()["items"]
    evidence_hash = cases[0]["response_evidence"]["sha256"]
    response = await client.post(
        f"{root}/cases/1/evidence-access",
        json={"kind": "response", "evidence_hash": evidence_hash, "confirmed": True},
    )
    assert response.status_code == 409
    assert "access_id" not in response.text


@pytest.mark.asyncio
async def test_evidence_grant_rejects_unavailable_kind_and_stale_hash(api, monkeypatch):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    grant_path = f"{root}/cases/1/evidence-access"

    unavailable = await client.post(grant_path, json={"kind": "request", "evidence_hash": "0" * 64, "confirmed": True})
    assert unavailable.status_code == 409
    stale = await client.post(grant_path, json={"kind": "response", "evidence_hash": "0" * 64, "confirmed": True})
    assert stale.status_code == 409
    assert "SYNTHETIC" not in unavailable.text + stale.text


@pytest.mark.asyncio
async def test_response_evidence_range_reject_does_not_consume_grant(api, monkeypatch):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    run_id = root.rsplit("/", 1)[1]
    cases = (await client.get(f"{base}/runs/{run_id}/cases")).json()["items"]
    evidence_hash = cases[0]["response_evidence"]["sha256"]
    grant = await client.post(
        f"{root}/cases/1/evidence-access",
        json={"kind": "response", "evidence_hash": evidence_hash, "confirmed": True},
    )
    assert grant.status_code == 200
    evidence_url = f"{base}/evidence/{grant.json()['access_id']}"

    invalid = await client.get(evidence_url, headers={"Range": "bytes=999999-"})
    assert invalid.status_code == 416
    assert "no-store" in invalid.headers["cache-control"]

    ranged = await client.get(evidence_url, headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206
    assert ranged.content == b"SYNT"
    assert ranged.headers["content-range"] == "bytes 0-3/22"
    assert ranged.headers["accept-ranges"] == "bytes"
    assert (await client.get(evidence_url)).status_code == 404


@pytest.mark.parametrize("confirmed", [False, 1, "true", None])
@pytest.mark.asyncio
async def test_evidence_grant_requires_literal_confirmation(api, monkeypatch, confirmed):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    response = await client.post(
        f"{root}/cases/1/evidence-access",
        json={"kind": "response", "evidence_hash": "0" * 64, "confirmed": confirmed},
    )
    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"expected_revision": True}, {"note": "SYNTHETIC_SECRET" * 2000}, {"output": "SYNTHETIC_FORGED"}])
@pytest.mark.asyncio
async def test_validation_never_echoes_sensitive_input(api, monkeypatch, changes):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    case = (await client.get(root + "/cases/1")).json()
    response = await client.post(root + "/cases/1/reviews", json={"case_hash": case["case_hash"], "expected_revision": 0, "decision": "pass", "note": "Synthetic", "confirmed": True, **changes})
    assert response.status_code == 422 and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
