"""Formal approval needs complete independent review and an explicit human decision."""

import asyncio
import json
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select, update
from test_dispatch_journal import prepared as prepared
from test_qa_assessments import assessments as assessments
from test_qa_assessments import complete as complete
from test_qa_assessments import payload as assessment_payload
from test_qa_evidence import captured as captured
from test_qa_evidence import observation
from test_review_tasks import ARB, TASK, A, B, TaskReopen, command, decision
from test_review_tasks import tasks as tasks

from app.evaluation import tables as t
from app.evaluation.qa_approvals import ApprovalCreate, ApprovalRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import TaskCreate

APPROVER = str(UUID(int=5))
APPROVAL = "b" * 32
ASSESSMENT = "c" * 32


def approvals(repo):
    return ApprovalRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)


def payload(document, *, approver=APPROVER, decision_value="approved", note=None, revision=0):
    values = {
        "assessment_id": document["id"],
        "assessment_hash": document["assessment_hash"],
        "expected_previous_revision": revision,
        "approver_id": approver,
        "decision": decision_value,
        "confirmed": True,
    }
    if note is not None:
        values["note"] = note
    return ApprovalCreate(**values)


async def archive(tasks, second_decision="pass"):
    repo = await complete(tasks, second_decision=second_decision)
    _, _, _, project, run, _, _, _ = tasks
    summary = await repo.get_preview("owner", project, run["id"])
    document = await repo.create_assessment("owner", project, run["id"], ASSESSMENT, assessment_payload(summary))
    return repo, project, run, document


@pytest.mark.asyncio
async def test_provisional_assessment_cannot_be_approved(tasks):
    _, evidence, _, project, run, _, _, _ = tasks
    repo = assessments(evidence)
    summary = await repo.get_preview("owner", project, run["id"])
    assert summary["readiness"] == "provisional"
    archived = await repo.create_assessment("owner", project, run["id"], ASSESSMENT, assessment_payload(summary))
    with pytest.raises(Conflict):
        await approvals(repo).create_approval("owner", project, run["id"], APPROVAL, payload(archived))
    with pytest.raises(NotFound):
        await approvals(repo).create_approval("owner", project, run["id"], "d" * 32, payload({**archived, "id": "d" * 32}))


@pytest.mark.asyncio
async def test_approved_decision_pins_exact_assessment_and_all_sample_counts(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    document = await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived, note="SYNTHETIC_APPROVAL_NOTE"))
    assert document["schema"] == "qa-run-formal-approval.v1" and document["scope"] == "formal_approval_decision"
    assert document["decision"] == "approved" and document["readiness"] == "review_complete"
    assert document["assessment"] == {"id": archived["id"], "revision": 1, "assessment_hash": archived["assessment_hash"], "summary_hash": archived["assessment"]["summary_hash"]}
    assert document["counts"] == {"pass": 2, "fail": 0, "uncertain": 0, "unreviewed": 0}
    assert document["human_pass_rate"] == {"numerator": 2, "denominator": 2, "value": 1.0}
    assert document["criteria"] == {"status": "not_defined", "approval": "not_approved"}
    assert document["approver_id"] == APPROVER and document["recorded_by"] == "owner"
    assert document["note"] == "SYNTHETIC_APPROVAL_NOTE"
    # Same ID and identical payload stays a receipt; never appends a second row.
    assert await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived, note="SYNTHETIC_APPROVAL_NOTE")) == document
    with pytest.raises(Conflict):
        await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived))
    with pytest.raises(Conflict):
        await unit.create_approval("owner", project, run["id"], "e" * 32, payload(archived))
    # Historical evidence is untouched by the decision.
    assert await repo.get_assessment("owner", project, run["id"], ASSESSMENT) == archived
    async with unit.sf() as session:
        audit = [dict(row) for row in (await session.execute(select(t.approval_audit))).mappings()]
        stored = json.dumps([dict(row) for row in (await session.execute(select(t.run_approvals))).mappings()], default=str)
    assert [(row["sequence"], row["actor"], row["action"]) for row in audit] == [(1, "owner", "approved")]
    assert not any(x in stored for x in ("SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_INDEPENDENT_NOTE"))


@pytest.mark.asyncio
async def test_separation_rejects_owner_and_every_independent_reviewer(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    for actor in (A, B, ARB):
        with pytest.raises(Conflict):
            await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived, approver=actor))
    async with unit.sf() as session:
        snapshot = await unit._approval_snapshot(session, "owner", project, run["id"], archived["id"])
    with pytest.raises(Conflict):
        unit._verify_approval_target(A, snapshot, payload(archived, approver=A))
    assert unit._verify_approval_target("other-owner", snapshot, payload(archived))["readiness"] == "review_complete"


