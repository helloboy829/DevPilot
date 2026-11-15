"""Synthetic owner-recorded formal approval API; no targets or live credentials."""

from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence
from test_review_tasks import ARB, A, B, command, decision

from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.qa_approvals import ApprovalRepository
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCreate
from app.gateway.auth.models import User
from app.gateway.authz import Permissions
from app.gateway.routers import evaluation_projects as routes

APPROVER = str(UUID(int=5))
APPROVAL = "b" * 32
ASSESSMENT = "c" * 32


def patch_approver_accounts(monkeypatch):
    """Exact-ID synthetic accounts for owner, approver, blind reviewers and arbitrator."""
    users = {str(UUID(int=index)): User(id=UUID(int=index), email=f"account{index}@example.com") for index in (1, 5)}
    users.update({actor: User(id=UUID(actor), email=f"{actor[:8]}@example.com") for actor in (A, B, ARB)})

    async def get_user(key):
        return users.get(key)

    monkeypatch.setattr(routes, "get_local_provider", lambda: SimpleNamespace(get_user=get_user))
    return users


@pytest.fixture(autouse=True)
def approver_account(monkeypatch):
    return patch_approver_accounts(monkeypatch)


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


@pytest.mark.asyncio
async def test_approval_audit_is_metadata_only_and_permissioned(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    created = await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment, note="SYNTHETIC_APPROVAL_NOTE"))
    assert created.status_code == 200
    audit = await client.get(root + "/approvals/audit")
    assert audit.status_code == 200 and "no-store" in audit.headers["cache-control"]
    assert [(event["sequence"], event["action"], event["revision"]) for event in audit.json()] == [(1, "approved", 1)]
    assert not any(secret in audit.text for secret in ("SYNTHETIC_APPROVAL_NOTE", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "document", "note"))
    assert (await client.get(root + "/approvals/" + APPROVAL)).status_code == 200
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(root + "/approvals/audit")).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(root + "/approvals/audit")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(root + "/approvals/audit")).status_code == 404
    app.state.actor = 0
    assert (await client.get(root + "/approvals/audit")).status_code == 401


@pytest.mark.asyncio
async def test_revocation_appends_second_revision_and_ordered_audit_over_api(api, monkeypatch):
    client, _, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    approved = await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))
    assert approved.status_code == 200
    revoked = await client.post(root + "/approvals/" + "e" * 32, json=payload(assessment, decision="revoked", note="SYNTHETIC_REVOCATION", expected_previous_revision=1))
    assert revoked.status_code == 200 and revoked.json()["revision"] == 2 and revoked.json()["decision"] == "revoked"
    listing = await client.get(root + "/approvals")
    assert [(item["revision"], item["decision"]) for item in listing.json()] == [(2, "revoked"), (1, "approved")]
    audit = await client.get(root + "/approvals/audit")
    assert [(event["sequence"], event["action"]) for event in audit.json()] == [(1, "approved"), (2, "revoked")]
    assert (await client.get(root + "/approvals/" + APPROVAL)).json()["decision"] == "approved"


@pytest.mark.asyncio
async def test_approval_preflight_reports_blockers_and_never_writes(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/assessments/" + assessment["id"] + "/approval-preflight"
    eligible = await client.get(path, params={"approver_id": APPROVER})
    assert eligible.status_code == 200 and eligible.json()["eligible"] is True and "no-store" in eligible.headers["cache-control"]
    assert eligible.json()["latest_approval"] is None
    assert not any(secret in eligible.text for secret in ("document", "note", "counts", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT"))
    assert (await client.get(root + "/approvals")).json() == []
    owner_blocked = await client.get(path, params={"approver_id": str(UUID(int=1))})
    assert owner_blocked.json()["eligible"] is False and owner_blocked.json()["blockers"] == ["approver_is_owner"]
    reviewer_blocked = await client.get(path, params={"approver_id": A})
    assert reviewer_blocked.json()["eligible"] is False and "approver_is_review_actor" in reviewer_blocked.json()["blockers"]
    invalid = await client.get(path, params={"approver_id": "SYNTHETIC_SECRET"})
    assert invalid.status_code == 422 and "SYNTHETIC" not in invalid.text
    assert (await client.get(root + "/assessments/" + "f" * 32 + "/approval-preflight", params={"approver_id": APPROVER})).status_code == 404
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path, params={"approver_id": APPROVER})).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path, params={"approver_id": APPROVER})).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path, params={"approver_id": APPROVER})).status_code == 404
    app.state.actor = 0
    assert (await client.get(path, params={"approver_id": APPROVER})).status_code == 401


