"""Real password/JWT/CSRF signatures by ordinary evaluation members."""

import asyncio
import time
from uuid import uuid4

import pytest
from test_qa_authenticated_workflow_api import accounts, create_task, route_policy, vote
from test_qa_authenticated_workflow_api import api as api
from test_qa_workflow_api import collect, create_plan, response_json
from test_qa_workflow_api import workflow as workflow

from app.gateway import authz
from app.gateway.routers import evaluation_approval_requests

ROOT = "/api/evaluation/approval-requests"


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["empty", "deny", "unavailable"])
async def test_real_ordinary_account_signs_and_revokes_own_assignment_without_reviewer_role(workflow, monkeypatch, policy):
    state = workflow
    state.app.include_router(evaluation_approval_requests.router)
    state.app.include_router(evaluation_approval_requests.project_router)
    root, _ = await collect(state, await create_plan(state, "v2", timeout_ms=5000), build="v2")
    identities = accounts(state)
    signer = identities.clients["outsider"]
    signer_id = str(identities.users["outsider"].id)
    for ordinal in range(1, 4):
        path, _, _ = await create_task(state, root, ordinal)
        await vote(state, path, "reviewer_a", "pass")
        await vote(state, path, "reviewer_b", "pass")
    summary = response_json(await state.client.get(root + "/independent-assessment"))
    assessment = response_json(await state.client.post(root + "/assessments/" + uuid4().hex, json={"summary_hash": summary["summary_hash"], "expected_previous_revision": 0, "confirmed": True}))
    assert assessment["assessment"]["criteria_evaluation"]["status"] == "met"
    if policy == "unavailable":

        def unavailable(_config):
            raise RuntimeError("SYNTHETIC_PROVIDER_UNAVAILABLE")

        monkeypatch.setattr(authz, "_get_cached_route_provider", unavailable)
    identities.policy["value"] = route_policy(allow=[], deny=[] if policy == "empty" else ["evaluation_projects:read", "evaluation_projects:write", "evaluation_projects:review"])
    request_id, view_id, sign_id, revoke_id = [uuid4().hex for _ in range(4)]
    now = time.time_ns() // 1_000_000
    assignment = {"assessment_id": assessment["id"], "assessment_hash": assessment["assessment_hash"], "approver_id": signer_id, "expires_at_ms": now + 60_000, "share_summary": True, "confirmed": True}
    create_path = root + "/approval-requests/" + request_id
    assert (await state.client.post(create_path, json=assignment, headers={"X-CSRF-Token": ""})).status_code == 403
    created = response_json(await state.client.post(create_path, json=assignment))
    command = {"expected_revision": created["revision"], "subject_hash": created["subject_hash"], "confirmed": True}
    path = ROOT + "/" + request_id
    assert response_json(await signer.get(ROOT))["requests"] == [created]
    assert (await signer.get(state.base + "/datasets")).status_code == 404
    assert (await identities.clients["reviewer_a"].get(path)).status_code == 404
    assert (await signer.post(path + "/views/" + view_id, json=command, headers={"X-CSRF-Token": ""})).status_code == 403
    opened = response_json(await signer.post(path + "/views/" + view_id, json=command))
    assert opened["summary"]["human_pass_rate"]["denominator"] == 3
    signed = response_json(await signer.post(path + "/decisions/" + sign_id, json={**command, "decision": "approved", "view_id": view_id, "expected_previous_approval_revision": 0}))
    assert signed["status"] == "approved"
    ledger = response_json(await state.client.get(root + "/approvals/" + sign_id))
    assert ledger["recorded_by"] == ledger["approver_id"] == signer_id
    assert ledger["schema"] == "qa-run-formal-approval.v2"
    assert response_json(await signer.get(path + "/state"))["effectiveness"]["status"] == "effective"
    revoke = {"expected_revision": signed["revision"], "subject_hash": signed["subject_hash"], "confirmed": True, "decision": "revoked", "expected_previous_approval_revision": 1, "note": "SYNTHETIC_SELF_REVOCATION"}
    assert (await state.client.post(path + "/decisions/" + revoke_id, json=revoke)).status_code == 409
    revoked = response_json(await signer.post(path + "/decisions/" + revoke_id, json=revoke))
    assert revoked["status"] == "revoked"
    notices = await asyncio.gather(state.client.get(ROOT + "/notifications"), signer.get(ROOT + "/notifications"))
    for response in notices:
        assert [item["action"] for item in response_json(response)["notifications"]] == ["requested", "approved", "revoked"]
    assert response_json(await state.client.get(root + "/approvals/" + sign_id)) == ledger
    assert len(state.sent) == 3
