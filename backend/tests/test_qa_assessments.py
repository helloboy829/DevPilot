"""All frozen samples, independent decisions, no owner substitution or approval."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, update
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_qa_evidence import observation, review
from test_review_tasks import ARB, TASK, A, B, command, decision, submit
from test_review_tasks import tasks as tasks

from app.evaluation import tables as t
from app.evaluation.qa_assessments import AssessmentCreate, AssessmentRepository
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import TaskCreate, TaskReopen

ARCHIVE = "c" * 32


def assessments(evidence):
    return AssessmentRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=evidence.clock_ms)


async def complete(tasks, *, second_decision="pass"):
    repo, evidence, _, project, run, _, payload, task = tasks
    await submit(repo, A, task)
    await submit(repo, B, task)
    ticket = await evidence.record_dispatch("owner", project, run["id"], 2, body_bytes=30)
    await evidence.record_attempt("owner", project, run["id"], ticket, observation())
    case = await evidence.open_case("owner", project, run["id"], 2)
    task2 = "b" * 32
    await repo.create_task("owner", project, task2, TaskCreate(**{**payload.model_dump(), "ordinal": 2, "case_hash": case["case_hash"]}))
    for actor in (A, B):
        claimed = await repo.claim(actor, task2, command(await repo.get_task(actor, task2)))
        await repo.open_task(actor, task2)
        await repo.submit_decision(actor, task2, decision(claimed, second_decision))
    return assessments(evidence)


def payload(summary, revision=0):
    return AssessmentCreate(summary_hash=summary["summary_hash"], expected_previous_revision=revision, confirmed=True)


@pytest.mark.asyncio
async def test_owner_votes_never_substitute_and_missing_tasks_keep_all_samples(tasks):
    _, evidence, _, project, run, _, _, _ = tasks
    case = await evidence.open_case("owner", project, run["id"], 1)
    await evidence.review_case("owner", project, run["id"], 1, review(case))
    result = await assessments(evidence).get_preview("owner", project, run["id"])
    assert result["schema"] == "qa-independent-assessment-preview.v1"
    assert result["counts"] == {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 2}
    assert result["human_pass_rate"] == {"numerator": 0, "denominator": 2, "value": 0}
    assert result["readiness"] == "provisional" and result["acceptance"] == "not_approved"
    assert "independent_review_incomplete" in result["blockers"]
    assert not any(x in json.dumps(result) for x in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_INDEPENDENT_NOTE", A, B, "encrypted_payload"))


@pytest.mark.asyncio
async def test_complete_independent_results_do_not_change_legacy_self_review(tasks):
    _, evidence, _, project, run, _, _, _ = tasks
    repo = await complete(tasks, second_decision="fail")
    result = await repo.get_preview("owner", project, run["id"])
    assert result["counts"] == {"pass": 1, "fail": 1, "uncertain": 0, "unreviewed": 0}
    assert result["readiness"] == "review_complete" and result["blockers"] == []
    assert result["human_pass_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    legacy = SummaryRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection)
    assert (await legacy.get_summary("owner", project, run["id"]))["counts"]["unreviewed"] == 2


@pytest.mark.asyncio
async def test_reopen_invalidates_current_preview_not_stored_assessment(tasks):
    task_repo, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    summary = await repo.get_preview("owner", project, run["id"])
    document = await repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary))
    assert document["revision"] == 1 and document["assessment"]["counts"]["pass"] == 2
    assert await repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary)) == document
    task = await task_repo.get_task("owner", TASK)
    await task_repo.reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_REOPEN"))
    current = await repo.get_preview("owner", project, run["id"])
    assert current["summary_hash"] != summary["summary_hash"] and current["counts"]["unreviewed"] == 1
    assert await repo.get_assessment("owner", project, run["id"], ARCHIVE) == document
    with pytest.raises(Conflict):
        await repo.create_assessment("owner", project, run["id"], "d" * 32, payload(summary, 1))
    revised = await repo.create_assessment("owner", project, run["id"], "d" * 32, payload(current, 1))
    assert revised["revision"] == 2 and revised["assessment"]["readiness"] == "provisional"
    with pytest.raises(Conflict):
        await repo.create_assessment("owner", project, run["id"], "e" * 32, payload(current, 1))
    assert len(await repo.list_assessments("owner", project, run["id"])) == 2
    async with engine.connect() as conn:
        stored = [dict(r) for r in (await conn.execute(select(t.run_assessments))).mappings()]
    assert not any(x in json.dumps(stored) for x in ("SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_INDEPENDENT_NOTE", "SYNTHETIC_REOPEN"))


@pytest.mark.asyncio
async def test_cancelled_or_conflicting_duplicate_tasks_cannot_hide_a_negative(tasks):
    task_repo, evidence, _, project, run, _, original, _ = tasks
    repo = await complete(tasks)
    other = "f" * 32
    await task_repo.create_task("owner", project, other, original)
    for actor in (A, B):
        claimed = await task_repo.claim(actor, other, command(await task_repo.get_task(actor, other)))
        await task_repo.open_task(actor, other)
        await task_repo.submit_decision(actor, other, decision(claimed, "fail"))
    result = await repo.get_preview("owner", project, run["id"])
    assert result["counts"] == {"pass": 1, "fail": 0, "uncertain": 1, "unreviewed": 0}
    assert "conflicting_independent_resolutions" in result["blockers"]
    await task_repo.cancel("owner", other, command(await task_repo.get_task("owner", other)))
    cancelled = await repo.get_preview("owner", project, run["id"])
    assert cancelled["counts"]["unreviewed"] == 1 and cancelled["readiness"] == "provisional"


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["decision", "resolution", "actor", "round", "output", "dispatch_gap", "gold"])
async def test_tampering_cannot_produce_a_verified_assessment(tasks, damage):
    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    if damage == "dispatch_gap":
        async with repo.sf() as session:
            source = await repo._assessment_snapshot(session, "owner", project, run["id"])
        source["dispatches"].pop()
        with pytest.raises(Conflict):
            repo._verify_assessment("owner", source)
        return
    async with engine.begin() as conn:
        if damage == "decision":
            await conn.execute(update(t.review_task_decisions).values(encrypted_payload="SYNTHETIC_BROKEN"))
        elif damage == "resolution":
            await conn.execute(update(t.review_task_resolutions).values(resolution_hash="0" * 64))
        elif damage == "actor":
            await conn.execute(update(t.review_task_assignments).where(t.review_task_assignments.c.role == "reviewer_1").values(actor_id="other"))
        elif damage == "round":
            await conn.execute(update(t.review_tasks).values(round=2))
        elif damage == "gold":
            await conn.execute(update(t.references).values(expected="SYNTHETIC_CHANGED_GOLD"))
        else:
            await conn.execute(update(t.output_evidence).values(encrypted_payload="SYNTHETIC_BROKEN"))
    with pytest.raises((Conflict, RequestProtectionError)):
        await repo.get_preview("owner", project, run["id"])


@pytest.mark.asyncio
async def test_owner_scope_and_archive_integrity(tasks):
    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    summary = await repo.get_preview("owner", project, run["id"])
    archived = await repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary))
    for actor in (A, "other"):
        with pytest.raises(NotFound):
            await repo.get_preview(actor, project, run["id"])
        with pytest.raises(NotFound):
            await repo.get_assessment(actor, project, run["id"], ARCHIVE)
    async with engine.begin() as conn:
        changed = {**archived, "revision": 99}
        await conn.execute(update(t.run_assessments).values(document=changed))
    with pytest.raises(RequestProtectionError):
        await repo.get_assessment("owner", project, run["id"], ARCHIVE)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preview", "archive"])
async def test_off_loop_verification_and_final_run_lock_fence_reopen(tasks, monkeypatch, operation):
    task_repo, evidence, _, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    summary = await repo.get_preview("owner", project, run["id"])
    original = repo._verify_assessment
    reached, release = asyncio.Event(), asyncio.Event()
    real = asyncio.to_thread

    async def delayed(function, *args, **kwargs):
        if function == original:
            reached.set()
            await release.wait()
        return await real(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", delayed)
    pending = asyncio.create_task(repo.get_preview("owner", project, run["id"]) if operation == "preview" else repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary)))
    await asyncio.wait_for(reached.wait(), 5)
    task = await task_repo.get_task("owner", TASK)
    await task_repo.reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_RACE"))
    release.set()
    with pytest.raises(Conflict):
        await pending
    assert await repo.list_assessments("owner", project, run["id"]) == []


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"expected_previous_revision": True}, {"expected_previous_revision": -1}, {"summary_hash": "x"}, {"counts": {"pass": 99}}])
def test_strict_assessment_create_requires_viewed_hash_and_explicit_confirmation(changes):
    with pytest.raises(ValidationError):
        AssessmentCreate.model_validate({"summary_hash": "a" * 64, "expected_previous_revision": 0, "confirmed": True, **changes})


@pytest.mark.asyncio
async def test_uncertain_arbitration_remains_blocked_and_cannot_be_approval(tasks):
    task_repo, evidence, _, project, run, _, _, task = tasks
    await submit(task_repo, A, task, "pass")
    await submit(task_repo, B, task, "fail")
    claimed = await task_repo.claim(ARB, TASK, command(await task_repo.get_task(ARB, TASK)))
    await task_repo.open_task(ARB, TASK)
    await task_repo.submit_decision(ARB, TASK, decision(claimed, "uncertain"))
    result = await assessments(evidence).get_preview("owner", project, run["id"])
    assert result["counts"] == {"pass": 0, "fail": 0, "uncertain": 1, "unreviewed": 1}
    assert result["human_pass_rate"]["denominator"] == 2
    assert "uncertain" in result["blockers"] and result["acceptance"] == "not_approved"


@pytest.mark.asyncio
async def test_owner_review_changes_and_corruption_are_not_independent_sources(tasks):
    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    before = await repo.get_preview("owner", project, run["id"])
    case = await evidence.open_case("owner", project, run["id"], 1)
    await evidence.review_case("owner", project, run["id"], 1, review(case, decision="fail"))
    assert await repo.get_preview("owner", project, run["id"]) == before
    async with engine.begin() as conn:
        await conn.execute(update(t.case_reviews).values(encrypted_payload="SYNTHETIC_CORRUPT_OWNER_NOTE"))
    assert await repo.get_preview("owner", project, run["id"]) == before


@pytest.mark.asyncio
async def test_source_verification_is_once_off_loop_and_does_not_select_owner_notes(tasks, monkeypatch):
    import threading

    from app.evaluation import qa_evidence

    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    original, loop_thread, calls, sql = qa_evidence._verified_inputs, threading.get_ident(), [], []

    def verify(*args):
        assert threading.get_ident() != loop_thread
        calls.append(1)
        return original(*args)

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        sql.append(statement)

    monkeypatch.setattr(qa_evidence, "_verified_inputs", verify)
    event.listen(engine.sync_engine, "before_cursor_execute", record)
    try:
        result = await repo.get_preview("owner", project, run["id"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert calls == [1] and result["counts"]["pass"] == 2
    assert not any(t.case_reviews.name in statement for statement in sql)


@pytest.mark.asyncio
async def test_concurrent_appends_have_one_cas_winner_and_one_atomic_audit(tasks):
    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    summary = await repo.get_preview("owner", project, run["id"])
    results = await asyncio.gather(*(repo.create_assessment("owner", project, run["id"], key * 32, payload(summary)) for key in ("c", "d")), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, Conflict) for result in results) == 1
    async with engine.connect() as conn:
        assert len((await conn.execute(select(t.run_assessments))).all()) == 1
        assert len((await conn.execute(select(t.dispatch_audit).where(t.dispatch_audit.c.action == "independent_assessment_archived"))).all()) == 1


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_archive_and_revision(tasks, monkeypatch):
    _, evidence, engine, project, run, _, _, _ = tasks
    repo = await complete(tasks)
    summary = await repo.get_preview("owner", project, run["id"])
    original = repo._journal_event

    async def failed(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_AUDIT_FAILURE")

    monkeypatch.setattr(repo, "_journal_event", failed)
    with pytest.raises(RuntimeError, match="SYNTHETIC_AUDIT_FAILURE"):
        await repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary))
    assert await repo.list_assessments("owner", project, run["id"]) == []
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.dispatch_audit).where(t.dispatch_audit.c.action == "independent_assessment_archived"))).all()
    monkeypatch.setattr(repo, "_journal_event", original)
    assert (await repo.create_assessment("owner", project, run["id"], ARCHIVE, payload(summary)))["revision"] == 1


@pytest.mark.parametrize("threshold,expected", [(0, "met"), (5000, "met"), (5001, "not_met")])
@pytest.mark.asyncio
async def test_frozen_v2_criteria_use_integer_all_sample_counts_and_block_incomplete(captured, threshold, expected):
    from app.evaluation.dispatch_journal import JournalLimits
    from app.evaluation.plans import AcceptancePlanCreate

    evidence, _, project, plan, _, _, _ = captured
    repo = assessments(evidence)
    fields = {name: plan["definition"][name] for name in AcceptancePlanCreate.model_fields if name not in {"confirmed", "acceptance_criteria"}}
    fields.update(version_label="Synthetic criteria", confirmed=True, acceptance_criteria={"schema": "qa-effectiveness-criteria.v1", "version_label": "Synthetic", "min_pass_rate_bps": threshold})
    v2 = await repo.create_plan("owner", project, plan["component_id"], AcceptancePlanCreate.model_validate(fields))
    run = await repo.record_run("owner", project, v2["id"], v2["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    # No task/output yet: even threshold zero cannot turn missing evidence into met.
    initial = await repo.get_preview("owner", project, run["id"])
    assert initial["criteria_evaluation"]["status"] == "incomplete"
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
    result = await repo.get_preview("owner", project, run["id"])
    assert result["human_pass_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert result["criteria_evaluation"]["status"] == expected
    assert result["criteria_evaluation"]["approval"] == "not_approved"


@pytest.mark.asyncio
async def test_technical_failure_is_never_hidden_by_complete_negative_reviews(captured):
    evidence, _, project, _, run, ticket, _ = captured
    repo = assessments(evidence)
    await repo.record_attempt("owner", project, run["id"], ticket, observation(kind="http_error", http_status=500, body_bytes=0, output=None))
    ticket = await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=30)
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    for ordinal in (1, 2):
        case = await repo.open_case("owner", project, run["id"], ordinal)
        task_id = str(ordinal) * 32
        await repo.create_task("owner", project, task_id, TaskCreate(run_id=run["id"], ordinal=ordinal, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True))
        for actor in (A, B):
            claimed = await repo.claim(actor, task_id, command(await repo.get_task(actor, task_id)))
            await repo.open_task(actor, task_id)
            await repo.submit_decision(actor, task_id, decision(claimed, "fail"))
    result = await repo.get_preview("owner", project, run["id"])
    assert result["counts"]["fail"] == 2 and result["technical_counts"] == {"collected": 1, "other": 1}
    assert result["blockers"] == ["technical_incomplete"] and result["readiness"] == "provisional"


@pytest.mark.asyncio
async def test_performance_plans_cannot_be_independent_effectiveness_assessments(captured):
    from app.evaluation.dispatch_journal import JournalLimits
    from app.evaluation.plans import PlanCreate

    repo0, _, project, plan, _, _, _ = captured
    repo = assessments(repo0)
    definition = plan["definition"]
    fields = {name: definition[name] for name in PlanCreate.model_fields if name != "confirmed"}
    fields.update(version_label="Synthetic performance", confirmed=True, limits={**definition["limits"], "mode": "performance", "request_count": 4})
    perf = await repo.create_plan("owner", project, plan["component_id"], PlanCreate.model_validate(fields))
    run = await repo.record_run("owner", project, perf["id"], perf["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=516))
    with pytest.raises(Conflict):
        await repo.get_preview("owner", project, run["id"])
