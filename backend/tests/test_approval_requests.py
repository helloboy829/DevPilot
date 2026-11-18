"""Self-signed approvals: narrow assignments, immutable decisions and stale fences."""

import asyncio
import json
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError
from test_dispatch_journal import prepared as prepared
from test_qa_approvals import archive
from test_qa_assessments import assessments as assessments
from test_qa_assessments import complete as complete
from test_qa_evidence import captured as captured
from test_review_tasks import TASK, A, TaskReopen, command
from test_review_tasks import tasks as tasks

from app.evaluation import tables as t
from app.evaluation.approval_requests import ApprovalRequestCreate, ApprovalRequestRepository, RequestCommand, SignatureCreate
from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.qa_approvals import ApprovalCreate
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError

APPROVER = str(UUID(int=5))
OUTSIDER = str(UUID(int=6))
REQUEST, VIEW, SIGNATURE, REVOKE = [key * 32 for key in ("d", "e", "f", "9")]


async def pending(tasks):
    source, project, run, assessment = await archive(tasks)
    repo = ApprovalRequestRepository(source.sf, protection=source.protection, evidence_protection=source.evidence_protection, clock_ms=source.clock_ms)
    payload = ApprovalRequestCreate(assessment_id=assessment["id"], assessment_hash=assessment["assessment_hash"], approver_id=APPROVER, expires_at_ms=repo._time() + 60_000, share_summary=True, confirmed=True)
    receipt = await repo.create_request("owner", project, run["id"], REQUEST, payload)
    return repo, project, run, assessment, payload, receipt


def cmd(receipt):
    return RequestCommand(expected_revision=receipt["revision"], subject_hash=receipt["subject_hash"], confirmed=True)


def signature(receipt, *, action="approved", previous=0, view_id=VIEW, note=None):
    return SignatureCreate(**cmd(receipt).model_dump(), decision=action, expected_previous_approval_revision=previous, view_id=view_id, note=note)


async def signed(tasks):
    repo, project, run, assessment, payload, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    result = await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    return repo, project, run, assessment, receipt, result


@pytest.mark.asyncio
async def test_assigned_human_signs_as_self_and_notifies_both_parties_atomically(tasks):
    repo, project, run, archived, request, signed_receipt = await signed(tasks)
    assert signed_receipt["status"] == "approved" and signed_receipt["revision"] == 2
    document = await repo.get_approval("owner", project, run["id"], SIGNATURE)
    assert document["schema"] == "qa-run-formal-approval.v2"
    assert document["recorded_by"] == document["approver_id"] == APPROVER
    assert document["authentication"] == {"mode": "signed_in_approver", "request_id": REQUEST, "subject_hash": request["subject_hash"]}
    assert document["assessment"]["assessment_hash"] == archived["assessment_hash"]
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "effective"
    assert (await repo.verify_approval_chain("owner", project, run["id"]))["status"] == "verified"
    for actor in ("owner", APPROVER):
        notices = await repo.notifications(actor)
        assert [item["action"] for item in notices["notifications"]] == ["requested", "approved"]
        assert all(item["request_id"] == REQUEST for item in notices["notifications"])
        assert not any(value in json.dumps(notices) for value in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "counts", "note", "document"))
    assert (await repo.notifications(OUTSIDER))["notifications"] == []
    async with repo.sf() as session:
        audit = (await session.execute(select(t.approval_audit))).mappings().one()
        assert audit["actor"] == APPROVER and audit["subject_hash"] == document["approval_hash"]
    assert await repo.get_assessment("owner", project, run["id"], archived["id"]) == archived


@pytest.mark.asyncio
async def test_assignment_never_grants_project_access_or_owner_impersonation(tasks):
    repo, project, run, _, _, receipt = await pending(tasks)
    for actor in (OUTSIDER, A):
        with pytest.raises(NotFound):
            await repo.get_request(actor, REQUEST)
        with pytest.raises(NotFound):
            await repo.open_summary(actor, REQUEST, VIEW, cmd(receipt))
    with pytest.raises(Conflict):
        await repo.open_summary("owner", REQUEST, VIEW, cmd(receipt))
    with pytest.raises(Conflict):
        await repo.decide("owner", REQUEST, SIGNATURE, signature(receipt))
    with pytest.raises(NotFound):
        await repo.list_assessments(APPROVER, project, run["id"])
    assert (await repo.inbox(APPROVER))["requests"] == [receipt]