@pytest.mark.asyncio
async def test_approval_preflight_marks_provisional_assessment(api, monkeypatch):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    preview = (await client.get(root + "/independent-assessment")).json()
    archived = (await client.post(root + "/assessments/" + ASSESSMENT, json={"summary_hash": preview["summary_hash"], "expected_previous_revision": 0, "confirmed": True})).json()
    result = await client.get(root + "/assessments/" + archived["id"] + "/approval-preflight", params={"approver_id": APPROVER})
    assert result.status_code == 200 and result.json()["eligible"] is False
    assert "independent_review_incomplete" in result.json()["blockers"]


@pytest.mark.asyncio
async def test_project_approval_index_is_latest_metadata_only_and_permissioned(api, monkeypatch):
    client, app, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    assert (await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))).status_code == 200
    index = await client.get(base + "/approvals")
    assert index.status_code == 200 and "no-store" in index.headers["cache-control"]
    entries = index.json()
    assert [(entry["run_id"], entry["revision"], entry["decision"]) for entry in entries] == [(root.rsplit("/", 1)[1], 1, "approved")]
    assert "document" not in index.text and "note" not in index.text
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(base + "/approvals")).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(base + "/approvals")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(base + "/approvals")).status_code == 404
    app.state.actor = 0
    assert (await client.get(base + "/approvals")).status_code == 401


@pytest.mark.asyncio
async def test_empty_approval_surfaces_and_unknown_run(api, monkeypatch):
    client, _, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    assert (await client.get(base + "/approvals")).json() == []
    assert (await client.get(root + "/approvals")).json() == []
    assert (await client.get(root + "/approvals/audit")).json() == []
    unknown = await client.get(base + "/review-runs/" + "f" * 32 + "/assessments/" + assessment["id"] + "/approval-preflight", params={"approver_id": APPROVER})
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_approval_chain_integrity_is_metadata_only_and_permissioned(api, monkeypatch):
    client, app, _, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    assert (await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))).status_code == 200
    path = root + "/approvals/integrity"
    result = await client.get(path)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    assert result.json() == {"schema": "qa-approval-chain.v1", "scope": "approval_audit_chain_only", "status": "verified", "approvals": 1, "events": 1, "blockers": []}
    assert not any(secret in result.text for secret in ("document", "note", "hash", "SYNTHETIC"))
    assert (await client.get(root + "/approvals/" + APPROVAL)).status_code == 200
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401
    assert (await client.get(root + "/approvals/integrity", params={})).headers.get("cache-control")


@pytest.mark.asyncio
async def test_project_approval_chain_summary_is_metadata_only_and_permissioned(api, monkeypatch):
    client, app, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    assert (await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))).status_code == 200
    path = base + "/approvals/integrity"
    result = await client.get(path)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    assert result.json() == {"schema": "qa-approval-chain-summary.v1", "scope": "project_approval_audit_chains_only", "status": "verified", "runs": 1, "verified_runs": 1, "broken_runs": 0, "approvals": 1, "events": 1, "blockers": []}
    assert not any(secret in result.text for secret in ("document", "note", "hash", "SYNTHETIC", root.rsplit("/", 1)[1]))
    original = app.state.permissions
    original_actor = app.state.actor
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401
    app.state.actor = original_actor
    assert (await client.get(root + "/approvals/" + APPROVAL)).status_code == 200
    listing = await client.get(base + "/approvals")
    assert listing.status_code == 200 and len(listing.json()) == 1


