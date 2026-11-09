"""Independent humans, frozen grants, blind decisions and immutable resolutions."""

import asyncio
import json
from uuid import UUID

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import OperationalError
from test_dispatch_journal import prepared as prepared
from test_qa_evidence import captured as captured
from test_qa_evidence import observation, review

from app.evaluation import tables as t
from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCommand, TaskCreate, TaskDecision, TaskReopen

A, B, ARB, OTHER = [str(UUID(int=i)) for i in range(2, 6)]
TASK = "a" * 32


def command(task):
    return TaskCommand(expected_revision=task["revision"], confirmed=True)


def decision(task, value="pass", note="SYNTHETIC_INDEPENDENT_NOTE"):
    return TaskDecision(expected_revision=task["revision"], subject_hash=task["subject_hash"], decision=value, note=note, confirmed=True)


@pytest_asyncio.fixture
async def tasks(captured):
    evidence, engine, project, _, run, ticket, clock = captured
    await evidence.record_attempt("owner", project, run["id"], ticket, observation())
    case = await evidence.open_case("owner", project, run["id"], 1)
    repo = ReviewTaskRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=lambda: clock["ms"])
    payload = TaskCreate(run_id=run["id"], ordinal=1, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True)
    task = await repo.create_task("owner", project, TASK, payload)
    yield repo, evidence, engine, project, run, clock, payload, task


async def submit(repo, actor, task, value="pass", note="SYNTHETIC_INDEPENDENT_NOTE"):
    task = await repo.claim(actor, TASK, command(await repo.get_task(actor, TASK)))
    opened = await repo.open_task(actor, TASK)
    assert opened["input"] == "SYNTHETIC_INPUT" and opened["expected"] == "SYNTHETIC_GOLD"
    assert opened["output"] == "SYNTHETIC_OUTPUT"
    assert "reviews" not in opened and "review_revision" not in opened
    return await repo.submit_decision(actor, TASK, decision(task, value, note))


@pytest.mark.asyncio
async def test_two_independent_blind_humans_resolve_without_approving_or_rewriting_owner(tasks):
    repo, evidence, engine, project, run, _, payload, task = tasks
    assert task["status"] == "queued" and task["round"] == 1
    assert await repo.create_task("owner", project, TASK, payload) == task
    with pytest.raises(Conflict):
        await repo.claim("owner", TASK, command(task))
    with pytest.raises(Conflict):
        await repo.claim(ARB, TASK, command(await repo.get_task(ARB, TASK)))
    for actor in (A, B):
        listing = await repo.inbox(actor)
        assert len(listing["tasks"]) == 1
        assert not any(s in json.dumps(listing) for s in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "encrypted_payload", "decision", ARB))
    first = await submit(repo, A, task)
    assert first["status"] == "in_review"
    blinded = await repo.get_task(B, TASK)
    assert "assignments" not in blinded and "resolution" not in blinded
    with pytest.raises(Conflict):
        await repo.get_result("owner", TASK)
    # Owner self-review is a separate record, not a vote and not a source mutation.
    own = await evidence.open_case("owner", project, run["id"], 1)
    await evidence.review_case("owner", project, run["id"], 1, review(own, decision="fail", note="SYNTHETIC_OWNER_NOTE"))
    final = await submit(repo, B, blinded)
    assert final["status"] == "resolved"
    result = await repo.get_result("owner", TASK)
    assert result["resolution"]["outcome"] == "pass"
    assert result["resolution"]["approval"] == "not_approved"
    assert [d["actor"] for d in result["decisions"]] == [A, B]
    assert all(d["note"] == "SYNTHETIC_INDEPENDENT_NOTE" for d in result["decisions"])
    assert (await evidence.list_cases("owner", project, run["id"]))["counts"]["fail"] == 1
    with pytest.raises(NotFound):
        await repo.get_result(A, TASK)
    async with engine.connect() as conn:
        rows = [dict(r) for r in (await conn.execute(select(t.review_task_decisions))).mappings()]
        assert len(rows) == 2 and "SYNTHETIC_INDEPENDENT_NOTE" not in json.dumps(rows)
        assert len((await conn.execute(select(t.review_task_resolutions))).all()) == 1