@pytest.mark.asyncio
async def test_revocation_appends_revision_with_required_reason_and_audit(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    first = await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived))
    with pytest.raises(ValidationError):
        payload(archived, decision_value="revoked", revision=1)
    with pytest.raises(Conflict):
        await unit.create_approval("owner", project, run["id"], "e" * 32, payload(archived, decision_value="revoked", note="SYNTHETIC_REVOCATION", revision=0))
    revoked = await unit.create_approval("owner", project, run["id"], "e" * 32, payload(archived, decision_value="revoked", note="SYNTHETIC_REVOCATION", revision=1))
    assert revoked["revision"] == 2 and revoked["decision"] == "revoked" and revoked["note"] == "SYNTHETIC_REVOCATION"
    assert await unit.get_approval("owner", project, run["id"], APPROVAL) == first
    assert [row["revision"] for row in await unit.list_approvals("owner", project, run["id"])] == [2, 1]
    async with unit.sf() as session:
        audit = [dict(row) for row in (await session.execute(select(t.approval_audit).order_by(t.approval_audit.c.sequence))).mappings()]
    assert [(row["sequence"], row["action"], row["actor"]) for row in audit] == [(1, "approved", "owner"), (2, "revoked", "owner")]
    with pytest.raises(Conflict):
        await unit.create_approval("owner", project, run["id"], "f" * 32, payload(archived, revision=0))


@pytest.mark.asyncio
async def test_concurrent_first_approvals_serialize_to_one_revision(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    results = await asyncio.gather(
        *(unit.create_approval("owner", project, run["id"], key * 32, payload(archived)) for key in ("b", "d")),
        return_exceptions=True,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Conflict) for result in results) == 1
    async with unit.sf() as session:
        assert len((await session.execute(select(t.run_approvals))).all()) == 1
        assert len((await session.execute(select(t.approval_audit))).all()) == 1


@pytest.mark.asyncio
async def test_tampered_document_and_wrong_scope_are_rejected(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived))
    async with unit.sf.begin() as session:
        await session.execute(update(t.run_approvals).values(decision="revoked"))
    with pytest.raises(RequestProtectionError):
        await unit.get_approval("owner", project, run["id"], APPROVAL)
    with pytest.raises(NotFound):
        await unit.get_approval("other", project, run["id"], APPROVAL)
    with pytest.raises(NotFound):
        await unit.list_approvals("owner", "f" * 32, run["id"])
    with pytest.raises(NotFound):
        await unit.create_approval("owner", project, "f" * 32, APPROVAL, payload(archived))
    with pytest.raises(NotFound):
        await unit.create_approval("owner", project, run["id"], "not-an-approval", payload(archived))


@pytest.mark.parametrize("threshold,expected", [(5000, "met"), (5001, "not_met")])
@pytest.mark.asyncio
async def test_frozen_threshold_never_substitutes_for_or_blocks_a_missing_decision(captured, threshold, expected):
    from app.evaluation.dispatch_journal import JournalLimits
    from app.evaluation.plans import AcceptancePlanCreate

    evidence, _, project, plan, _, _, _ = captured
    repo = assessments(evidence)
    fields = {name: plan["definition"][name] for name in AcceptancePlanCreate.model_fields if name not in {"confirmed", "acceptance_criteria"}}
    fields.update(version_label="Synthetic criteria", confirmed=True, acceptance_criteria={"schema": "qa-effectiveness-criteria.v1", "version_label": "Synthetic", "min_pass_rate_bps": threshold})
    v2 = await repo.create_plan("owner", project, plan["component_id"], AcceptancePlanCreate.model_validate(fields))
    run = await repo.record_run("owner", project, v2["id"], v2["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    for ordinal, outcome in ((1, "pass"), (2, "fail")):
        ticket = await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=30)
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
        case = await repo.open_case("owner", project, run["id"], ordinal)
        task_id = str(ordinal) * 32
        await repo.create_task("owner", project, task_id, TaskCreate(run_id=run["id"], ordinal=ordinal, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True))
        for actor in (A, B):
            claimed = await repo.claim(actor, task_id, command(await repo.get_task(actor, task_id)))
            await repo.open_task(actor, task_id)
            await repo.submit_decision(actor, task_id, decision(claimed, outcome))
    summary = await repo.get_preview("owner", project, run["id"])
    assert summary["criteria_evaluation"]["status"] == expected
    assert summary["criteria_evaluation"]["approval"] == "not_approved"
    archived = await repo.create_assessment("owner", project, run["id"], ASSESSMENT, assessment_payload(summary))
    unit = approvals(repo)
    target = payload(archived, approver=str(UUID(int=5 + threshold)))
    preview = await unit.preview_approval("owner", project, run["id"], archived["id"], target.approver_id)
    assert preview["criteria"]["status"] == expected
    assert preview["eligible"] is (expected == "met")
    if expected != "met":
        assert "criteria_not_met" in preview["blockers"]
    if expected == "met":
        document = await unit.create_approval("owner", project, run["id"], APPROVAL, target)
        assert document["criteria"]["status"] == "met" and document["decision"] == "approved"
    else:
        with pytest.raises(Conflict):
            await unit.create_approval("owner", project, run["id"], APPROVAL, target)
        assert await unit.list_approvals("owner", project, run["id"]) == []


@pytest.mark.asyncio
async def test_unknown_run_or_assessment_requires_original_identifiers(tasks):
    repo, project, _, archived = await archive(tasks)
    unit = approvals(repo)
    with pytest.raises(NotFound):
        await unit.create_approval("owner", project, "run-does-not-exist", APPROVAL, payload(archived))
    with pytest.raises(NotFound):
        await unit.create_approval("owner", project, "run-does-not-exist", "not-an-approval", payload(archived))
    with pytest.raises(Conflict):
        await unit.create_approval("owner", project, tasks[4]["id"], APPROVAL, payload({**archived, "assessment_hash": "f" * 64}))


@pytest.mark.asyncio
async def test_approval_audit_is_ordered_and_metadata_only(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    first = await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived, note="SYNTHETIC_APPROVAL_NOTE"))
    second = await unit.create_approval("owner", project, run["id"], "e" * 32, payload(archived, decision_value="revoked", note="SYNTHETIC_REVOCATION", revision=1))
    events = await unit.list_approval_audit("owner", project, run["id"])
    assert [(e["sequence"], e["approval_id"], e["revision"], e["action"], e["actor"]) for e in events] == [(1, APPROVAL, 1, "approved", "owner"), (2, "e" * 32, 2, "revoked", "owner")]
    assert [e["subject_hash"] for e in events] == [first["approval_hash"], second["approval_hash"]]
    assert all("document" not in e and "note" not in e for e in events)
    with pytest.raises(NotFound):
        await unit.list_approval_audit("owner", project, "f" * 32)
    with pytest.raises(NotFound):
        await unit.list_approval_audit("other", project, run["id"])


