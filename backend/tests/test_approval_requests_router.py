"""Assigned human approval API, strict actors and original-ID reconciliation."""

import pytest
from test_evaluation_registry_router import api as api
from test_qa_approvals_router import APPROVER, patch_approver_accounts, setup_approval

from app.evaluation.approval_requests import ApprovalRequestRepository
from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

ROOT = "/api/evaluation/approval-requests"
REQUEST, VIEW, SIGN, REVOKE = [char * 32 for char in "def9"]


@pytest.fixture(autouse=True)
def accounts(monkeypatch):
    return patch_approver_accounts(monkeypatch)


async def ready(api, monkeypatch, *, create=True):
    from app.gateway.routers import evaluation_approval_requests as routes

    client, app, _, _ = api
    app.include_router(routes.router)
    app.include_router(routes.project_router)
    source, assessment = await setup_approval(api, monkeypatch)
    repo = ApprovalRequestRepository(app.state.evaluation_repo.sf)
    payload = {"assessment_id": assessment["id"], "assessment_hash": assessment["assessment_hash"], "approver_id": APPROVER, "expires_at_ms": repo._time() + 60_000, "share_summary": True, "confirmed": True}
    path = source + "/approval-requests/" + REQUEST
    receipt = None
    if create:
        response = await client.post(path, json=payload)
        assert response.status_code == 200, response.text
        receipt = response.json()
    return path, payload, receipt


def command(receipt):
    return {"expected_revision": receipt["revision"], "subject_hash": receipt["subject_hash"], "confirmed": True}


@pytest.mark.asyncio
async def test_assigned_member_signs_self_and_owner_cannot_impersonate(api, monkeypatch):
    client, app, base, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    path = ROOT + "/" + REQUEST
    assert (await client.get(path)).json() == receipt
    payload = {**command(receipt), "decision": "approved", "view_id": VIEW, "expected_previous_approval_revision": 0}
    assert (await client.post(path + "/decisions/" + SIGN, json=payload)).status_code == 409
    app.state.actor = 5
    app.state.permissions = []
    assert (await client.get(base)).status_code == 404
    assert (await client.get(ROOT)).json()["requests"] == [receipt]
    opened = await client.post(path + "/views/" + VIEW, json=command(receipt))
    assert opened.status_code == 200
    assert (await client.get(path + "/views/" + VIEW)).json() == opened.json()
    signed = await client.post(path + "/decisions/" + SIGN, json=payload)
    assert signed.status_code == 200 and signed.json()["status"] == "approved"
    assert (await client.get(path + "/operations/" + SIGN)).json() == signed.json()
    state = await client.get(path + "/state")
    assert state.status_code == 200 and state.json()["approval_revision"] == 1
    assert state.json()["effectiveness"]["status"] == "effective"
    notices = await client.get(ROOT + "/notifications")
    assert [item["action"] for item in notices.json()["notifications"]] == ["requested", "approved"]
    for response in (opened, signed, state, notices):
        assert "no-store" in response.headers["cache-control"]
        assert not any(secret in response.text for secret in ("SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_NOTE", "password_hash", "cases"))
    app.state.actor = 1
    assert (await client.get(path + "/views/" + VIEW)).status_code == 404
    app.state.actor = 6
    assert (await client.get(path)).status_code == 404
    assert (await client.get(ROOT + "/notifications")).json()["notifications"] == []
    app.state.actor = 0
    assert (await client.get(ROOT)).status_code == 401


@pytest.mark.asyncio
async def test_internal_agents_are_rejected_on_narrow_approval_routes(api, monkeypatch):
    client, app, _, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    app.state.actor = 5
    app.state.internal = True
    path = ROOT + "/" + REQUEST
    for target in (ROOT, ROOT + "/notifications", path, path + "/state", path + "/operations/" + SIGN, path + "/views/" + VIEW):
        assert (await client.get(target)).status_code == 403
    assert (await client.post(path + "/views/" + VIEW, json=command(receipt))).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"recorded_by": APPROVER}, {"approver_id": APPROVER}, {"confirmed": 1}, {"expected_previous_approval_revision": True}, {"note": " "}])