@pytest.mark.asyncio
async def test_disagreement_arbitration_and_explicit_reopen_keep_old_round_immutable(tasks):
    repo, _, engine, _, _, _, _, task = tasks
    await submit(repo, A, task, "pass", "SYNTHETIC_A_NOTE")
    escalated = await submit(repo, B, task, "fail", "SYNTHETIC_B_NOTE")
    assert escalated["status"] == "escalated"
    claimed = await repo.claim(ARB, TASK, command(await repo.get_task(ARB, TASK)))
    opened = await repo.open_task(ARB, TASK)
    assert [d["note"] for d in opened["prior_decisions"]] == ["SYNTHETIC_A_NOTE", "SYNTHETIC_B_NOTE"]
    resolved = await repo.submit_decision(ARB, TASK, decision(claimed, "fail", "SYNTHETIC_ARBITRATION_NOTE"))
    assert resolved["status"] == "resolved"
    old = await repo.get_result("owner", TASK)
    assert old["resolution"]["basis"] == "arbitrated" and old["resolution"]["outcome"] == "fail"
    reopened = await repo.reopen("owner", TASK, TaskReopen(expected_revision=resolved["revision"], confirmed=True, reason="SYNTHETIC_REOPEN_REASON"))
    assert reopened["round"] == 2 and reopened["status"] == "queued"
    assert await repo.get_result("owner", TASK, round_number=1) == old
    for actor in (A, B):
        await submit(repo, actor, reopened)
    assert (await repo.get_result("owner", TASK))["resolution"]["outcome"] == "pass"
    async with engine.connect() as conn:
        assert len((await conn.execute(select(t.review_task_decisions))).all()) == 5
        assert len((await conn.execute(select(t.review_task_resolutions))).all()) == 3
        audit = [dict(r) for r in (await conn.execute(select(t.review_task_audit))).mappings()]
        assert "SYNTHETIC_REOPEN_REASON" not in json.dumps(audit)
        assert any(r["actor"] == ARB and r["action"] == "decision_submitted" for r in audit)


@pytest.mark.asyncio
async def test_claim_lease_view_receipt_stale_writes_and_cancellation_revoke_access(tasks):
    repo, _, _, _, _, clock, _, task = tasks
    claimed = await repo.claim(A, TASK, command(task))
    with pytest.raises(Conflict):
        await repo.submit_decision(A, TASK, decision(claimed))
    await repo.open_task(A, TASK)
    # Another claim makes an old confirmation stale; do not silently retry it.
    await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
    with pytest.raises(Conflict):
        await repo.submit_decision(A, TASK, decision(claimed))
    current = await repo.get_task(A, TASK)
    await repo.open_task(A, TASK)
    clock["ms"] += 1_800_001
    with pytest.raises(Conflict):
        await repo.submit_decision(A, TASK, decision(current))
    reclaimed = await repo.claim(A, TASK, command(await repo.get_task(A, TASK)))
    assert reclaimed["revision"] > claimed["revision"]
    with pytest.raises(Conflict):
        await repo.submit_decision(A, TASK, decision(reclaimed))
    await repo.open_task(A, TASK)
    await repo.release(A, TASK, command(reclaimed))
    with pytest.raises(Conflict):
        await repo.open_task(A, TASK)
    cancelled = await repo.cancel("owner", TASK, command(await repo.get_task("owner", TASK)))
    assert cancelled["status"] == "cancelled"
    with pytest.raises(Conflict):
        await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
    with pytest.raises(Conflict):
        await repo.open_task(B, TASK)


@pytest.mark.asyncio
async def test_metadata_never_selects_sensitive_tables_or_ciphertext_and_unknown_actor_gets_404(tasks):
    repo, _, engine, _, _, _, _, _ = tasks
    statements = []

    def capture(_c, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await repo.inbox(A)
        await repo.get_task(A, TASK)
        with pytest.raises(NotFound):
            await repo.get_task(OTHER, TASK)
        with pytest.raises(NotFound):
            await repo.open_task(OTHER, TASK)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    joined = " ".join(statements)
    for forbidden in ("encrypted_payload", "evaluation_qa_samples", "evaluation_qa_references", "evaluation_output_evidence", "evaluation_case_reviews"):
        assert forbidden not in joined


@pytest.mark.parametrize("field", ["output", "gold", "decision", "grant"])
@pytest.mark.asyncio
async def test_tampering_rejects_without_new_decisions(tasks, field):
    repo, _, engine, _, _, _, _, task = tasks
    if field == "decision":
        await submit(repo, A, task)
        async with engine.begin() as conn:
            await conn.execute(update(t.review_task_decisions).values(decision="fail"))
        await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
        await repo.open_task(B, TASK)
        with pytest.raises((Conflict, ValueError)):
            await repo.submit_decision(B, TASK, decision(await repo.get_task(B, TASK)))
        return
    if field == "grant":
        async with engine.begin() as conn:
            await conn.execute(update(t.review_task_assignments).where(t.review_task_assignments.c.actor_id == A).values(actor_id=OTHER))
        with pytest.raises((Conflict, NotFound)):
            await repo.open_task(OTHER, TASK)
        return
    await repo.claim(A, TASK, command(task))
    async with engine.begin() as conn:
        if field == "output":
            await conn.execute(update(t.output_evidence).values(encrypted_payload="SYNTHETIC_TAMPER"))
        else:
            await conn.execute(update(t.references).values(expected="SYNTHETIC_TAMPER"))
    with pytest.raises((Conflict, RequestProtectionError)):
        await repo.open_task(A, TASK)
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.review_task_decisions))).all()


