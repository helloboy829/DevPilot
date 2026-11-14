"""Synthetic owner-recorded formal approval API; no targets or live credentials."""

from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence
from test_review_tasks import ARB, A, B, command, decision

from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.qa_approvals import ApprovalRepository
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCreate
from app.gateway.authz import Permissions

APPROVER = str(UUID(int=5))
APPROVAL = "b" * 32
ASSESSMENT = "c" * 32


async def setup_approval(api, monkeypatch):
    client, app, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    owner = str(UUID(int=1))
    project = base.rsplit("/", 1)[1]
    run_id = root.rsplit("/", 1)[1]
    repo = ReviewTaskRepository(app.state.evaluation_repo.sf)
    case = await repo.open_case(owner, project, run_id, 1)
    task = "a" * 32
    await repo.create_task(owner, project, task, TaskCreate(run_id=run_id, ordinal=1, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True))
    for actor in (A, B):
        claimed = await repo.claim(actor, task, command(await repo.get_task(actor, task)))
        await repo.open_task(actor, task)
        await repo.submit_decision(actor, task, decision(claimed, "pass"))
    preview = (await client.get(root + "/independent-assessment")).json()
    created = await client.post(root + "/assessments/" + ASSESSMENT, json={"summary_hash": preview["summary_hash"], "expected_previous_revision": 0, "confirmed": True})
    assert created.status_code == 200
    return root, created.json()


def payload(assessment, **changes):
    return {
        "assessment_id": assessment["id"],
        "assessment_hash": assessment["assessment_hash"],
        "expected_previous_revision": 0,
        "approver_id": APPROVER,
        "decision": "approved",
        "confirmed": True,
        **changes,
    }


@pytest.mark.asyncio
async def test_explicit_approval_read_write_permissions_and_no_store(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/approvals/" + APPROVAL
    created = await client.post(path, json=payload(assessment))
    assert created.status_code == 200 and created.json()["decision"] == "approved" and created.json()["revision"] == 1
    assert (await client.get(path)).json() == created.json()
    listing = await client.get(root + "/approvals")
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert "document" not in listing.text and "cases" not in listing.text
    for response in (created, listing):
        assert "no-store" in response.headers["cache-control"]
        assert not any(secret in response.text for secret in ("SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_NOTE", "encrypted_payload"))
    assert (await client.delete(path)).status_code == 405
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(root + "/approvals")).status_code == 403
    assert (await client.get(path)).status_code == 403
    assert (await client.post(path, json=payload(assessment))).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(path)).status_code == 200
    assert (await client.post(path, json=payload(assessment))).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_append_only_reconciles_same_id_and_generic_errors(api, monkeypatch, committed):
    client, _, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/approvals/" + APPROVAL
    original = ApprovalRepository.create_approval

    async def committed_but_unconfirmed(self, *args, **kwargs):
        if committed:
            await original(self, *args, **kwargs)
        raise JournalWriteUnconfirmed("SYNTHETIC_SECRET")

    monkeypatch.setattr(ApprovalRepository, "create_approval", committed_but_unconfirmed)
    result = await client.post(path, json=payload(assessment))
    assert result.status_code == 503 and "SYNTHETIC" not in result.text and "no-store" in result.headers["cache-control"]
    found = await client.get(path)
    assert found.status_code == (200 if committed else 404)
    if committed:
        assert found.json()["revision"] == 1

    async def sql_failure(self, *args, **kwargs):
        raise OperationalError("SYNTHETIC_SQL", {"secret": "SYNTHETIC_SECRET"}, Exception("SYNTHETIC_EXCEPTION"))

    monkeypatch.setattr(ApprovalRepository, "list_approvals", sql_failure)
    failed = await client.get(root + "/approvals")
    assert failed.status_code == 503 and "SYNTHETIC" not in failed.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": 1},
        {"assessment_hash": "SYNTHETIC_SECRET"},
        {"assessment_id": "SYNTHETIC_SECRET"},
        {"approver_id": "SYNTHETIC_SECRET"},
        {"decision": "SYNTHETIC_SECRET"},
        {"expected_previous_revision": True},
        {"decision": "revoked"},
    ],
)
async def test_validation_redacts_all_client_values(api, monkeypatch, changes):
    client, _, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    result = await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment, **changes))
    assert result.status_code == 422 and "SYNTHETIC_SECRET" not in result.text and "no-store" in result.headers["cache-control"]


@pytest.mark.asyncio
async def test_provisional_independent_review_cannot_be_approved_over_api(api, monkeypatch):
    client, _, base, _ = api
    root = await setup_evidence(api, monkeypatch)
    preview = (await client.get(root + "/independent-assessment")).json()
    assert preview["readiness"] == "provisional"
    archived = (await client.post(root + "/assessments/" + ASSESSMENT, json={"summary_hash": preview["summary_hash"], "expected_previous_revision": 0, "confirmed": True})).json()
    result = await client.post(root + "/approvals/" + APPROVAL, json=payload(archived))
    assert result.status_code == 409 and "no-store" in result.headers["cache-control"]
    assert (await client.get(root + "/approvals/" + APPROVAL)).status_code == 404