@pytest.mark.asyncio
async def test_summary_open_is_explicit_pinned_and_contains_no_case_or_blind_actor_data(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    with pytest.raises(Conflict):
        await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    opened = await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    assert opened["view_id"] == VIEW and opened["summary"]["human_pass_rate"]["denominator"] == 2
    assert opened["summary"]["counts"]["pass"] == 2
    assert all(value not in json.dumps(opened) for value in ("SYNTHETIC_INPUT", "SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "cases", A, "note"))
    assert await repo.get_view(APPROVER, REQUEST, VIEW) == opened
    with pytest.raises(NotFound):
        await repo.get_view("owner", REQUEST, VIEW)


@pytest.mark.asyncio
async def test_expiry_and_open_view_fences_do_not_append_a_signature(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    tasks[5]["ms"] += 60_000
    with pytest.raises(Conflict):
        await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "expired"
    async with repo.sf() as session:
        assert (await session.execute(select(t.run_approvals))).all() == []


@pytest.mark.asyncio
async def test_view_from_another_request_cannot_authorize_a_signature(tasks):
    repo, project, run, _, payload, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    other_id = "6" * 32
    other = await repo.create_request("owner", project, run["id"], other_id, payload)
    with pytest.raises(Conflict):
        await repo.decide(APPROVER, other_id, SIGNATURE, signature(other))
    assert (await repo.get_request(APPROVER, other_id))["status"] == "pending"
    async with repo.sf() as session:
        assert (await session.execute(select(t.run_approvals))).all() == []


@pytest.mark.asyncio
async def test_source_reopened_after_open_blocks_signing_without_mutating_view(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    opened = await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    task = await tasks[0].get_task("owner", TASK)
    await tasks[0].reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_SOURCE_CHANGED"))
    with pytest.raises(Conflict):
        await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "stale"
    assert await repo.get_view(APPROVER, REQUEST, VIEW) == opened
    async with repo.sf() as session:
        assert (await session.execute(select(t.run_approvals))).all() == []


@pytest.mark.asyncio
async def test_expiry_closes_pending_signing_but_keeps_completed_signature_effective(tasks):
    repo, _, _, _, _, _ = await signed(tasks)
    tasks[5]["ms"] += 120_000
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "effective"


@pytest.mark.asyncio
async def test_only_actual_signer_can_revoke_and_owner_cannot_cancel_signed_request(tasks):
    repo, _, _, _, _, approved = await signed(tasks)
    revoke = signature(approved, action="revoked", previous=1, view_id=None, note="SYNTHETIC_REVOCATION")
    with pytest.raises(Conflict):
        await repo.decide("owner", REQUEST, REVOKE, revoke)
    with pytest.raises(NotFound):
        await repo.decide(OUTSIDER, REQUEST, REVOKE, revoke)
    with pytest.raises(Conflict):
        await repo.cancel("owner", REQUEST, "8" * 32, cmd(approved))
    assert await repo.get_request(APPROVER, REQUEST) == approved
    assert [item["action"] for item in (await repo.notifications(APPROVER))["notifications"]] == ["requested", "approved"]


@pytest.mark.asyncio
async def test_reopened_source_invalidates_signature_but_does_not_prevent_own_revocation(tasks):
    repo, project, run, archived, receipt, approved = await signed(tasks)
    original = await repo.get_approval("owner", project, run["id"], SIGNATURE)
    task_repo = tasks[0]
    task = await task_repo.get_task("owner", TASK)
    await task_repo.reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_SOURCE_CHANGED"))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "stale"
    tasks[5]["ms"] += 120_000
    revoked = await repo.decide(APPROVER, REQUEST, REVOKE, signature(approved, action="revoked", previous=1, view_id=None, note="SYNTHETIC_REVOCATION"))
    assert revoked["status"] == "revoked" and revoked["revision"] == 3
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "revoked"
    assert await repo.get_approval("owner", project, run["id"], SIGNATURE) == original
    assert await repo.get_assessment("owner", project, run["id"], archived["id"]) == archived
    assert (await repo.get_approval("owner", project, run["id"], REVOKE))["recorded_by"] == APPROVER


@pytest.mark.asyncio
async def test_owner_cancels_pending_but_cannot_revoke_the_approver(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    with pytest.raises(Conflict):
        await repo.cancel(APPROVER, REQUEST, "8" * 32, cmd(receipt))
    cancelled = await repo.cancel("owner", REQUEST, "8" * 32, cmd(receipt))
    assert cancelled["status"] == "cancelled" and cancelled["revision"] == 2
    with pytest.raises(Conflict):
        await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(cancelled))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "cancelled"
    assert await repo.get_operation("owner", REQUEST, "8" * 32) == cancelled


@pytest.mark.asyncio
async def test_same_operation_has_an_immutable_receipt_and_different_payload_conflicts(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    first = await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    assert await repo.get_operation(APPROVER, REQUEST, SIGNATURE) == first
    assert await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt)) == first
    with pytest.raises(Conflict):
        await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt, note="different"))
    assert (await repo.notifications(APPROVER))["notifications"][-1]["action"] == "approved"


@pytest.mark.asyncio
async def test_signed_and_owner_recorded_history_share_a_verified_chain_without_promoting_legacy(tasks):
    repo, project, run, archived, _, receipt = await pending(tasks)
    legacy_payload = ApprovalCreate(assessment_id=archived["id"], assessment_hash=archived["assessment_hash"], approver_id=APPROVER, decision="approved", expected_previous_revision=0, confirmed=True)
    legacy = await repo.create_approval("owner", project, run["id"], "7" * 32, legacy_payload)
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "pending"
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt, previous=1))
    assert (await repo.verify_approval_chain("owner", project, run["id"]))["status"] == "verified"
    assert await repo.get_approval("owner", project, run["id"], "7" * 32) == legacy
    assert await repo.create_approval("owner", project, run["id"], "7" * 32, legacy_payload) == legacy