@pytest.mark.asyncio
async def test_simultaneous_claims_have_one_cas_winner_and_atomic_audit(tasks):
    repo, _, engine, _, _, _, _, task = tasks
    results = await asyncio.gather(repo.claim(A, TASK, command(task)), repo.claim(B, TASK, command(task)), return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, Conflict) for r in results) == 1
    async with engine.connect() as conn:
        assert len((await conn.execute(select(t.review_task_audit).where(t.review_task_audit.c.action == "claimed"))).all()) == 1


@pytest.mark.parametrize("change", [{"confirmed": 1}, {"share_reference": 1}, {"reviewer_ids": [A, A]}, {"arbitrator_id": A}, {"reviewer_ids": [A]}, {"ordinal": True}, {"case_hash": "wrong"}, {"reviewer_ids": ["internal", B]}])
def test_task_contract_fails_closed(change):
    payload = dict(run_id="run", ordinal=1, case_hash="a" * 64, reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True)
    with pytest.raises(ValidationError):
        TaskCreate.model_validate({**payload, **change})


@pytest.mark.asyncio
async def test_owner_cannot_assign_themself_or_change_same_id_definition(tasks):
    repo, _, _, project, _, _, payload, _ = tasks
    with pytest.raises(Conflict):
        await repo.create_task(A, project, "b" * 32, payload)
    with pytest.raises(Conflict):
        await repo.create_task("owner", project, TASK, payload.model_copy(update={"arbitrator_id": OTHER}))


@pytest.mark.parametrize("kind", ["http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"])
@pytest.mark.asyncio
async def test_technical_failure_and_missing_output_never_become_pass(captured, kind):
    evidence, _, project, _, run, ticket, clock = captured
    await evidence.record_attempt("owner", project, run["id"], ticket, AttemptObservation(kind, None if kind in {"policy_rejected", "delivery_unknown"} else 500 if kind == "http_error" else 200, 0, 1.0, None))
    case = await evidence.open_case("owner", project, run["id"], 1)
    repo = ReviewTaskRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=lambda: clock["ms"])
    payload = TaskCreate(run_id=run["id"], ordinal=1, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True)
    task = await repo.create_task("owner", project, TASK, payload)
    for actor in (A, B):
        task = await repo.claim(actor, TASK, command(await repo.get_task(actor, TASK)))
        opened = await repo.open_task(actor, TASK)
        assert opened["output"] is None
        with pytest.raises(Conflict):
            await repo.submit_decision(actor, TASK, decision(task))
        await repo.submit_decision(actor, TASK, decision(task, "uncertain"))
    assert (await repo.get_task("owner", TASK))["status"] == "escalated"
    result = await repo.get_result("owner", TASK)
    assert result["resolution"]["outcome"] == "uncertain"
    arb = await repo.claim(ARB, TASK, command(await repo.get_task(ARB, TASK)))
    await repo.open_task(ARB, TASK)
    with pytest.raises(Conflict):
        await repo.submit_decision(ARB, TASK, decision(arb))


@pytest.mark.asyncio
async def test_blind_sensitive_open_never_reads_any_human_decision_table(tasks):
    repo, _, engine, _, _, _, _, task = tasks
    await submit(repo, A, task, "fail")
    await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
    statements = []

    def capture(_c, _cursor, sql, _parameters, _context, _many):
        statements.append(sql.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        opened = await repo.open_task(B, TASK)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert opened["prior_decisions"] == []
    assert "evaluation_case_reviews" not in " ".join(statements)
    assert "evaluation_review_task_decisions" not in " ".join(statements)
    assert "evaluation_review_task_resolutions" not in " ".join(statements)
    assert "SYNTHETIC_INDEPENDENT_NOTE" not in json.dumps(opened)


@pytest.mark.asyncio
async def test_simultaneous_decisions_preserve_both_via_explicit_refresh_and_review(tasks):
    repo, _, engine, _, _, _, _, task = tasks
    await repo.claim(A, TASK, command(task))
    current = await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
    await repo.open_task(A, TASK)
    await repo.open_task(B, TASK)
    results = await asyncio.gather(repo.submit_decision(A, TASK, decision(current)), repo.submit_decision(B, TASK, decision(current)), return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, Conflict) for r in results) == 1
    loser = (A, B)[next(i for i, r in enumerate(results) if isinstance(r, Conflict))]
    updated = await repo.get_task(loser, TASK)
    with pytest.raises(Conflict):
        await repo.submit_decision(loser, TASK, decision(updated))
    await repo.open_task(loser, TASK)
    await repo.submit_decision(loser, TASK, decision(updated))
    assert (await repo.get_result("owner", TASK))["resolution"]["outcome"] == "pass"
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.review_task_decisions))).scalar_one() == 2