async def test_forged_signature_identity_and_invalid_commands_are_private(api, monkeypatch, changes):
    client, app, _, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    app.state.actor = 5
    payload = {**command(receipt), "decision": "approved", "view_id": VIEW, "expected_previous_approval_revision": 0, **changes}
    response = await client.post(ROOT + "/" + REQUEST + "/decisions/" + SIGN, json=payload)
    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]
    assert APPROVER not in response.text


@pytest.mark.asyncio
async def test_missing_approver_rejects_assignment_after_ownership_check(api, monkeypatch, accounts):
    client, app, _, _ = api
    path, payload, _ = await ready(api, monkeypatch, create=False)
    accounts.pop(APPROVER)
    assert (await client.post(path, json=payload)).status_code == 409
    assert (await client.get(ROOT + "/" + REQUEST)).status_code == 404
    app.state.actor = 6
    assert (await client.post(path, json=payload)).status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_signature_only_reconciles_original_operation(api, monkeypatch, committed):
    client, app, _, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    app.state.actor = 5
    path = ROOT + "/" + REQUEST
    assert (await client.post(path + "/views/" + VIEW, json=command(receipt))).status_code == 200
    original = ApprovalRequestRepository.decide

    async def unknown(self, *args, **kwargs):
        if committed:
            await original(self, *args, **kwargs)
        raise JournalWriteUnconfirmed("SYNTHETIC_SECRET_SQL")

    monkeypatch.setattr(ApprovalRequestRepository, "decide", unknown)
    response = await client.post(path + "/decisions/" + SIGN, json={**command(receipt), "decision": "approved", "view_id": VIEW, "expected_previous_approval_revision": 0})
    assert response.status_code == 503 and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
    result = await client.get(path + "/operations/" + SIGN)
    assert result.status_code == (200 if committed else 404)
    assert len((await client.get(ROOT + "/notifications")).json()["notifications"]) == (2 if committed else 1)


@pytest.mark.asyncio
async def test_approver_revokes_self_with_required_reason(api, monkeypatch):
    client, app, _, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    path = ROOT + "/" + REQUEST
    app.state.actor = 5
    assert (await client.post(path + "/views/" + VIEW, json=command(receipt))).status_code == 200
    signed = await client.post(path + "/decisions/" + SIGN, json={**command(receipt), "decision": "approved", "view_id": VIEW, "expected_previous_approval_revision": 0})
    assert signed.status_code == 200
    revoked = await client.post(path + "/decisions/" + REVOKE, json={**command(signed.json()), "decision": "revoked", "expected_previous_approval_revision": 1, "note": "SYNTHETIC_REVOCATION"})
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert (await client.get(path + "/state")).json()["effectiveness"]["status"] == "revoked"


@pytest.mark.asyncio
async def test_owner_cancels_pending_request_without_impersonating_signature(api, monkeypatch):
    client, app, _, _ = api
    _, _, receipt = await ready(api, monkeypatch)
    path = ROOT + "/" + REQUEST
    app.state.actor = 5
    assert (await client.post(path + "/cancellations/" + REVOKE, json=command(receipt))).status_code == 409
    app.state.actor = 1
    cancelled = await client.post(path + "/cancellations/" + REVOKE, json=command(receipt))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await client.get(path + "/operations/" + REVOKE)).json() == cancelled.json()
    app.state.actor = 5
    assert (await client.post(path + "/views/" + VIEW, json=command(cancelled.json()))).status_code == 409


@pytest.mark.asyncio
async def test_account_that_needs_setup_cannot_be_assigned_or_sign(api, monkeypatch, accounts):
    client, app, _, _ = api
    path, payload, _ = await ready(api, monkeypatch, create=False)
    accounts[APPROVER].needs_setup = True
    assert (await client.post(path, json=payload)).status_code == 409
    accounts[APPROVER].needs_setup = False
    receipt = (await client.post(path, json=payload)).json()
    app.state.actor = 5
    path = ROOT + "/" + REQUEST
    assert (await client.post(path + "/views/" + VIEW, json=command(receipt))).status_code == 200
    accounts[APPROVER].needs_setup = True
    signed = await client.post(path + "/decisions/" + SIGN, json={**command(receipt), "decision": "approved", "view_id": VIEW, "expected_previous_approval_revision": 0})
    assert signed.status_code == 409
    assert (await client.get(path + "/operations/" + SIGN)).status_code == 404