@pytest.mark.asyncio
async def test_revocation_stays_available_after_current_review_is_reopened(tasks):
    task_repo, _, _, project, run, _, _, _ = tasks
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    await unit.create_approval("owner", project, run["id"], APPROVAL, payload(archived))
    task = await task_repo.get_task("owner", TASK)
    await task_repo.reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_REOPEN"))
    assert (await repo.get_preview("owner", project, run["id"]))["readiness"] == "provisional"
    revoked = await unit.create_approval("owner", project, run["id"], "e" * 32, payload(archived, decision_value="revoked", note="SYNTHETIC_REVOCATION", revision=1))
    assert revoked["revision"] == 2 and revoked["decision"] == "revoked"
    assert (await unit.get_approval("owner", project, run["id"], APPROVAL))["decision"] == "approved"


@pytest.mark.asyncio
async def test_preflight_reports_eligibility_and_separation_without_writes(tasks):
    repo, project, run, archived = await archive(tasks)
    unit = approvals(repo)
    preview = await unit.preview_approval("owner", project, run["id"], archived["id"], APPROVER)
    assert preview["schema"] == "qa-approval-preflight.v1"
    assert preview["eligible"] is True and preview["blockers"] == []
    assert preview["separation"] == {"approver_not_owner": True, "approver_not_review_actor": True}
    assert preview["readiness"] == "review_complete" and preview["criteria"]["status"] == "not_defined"
    assert preview["approval"] == "not_recorded"
    async with unit.sf() as session:
        assert (await session.execute(select(t.run_approvals))).all() == []
        assert (await session.execute(select(t.approval_audit))).all() == []
    for actor in (A, B, ARB):
        blocked = await unit.preview_approval("owner", project, run["id"], archived["id"], actor)
        assert blocked["eligible"] is False and "approver_is_review_actor" in blocked["blockers"]
        assert blocked["separation"]["approver_not_review_actor"] is False
    with pytest.raises(ValueError):
        await unit.preview_approval("owner", project, run["id"], archived["id"], "not-a-uuid")
    with pytest.raises(NotFound):
        await unit.preview_approval("owner", project, run["id"], "f" * 32, APPROVER)


@pytest.mark.asyncio
async def test_preflight_marks_incomplete_review_ineligible(tasks):
    _, evidence, _, project, run, _, _, _ = tasks
    repo = assessments(evidence)
    summary = await repo.get_preview("owner", project, run["id"])
    archived = await repo.create_assessment("owner", project, run["id"], ASSESSMENT, assessment_payload(summary))
    preview = await approvals(repo).preview_approval("owner", project, run["id"], archived["id"], APPROVER)
    assert preview["eligible"] is False and preview["readiness"] == "provisional"
    assert "independent_review_incomplete" in preview["blockers"]