@pytest.mark.parametrize("operation", ["open", "submit", "result", "reopen"])
@pytest.mark.asyncio
async def test_offloop_verification_rechecks_revoked_state_before_return_or_append(tasks, monkeypatch, operation):
    repo, _, engine, _, _, _, _, task = tasks
    if operation in {"result", "reopen"}:
        await submit(repo, A, task)
        await submit(repo, B, task)
        task = await repo.get_task("owner", TASK)
    else:
        task = await repo.claim(A, TASK, command(task))
        if operation == "submit":
            await repo.open_task(A, TASK)
    original = asyncio.to_thread
    changed = False

    async def revoked_after_crypto(function, *args, **kwargs):
        nonlocal changed
        value = await original(function, *args, **kwargs)
        if not changed and getattr(function, "__name__", "") == "_verify_materials":
            changed = True
            await repo.cancel("owner", TASK, command(await repo.get_task("owner", TASK)))
        return value

    monkeypatch.setattr(asyncio, "to_thread", revoked_after_crypto)
    with pytest.raises(Conflict):
        if operation == "open":
            await repo.open_task(A, TASK)
        elif operation == "submit":
            await repo.submit_decision(A, TASK, decision(task))
        elif operation == "result":
            await repo.get_result("owner", TASK)
        else:
            await repo.reopen("owner", TASK, TaskReopen(expected_revision=task["revision"], confirmed=True, reason="Synthetic reopen"))
    assert changed
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.review_task_decisions))).scalar_one() == (2 if operation in {"result", "reopen"} else 0)


@pytest.mark.parametrize("operation", ["claim", "open", "submit", "cancel", "reopen"])
@pytest.mark.asyncio
async def test_audit_failure_rolls_back_task_and_decision_writes_without_private_error(tasks, monkeypatch, operation):
    repo, _, engine, _, _, _, _, task = tasks
    if operation == "reopen":
        await submit(repo, A, task)
        await submit(repo, B, task)
        task = await repo.get_task("owner", TASK)
    elif operation in {"open", "submit"}:
        task = await repo.claim(A, TASK, command(task))
        if operation == "submit":
            await repo.open_task(A, TASK)
    tables = [t.review_tasks, t.review_task_assignments, t.review_task_decisions, t.review_task_resolutions, t.review_task_audit]

    async def rows():
        async with engine.connect() as conn:
            return {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in tables}

    before = await rows()

    async def fail(*args, **kwargs):
        raise OperationalError("SYNTHETIC_PRIVATE_SQL", {}, Exception("SYNTHETIC_PRIVATE_GOLD"))

    monkeypatch.setattr(repo, "_event", fail)
    with pytest.raises(JournalWriteUnconfirmed) as failure:
        if operation == "claim":
            await repo.claim(A, TASK, command(task))
        elif operation == "open":
            await repo.open_task(A, TASK)
        elif operation == "submit":
            await repo.submit_decision(A, TASK, decision(task))
        elif operation == "cancel":
            await repo.cancel("owner", TASK, command(task))
        else:
            await repo.reopen("owner", TASK, TaskReopen(expected_revision=task["revision"], confirmed=True, reason="Synthetic reopen"))
    assert "SYNTHETIC_PRIVATE" not in str(failure.value)
    assert await rows() == before


@pytest.mark.asyncio
async def test_release_only_returns_queued_when_no_other_active_or_submitted_assignment(tasks):
    repo, _, _, _, _, _, _, task = tasks
    claimed = await repo.claim(A, TASK, command(task))
    assert (await repo.release(A, TASK, command(claimed)))["status"] == "queued"
    await submit(repo, A, task)
    current = await repo.claim(B, TASK, command(await repo.get_task(B, TASK)))
    assert (await repo.release(B, TASK, command(current)))["status"] == "in_review"