@pytest.mark.asyncio
async def test_v2_signature_prevents_new_legacy_decision_from_diverging_run_projection(tasks):
    repo, project, run, archived, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))

    with pytest.raises(Conflict):
        await repo.create_approval(
            "owner",
            project,
            run["id"],
            "7" * 32,
            ApprovalCreate(
                assessment_id=archived["id"],
                assessment_hash=archived["assessment_hash"],
                approver_id=APPROVER,
                decision="revoked",
                expected_previous_revision=1,
                note="SYNTHETIC_LEGACY_REVOCATION",
                confirmed=True,
            ),
        )

    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "effective"
    latest = await repo.list_project_approvals("owner", project)
    assert len(latest) == 1
    assert latest[0]["id"] == SIGNATURE and latest[0]["decision"] == "approved"
    assert (await repo.approval_signoff_progress("owner", project, run["id"]))["latest_decision"] == "approved"


@pytest.mark.asyncio
async def test_concurrent_v1_and_v2_appends_share_run_revision_and_lock(tasks):
    repo, project, run, archived, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    legacy = ApprovalCreate(
        assessment_id=archived["id"],
        assessment_hash=archived["assessment_hash"],
        approver_id=APPROVER,
        decision="approved",
        expected_previous_revision=0,
        confirmed=True,
    )

    results = await asyncio.gather(
        repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt)),
        repo.create_approval("owner", project, run["id"], "8" * 32, legacy),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Conflict) for result in results) == 1
    async with repo.sf() as session:
        approvals = (await session.execute(select(t.run_approvals).where(t.run_approvals.c.run_id == run["id"]))).mappings().all()
    assert len(approvals) == 1 and approvals[0]["revision"] == 1
    assert (await repo.verify_approval_chain("owner", project, run["id"]))["status"] == "verified"
    latest = await repo.list_project_approvals("owner", project)
    assert latest[0]["decision"] == approvals[0]["decision"]