@pytest.mark.asyncio
async def test_approval_requires_an_existing_active_approver_account(api, monkeypatch, approver_account):
    client, app, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/approvals/" + APPROVAL
    preflight = root + "/assessments/" + ASSESSMENT + "/approval-preflight"
    approver_account.clear()
    created = await client.post(path, json=payload(assessment))
    assert created.status_code == 409
    preview = await client.get(preflight, params={"approver_id": APPROVER})
    assert preview.status_code == 200
    body = preview.json()
    assert body["eligible"] is False and "approver_account_not_found" in body["blockers"]
    assert body["approval"] == "not_recorded"
    assert (await client.get(root + "/approvals")).json() == []
    approver_account[APPROVER] = User(id=UUID(APPROVER), email="approver@example.com", needs_setup=True)
    assert (await client.post(path, json=payload(assessment))).status_code == 409
    preview = await client.get(preflight, params={"approver_id": APPROVER})
    assert preview.status_code == 200 and "approver_account_not_found" in preview.json()["blockers"]
    assert (await client.get(root + "/approvals")).json() == []


@pytest.mark.asyncio
async def test_approval_signoff_progress_is_aggregate_and_permissioned(api, monkeypatch):
    client, app, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/approvals/sign-off"
    empty = await client.get(path)
    assert empty.status_code == 200 and "no-store" in empty.headers["cache-control"]
    assert empty.json() == {
        "schema": "qa-approval-signoff.v1",
        "scope": "approval_signoff_progress_only",
        "policy": "not_defined",
        "required_distinct_approvers": None,
        "revisions": 0,
        "distinct_approvers": 0,
        "distinct_approved_approvers": 0,
        "approved_revisions": 0,
        "revoked_revisions": 0,
        "latest_revision": None,
        "latest_decision": None,
        "multi_level_satisfied": None,
        "blockers": ["multi_level_policy_not_defined", "approver_login_not_implemented"],
    }
    assert (await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))).status_code == 200
    progress = await client.get(path)
    assert progress.status_code == 200
    body = progress.json()
    assert body["revisions"] == 1 and body["distinct_approvers"] == 1
    assert body["latest_revision"] == 1 and body["latest_decision"] == "approved"
    assert not any(secret in progress.text for secret in ("document", "note", "hash", "SYNTHETIC", APPROVAL, APPROVER))
    original = app.state.permissions
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_signoff_requirement_is_advisory_and_read_only(api, monkeypatch):
    client, app, base, _ = api
    root, assessment = await setup_approval(api, monkeypatch)
    path = root + "/approvals/sign-off"
    assert (await client.post(root + "/approvals/" + APPROVAL, json=payload(assessment))).status_code == 200
    blocked = await client.get(path, params={"required_distinct_approvers": 2})
    assert blocked.status_code == 200 and "no-store" in blocked.headers["cache-control"]
    body = blocked.json()
    assert body["policy"] == "not_defined" and body["multi_level_satisfied"] is None
    assert body["requirement"]["schema"] == "qa-signoff-requirement.v1"
    assert body["requirement"]["policy"] == {"defined": True, "required_distinct_approvers": 2}
    assert body["requirement"]["satisfied"] is False
    assert body["requirement"]["blockers"] == ["insufficient_approvers"]
    assert body["requirement"]["approval"] == "not_approved"
    satisfied = (await client.get(path, params={"required_distinct_approvers": 1})).json()
    assert satisfied["requirement"]["satisfied"] is True
    assert satisfied["requirement"]["blockers"] == []
    plain = (await client.get(path)).json()
    assert "requirement" not in plain
    assert (await client.get(path, params={"required_distinct_approvers": 0})).status_code == 422
    assert (await client.get(path, params={"required_distinct_approvers": 11})).status_code == 422
    assert [item["revision"] for item in (await client.get(root + "/approvals")).json()] == [1]
    assert [(event["sequence"], event["action"]) for event in (await client.get(root + "/approvals/audit")).json()] == [(1, "approved")]