@pytest.mark.parametrize("tamper", ["document", "resolution_hash", "decision_ciphertext", "decision_hash"])
@pytest.mark.asyncio
async def test_resolution_and_protected_decision_tampering_fail_closed(tasks, tamper):
    repo, _, engine, _, _, _, _, task = tasks
    await submit(repo, A, task)
    await submit(repo, B, task)
    async with engine.begin() as conn:
        if tamper == "document":
            await conn.execute(update(t.review_task_resolutions).values(document={"outcome": "pass"}))
        elif tamper == "resolution_hash":
            await conn.execute(update(t.review_task_resolutions).values(resolution_hash="0" * 64))
        elif tamper == "decision_ciphertext":
            await conn.execute(update(t.review_task_decisions).values(encrypted_payload="SYNTHETIC_TAMPER"))
        else:
            await conn.execute(update(t.review_task_decisions).values(protected_hash="0" * 64))
    with pytest.raises((Conflict, RequestProtectionError)):
        await repo.get_result("owner", TASK)


@pytest.mark.asyncio
async def test_arbitrator_cannot_open_incomplete_or_unanimous_review_even_with_forged_phase(tasks):
    repo, _, engine, _, _, _, _, task = tasks
    await submit(repo, A, task)
    async with engine.begin() as conn:
        await conn.execute(update(t.review_tasks).values(status="escalated"))
    await repo.claim(ARB, TASK, command(await repo.get_task(ARB, TASK)))
    with pytest.raises(Conflict):
        await repo.open_task(ARB, TASK)


@pytest.mark.parametrize("value", [" ", "\t", "\ud800"])
def test_decision_and_reopen_require_valid_nonblank_utf8(value):
    task = {"revision": 1, "subject_hash": "a" * 64}
    with pytest.raises(ValidationError):
        decision(task, note=value)
    with pytest.raises(ValidationError):
        TaskReopen(expected_revision=1, confirmed=True, reason=value)


@pytest.mark.asyncio
async def test_subject_grant_rejects_owner_as_any_reviewer_role():
    payload = TaskCreate(run_id="run", ordinal=1, case_hash="a" * 64, reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True)
    for owner in (A, B, ARB):
        with pytest.raises(Conflict):
            ReviewTaskRepository._definition(owner, "project", TASK, payload)


@pytest.mark.asyncio
async def test_crypto_verification_and_protection_run_off_event_loop(tasks, monkeypatch):
    import threading

    repo, _, _, _, _, _, _, task = tasks
    loop_thread = threading.get_ident()
    calls = []
    for name in ("_verify_materials", "_verify_decisions"):
        original = getattr(repo, name)

        def wrap(*args, _original=original, _name=name, **kwargs):
            assert threading.get_ident() != loop_thread
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(repo, name, wrap)
    protection = repo._evidence_protection()
    original_seal = protection.seal

    def seal(*args, **kwargs):
        assert threading.get_ident() != loop_thread
        calls.append("seal")
        return original_seal(*args, **kwargs)

    monkeypatch.setattr(protection, "seal", seal)
    await submit(repo, A, task)
    assert set(calls) == {"_verify_materials", "_verify_decisions", "seal"}


@pytest.mark.asyncio
async def test_create_grants_and_audit_roll_back_atomically(captured, monkeypatch):
    evidence, engine, project, _, run, ticket, clock = captured
    await evidence.record_attempt("owner", project, run["id"], ticket, observation())
    case = await evidence.open_case("owner", project, run["id"], 1)
    repo = ReviewTaskRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=lambda: clock["ms"])
    payload = TaskCreate(run_id=run["id"], ordinal=1, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True)

    async def fail(*args, **kwargs):
        raise OperationalError("SYNTHETIC_PRIVATE", {}, Exception("SYNTHETIC_GOLD"))

    monkeypatch.setattr(repo, "_event", fail)
    with pytest.raises(JournalWriteUnconfirmed):
        await repo.create_task("owner", project, TASK, payload)
    async with engine.connect() as conn:
        for table in (t.review_tasks, t.review_task_assignments, t.review_task_audit):
            assert (await conn.execute(select(func.count()).select_from(table))).scalar_one() == 0


@pytest.mark.parametrize("change", [{"run_id": "\ud800"}, {"note": " "}])
def test_private_run_identifier_and_notes_fail_validation(change):
    if "run_id" in change:
        with pytest.raises(ValidationError):
            TaskCreate.model_validate({"run_id": change["run_id"], "ordinal": 1, "case_hash": "a" * 64, "reviewer_ids": [A, B], "arbitrator_id": ARB, "share_reference": True, "confirmed": True})
    else:
        with pytest.raises(ValidationError):
            decision({"revision": 1, "subject_hash": "a" * 64}, note=change["note"])