@pytest.mark.asyncio
async def test_newer_authenticated_decision_supersedes_older_signature_for_same_approver(tasks):
    repo, project, run, _, first, approved = await signed(tasks)
    definition = await repo.get_request(APPROVER, REQUEST)
    payload = ApprovalRequestCreate(assessment_id=definition["assessment_id"], assessment_hash=definition["assessment_hash"], approver_id=APPROVER, expires_at_ms=definition["expires_at_ms"], share_summary=True, confirmed=True)
    other_id, other_view, other_operation = [char * 32 for char in "678"]
    other = await repo.create_request("owner", project, run["id"], other_id, payload)
    await repo.open_summary(APPROVER, other_id, other_view, cmd(other))
    await repo.decide(APPROVER, other_id, other_operation, signature(other, previous=1, view_id=other_view))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "superseded"
    assert (await repo.effectiveness(APPROVER, other_id))["status"] == "effective"
    # Revoking one's older signature is still allowed, and becomes the latest
    # authenticated decision for this same signer and assessment.
    await repo.decide(APPROVER, REQUEST, REVOKE, signature(approved, action="revoked", previous=2, view_id=None, note="SYNTHETIC_REVOCATION"))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "revoked"
    assert (await repo.effectiveness(APPROVER, other_id))["status"] == "superseded"


@pytest.mark.asyncio
async def test_newer_assessment_revision_invalidates_signature_even_with_identical_summary(tasks):
    from app.evaluation.qa_assessments import AssessmentCreate

    repo, project, run, assessment, _, _ = await signed(tasks)
    await repo.create_assessment("owner", project, run["id"], "6" * 32, AssessmentCreate(summary_hash=assessment["assessment"]["summary_hash"], expected_previous_revision=1, confirmed=True))
    assert (await repo.effectiveness(APPROVER, REQUEST))["status"] == "stale"


@pytest.mark.asyncio
async def test_sign_and_cancel_race_produces_one_transition_and_one_notification(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    results = await asyncio.gather(repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt)), repo.cancel("owner", REQUEST, "8" * 32, cmd(receipt)), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Conflict) for result in results) == 1
    assert len((await repo.notifications(APPROVER))["notifications"]) == 2


@pytest.mark.asyncio
async def test_request_or_audit_corruption_never_becomes_effective(tasks):
    repo, _, _, _, _, _ = await signed(tasks)
    async with repo.sf.begin() as session:
        await session.execute(update(t.approval_request_events).where(t.approval_request_events.c.action == "approved").values(actor="owner"))
    with pytest.raises(RequestProtectionError):
        await repo.get_request(APPROVER, REQUEST)
    with pytest.raises(RequestProtectionError):
        await repo.effectiveness(APPROVER, REQUEST)


@pytest.mark.asyncio
async def test_notification_failure_rolls_back_the_signature_and_request_revision(tasks):
    repo, _, _, _, _, receipt = await pending(tasks)
    await repo.open_summary(APPROVER, REQUEST, VIEW, cmd(receipt))
    engine = repo.sf.kw["bind"]

    def reject_event(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO evaluation_approval_request_events"):
            raise OperationalError("synthetic", {}, RuntimeError("SYNTHETIC_FAILURE"))

    event.listen(engine.sync_engine, "before_cursor_execute", reject_event)
    try:
        with pytest.raises(JournalWriteUnconfirmed):
            await repo.decide(APPROVER, REQUEST, SIGNATURE, signature(receipt))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", reject_event)
    assert (await repo.get_request(APPROVER, REQUEST))["revision"] == 1
    async with repo.sf() as session:
        assert (await session.execute(select(t.run_approvals))).all() == []
        assert (await session.execute(select(t.approval_audit))).all() == []


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"share_summary": False}, {"approver_id": "junk"}, {"recorded_by": APPROVER}, {"expires_at_ms": True}])
def test_request_dto_rejects_forged_identity_and_confirmation(changes):
    payload = dict(assessment_id="c" * 32, assessment_hash="a" * 64, approver_id=APPROVER, expires_at_ms=100_000, share_summary=True, confirmed=True)
    payload.update(changes)
    with pytest.raises(ValidationError):
        ApprovalRequestCreate(**payload)
