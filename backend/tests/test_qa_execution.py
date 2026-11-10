"""Synthetic execution admission and real collector wiring; no external targets."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from test_dispatch_journal import prepared as prepared

from app.evaluation import tables as t
from app.evaluation.evidence_protection import EvidenceProtection
from app.evaluation.execution import ExecutionCreate, ExecutionPolicy, ExecutionRepository, QAExecutionWorker
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.repository import Conflict, NotFound


def consent(plan, **changes):
    return ExecutionCreate.model_validate({"plan_id": plan["id"], "plan_hash": plan["definition_hash"], "confirmed": True, "target_authorized": True, **changes})


@pytest.fixture
def policy():
    return ExecutionPolicy(enabled=True, max_active_runs=2, max_reserved_concurrency=4, max_response_bytes=128, max_reserved_body_bytes=100000, max_reserved_response_bytes=10000)


def repository(prepared, policy):
    old, _, _, _, clock = prepared
    return ExecutionRepository(
        old.sf,
        policy=policy,
        protection=old.protection,
        evidence_protection=EvidenceProtection(Fernet.generate_key()),
        config_getter=lambda: SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]}),
        clock_ms=lambda: clock["ms"],
    )


async def admit(repo, prepared, **changes):
    _, _, project, plan, _ = prepared
    return await repo.admit("owner", project, uuid4().hex, consent(plan, **changes))


@pytest.mark.asyncio
async def test_consent_policy_idempotency_and_quota_are_independent_of_plan(prepared, policy):
    repo = repository(prepared, policy)
    _, _, project, plan, _ = prepared
    rid = uuid4().hex
    await repo.initialize()
    row = await repo.admit("owner", project, rid, consent(plan))
    assert row["state"] == "queued" and row["scope"] == "admitted_qa_json"
    assert "SYNTHETIC" not in str(row) and "token" not in str(row)
    assert await repo.admit("owner", project, rid, consent(plan)) == row
    assert len(await repo.list_executions("owner", project)) == 1
    await admit(repo, prepared)
    with pytest.raises(Conflict):
        await admit(repo, prepared)
    with pytest.raises(NotFound):
        await repo.get_execution("other", project, rid)
    with pytest.raises(Conflict):
        await repo.admit("owner", project, rid, consent(plan, plan_hash="a" * 64))
    with pytest.raises(Conflict):
        await ExecutionRepository(repo.sf, policy=ExecutionPolicy()).admit("owner", project, uuid4().hex, consent(plan))


@pytest.mark.parametrize("patch", [{"confirmed": False}, {"confirmed": 1}, {"target_authorized": False}, {"target_authorized": 1}, {"plan_hash": "bad"}, {"retry": True}])
def test_explicit_non_coercing_confirmation(patch):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExecutionCreate.model_validate({"plan_id": "plan", "plan_hash": "b" * 64, "confirmed": True, "target_authorized": True, **patch})


@pytest.mark.asyncio
async def test_disabled_or_missing_key_or_tampered_gold_cannot_admit(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    _, _, project, plan, _ = prepared
    async with repo.sf.begin() as session:
        await session.execute(update(t.references).values(expected="SYNTHETIC_TAMPERED"))
    with pytest.raises(Conflict):
        await admit(repo, prepared)
    assert not await repo.list_executions("owner", project)


@pytest.mark.asyncio
async def test_two_workers_cannot_claim_the_same_execution(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    claims = await asyncio.gather(repo.claim(), repo.claim())
    claims = [claim for claim in claims if claim is not None]
    assert len(claims) == 1 and claims[0].execution_id == row["id"]
    assert claims[0].token not in repr(claims[0])
    _, _, project, _, _ = prepared
    observed = await repo.get_execution("owner", project, row["id"])
    assert observed["run_id"] and observed["state"] == "running"
    assert await repo.claim() is None


@pytest.mark.asyncio
async def test_worker_renders_input_only_and_records_actual_output_for_human_review(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    calls = []

    async def collect(request, binding, config, limits):
        spec = request.to_request()
        calls.append(spec.body)
        assert "SYNTHETIC_INPUT" in spec.body and "GOLD" not in spec.body
        return AttemptObservation("output_collected", 200, 35, 2.0, "SYNTHETIC_ACTUAL")

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    worker = QAExecutionWorker(repo, lambda: SimpleNamespace())
    assert await worker.run_once()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "collected" and not state["reservation_held"]
    assert len(calls) == 2
    case = await repo.open_case("owner", prepared[2], state["run_id"], 1)
    assert case["output"] == "SYNTHETIC_ACTUAL" and case["expected"] == "SYNTHETIC_GOLD"
    assert case["review_revision"] == 0
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_unknown_delivery_stops_whole_run_without_retry(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    count = 0

    async def collect(*args):
        nonlocal count
        count += 1
        return AttemptObservation("delivery_unknown", None, 0, 1.0, None)

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    await QAExecutionWorker(repo, lambda: SimpleNamespace()).run_once()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]
    assert count <= 2
    assert await repo.claim() is None
    cases = await repo.list_cases("owner", prepared[2], state["run_id"])
    assert cases["counts"]["unreviewed"] == 2


@pytest.mark.asyncio
async def test_cancel_queued_never_dispatches_and_claimed_cancel_keeps_reservation_until_drained(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    stopped = await repo.cancel("owner", prepared[2], row["id"])
    assert stopped["state"] == "interrupted" and not stopped["reservation_held"]
    assert await repo.claim() is None
    row = await admit(repo, prepared)
    claim = await repo.claim()
    stopped = await repo.cancel("owner", prepared[2], row["id"])
    assert stopped["reservation_held"]
    with pytest.raises(Conflict):
        await repo.reserve_attempt(claim, 1, body_bytes=30)
    await repo.finish(claim, completed=False)
    assert not (await repo.get_execution("owner", prepared[2], row["id"]))["reservation_held"]


@pytest.mark.asyncio
async def test_expired_claim_is_never_reclaimed_or_quota_released(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    claim = await repo.claim()
    prepared[4]["ms"] += 10001
    await repo.expire()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and state["reservation_held"]
    assert await repo.claim() is None
    with pytest.raises(Conflict):
        await repo.reserve_attempt(claim, 1, body_bytes=30)


@pytest.mark.asyncio
async def test_global_quota_serializes_independent_sessions(prepared, policy):
    repo = repository(prepared, policy.model_copy(update={"max_active_runs": 1}))
    await repo.initialize()
    other = ExecutionRepository(async_sessionmaker(prepared[1], expire_on_commit=False), policy=repo.policy, protection=repo.protection, evidence_protection=repo.evidence_protection, config_getter=repo.config_getter, clock_ms=repo.clock_ms)
    results = await asyncio.gather(admit(repo, prepared), admit(other, prepared), return_exceptions=True)
    assert sum(isinstance(row, dict) for row in results) == 1
    assert sum(isinstance(row, Conflict) for row in results) == 1


@pytest.mark.asyncio
async def test_real_collector_path_uses_rendered_json_and_never_sends_gold(prepared, policy, monkeypatch):
    import json

    import httpx

    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    sent = []
    delegated = []
    from devpilot.qa_json_run import JSONRunLimits, run_json_attempts

    async def shared_run(request, binding, inputs, limits, **capabilities):
        assert isinstance(limits, JSONRunLimits)
        assert limits.request_count == 2 and limits.concurrency == 2
        assert inputs == ("SYNTHETIC_INPUT", "SYNTHETIC_INPUT")
        assert set(capabilities) == {"now_ms", "reserve_attempt", "collect_attempt", "record_attempt", "check_active"}
        delegated.append(limits)
        # Execute the REAL shared core, App DB callbacks and shared collector.
        return await run_json_attempts(request, binding, inputs, limits, **capabilities)

    monkeypatch.setattr("app.evaluation.execution.run_json_attempts", shared_run)

    def respond(request):
        sent.append(request.content)
        assert json.loads(request.content) == {"q": "SYNTHETIC_INPUT"}
        assert b"GOLD" not in request.content
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=httpx.ByteStream(b'{"a":"SYNTHETIC_REAL_COLLECTOR"}'))

    monkeypatch.setattr("app.evaluation.qa_attempts.evaluation_client", lambda *args, **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=False))
    await QAExecutionWorker(repo, repo.config_getter).run_once()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert len(delegated) == 1
    assert state["state"] == "collected" and len(sent) == 2
    assert (await repo.open_case("owner", prepared[2], state["run_id"], 1))["output"] == "SYNTHETIC_REAL_COLLECTOR"


@pytest.mark.asyncio
async def test_operator_target_allowlist_is_required_at_admission(prepared, policy):
    repo = repository(prepared, policy)
    repo.config_getter = lambda: SimpleNamespace(evaluation_http={"allowed_hosts": []})
    await repo.initialize()
    with pytest.raises(Conflict):
        await admit(repo, prepared)
    assert not await repo.list_executions("owner", prepared[2])


@pytest.mark.asyncio
async def test_missing_evidence_key_prevents_admission_before_dispatch(prepared, policy, monkeypatch):
    from app.evaluation.request_protection import RequestProtectionUnavailable

    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)
    repo = repository(prepared, policy)
    repo.evidence_protection = None
    await repo.initialize()
    with pytest.raises(RequestProtectionUnavailable):
        await admit(repo, prepared)
    assert not await repo.list_executions("owner", prepared[2])


@pytest.mark.asyncio
async def test_running_cancel_drains_in_flight_tasks_before_releasing_quota(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    entered, drained = asyncio.Event(), asyncio.Event()
    active = 0

    async def collect(*args):
        nonlocal active
        active += 1
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            active -= 1
            drained.set()

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    task = asyncio.create_task(QAExecutionWorker(repo, repo.config_getter).run_once())
    await asyncio.wait_for(entered.wait(), 5)
    state = await repo.cancel("owner", prepared[2], row["id"])
    assert state["reservation_held"] and active
    await asyncio.wait_for(task, 5)
    assert drained.is_set() and active == 0
    assert not (await repo.get_execution("owner", prepared[2], row["id"]))["reservation_held"]


@pytest.mark.asyncio
async def test_execution_policy_mismatch_cannot_claim_or_reserve(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    await admit(repo, prepared)
    other = repository(prepared, policy.model_copy(update={"max_active_runs": 3}))
    with pytest.raises(Conflict):
        await other.claim()
    assert await repo.claim() is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", ["eval_0006"], indirect=True)
async def test_migration_from_evidence_head_preserves_output_review_and_harness_ledger(prepared, policy):
    from sqlalchemy import text

    from app.evaluation.dispatch_journal import JournalLimits
    from app.evaluation.qa_evidence import ReviewCreate
    from app.evaluation.schema import upgrade_evaluation_schema

    repo = repository(prepared, policy)
    project, plan = prepared[2:4]
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=30)
    await repo.record_attempt("owner", project, run["id"], ticket, AttemptObservation("output_collected", 200, 35, 1.0, "SYNTHETIC_ACTUAL"))
    opened = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, ReviewCreate(case_hash=opened["case_hash"], expected_revision=0, decision="uncertain", note="Synthetic migration review", confirmed=True))
    async with prepared[1].begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('SYNTHETIC_HARNESS_LEDGER')"))
    await upgrade_evaluation_schema(prepared[1])
    async with prepared[1].connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0014"
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "SYNTHETIC_HARNESS_LEDGER"
        assert not (await conn.execute(select(t.executions))).all()
    reopened = await repo.open_case("owner", project, run["id"], 1)
    assert reopened["output"] == "SYNTHETIC_ACTUAL" and reopened["review_revision"] == 1
    assert reopened["reviews"][0]["note"] == "Synthetic migration review"


@pytest.mark.asyncio
async def test_parallel_render_completion_cannot_reorder_durable_dispatch(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    original = asyncio.to_thread
    renders = 0

    async def delayed_render(func, *args, **kwargs):
        nonlocal renders
        if getattr(func, "__name__", "") == "render":
            renders += 1
            if renders == 1:
                await asyncio.sleep(0.05)
        return await original(func, *args, **kwargs)

    async def collect(*args):
        return AttemptObservation("output_collected", 200, 35, 2.0, "SYNTHETIC_ACTUAL")

    monkeypatch.setattr(asyncio, "to_thread", delayed_render)
    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    await QAExecutionWorker(repo, repo.config_getter).run_once()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "collected" and not state["reservation_held"]
    assert renders == 2


@pytest.mark.asyncio
async def test_unknown_dispatch_commit_never_sends_or_reclaims(prepared, policy, monkeypatch):
    from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    original = repo.reserve_attempt
    sends = []

    async def ambiguous(*args, **kwargs):
        await original(*args, **kwargs)
        raise JournalWriteUnconfirmed("Synthetic lost commit acknowledgement")

    async def collect(*args):
        sends.append(True)
        raise AssertionError("No network send after an unconfirmed journal commit")

    monkeypatch.setattr(repo, "reserve_attempt", ambiguous)
    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    worker = QAExecutionWorker(repo, repo.config_getter)
    await worker.run_once()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]
    assert not sends
    assert not await worker.run_once()


@pytest.mark.asyncio
async def test_worker_shutdown_drains_before_releasing_reservations(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    entered = asyncio.Event()
    drained = asyncio.Event()

    async def collect(*args):
        entered.set()
        try:
            await asyncio.sleep(30)
        finally:
            assert (await repo.get_execution("owner", prepared[2], row["id"]))["reservation_held"]
            drained.set()

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    task = asyncio.create_task(QAExecutionWorker(repo, repo.config_getter).run_once())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert drained.is_set()
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]


@pytest.mark.asyncio
async def test_worker_shutdown_drains_monitor_read_before_finish(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    read_entered, read_release = asyncio.Event(), asyncio.Event()
    read_cancelled, read_drained = asyncio.Event(), asyncio.Event()
    original_read, original_finish = repo.get_execution, repo.finish
    reads = 0

    async def delayed_read(*args):
        nonlocal reads
        result = await original_read(*args)
        reads += 1
        if reads == 1:
            return result
        read_entered.set()
        try:
            await read_release.wait()
        except asyncio.CancelledError:
            read_cancelled.set()
            raise
        read_drained.set()
        return result

    async def collect(*args):
        await read_entered.wait()
        await read_release.wait()
        return AttemptObservation("output_collected", 200, 35, 1.0, "SYNTHETIC_ACTUAL")

    async def finish(*args, **kwargs):
        assert read_drained.is_set()
        return await original_finish(*args, **kwargs)

    monkeypatch.setattr(repo, "get_execution", delayed_read)
    monkeypatch.setattr(repo, "finish", finish)
    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    worker = asyncio.create_task(QAExecutionWorker(repo, repo.config_getter).run_once())
    try:
        await asyncio.wait_for(read_entered.wait(), 5)
        worker.cancel()
        await asyncio.sleep(0)
        assert not worker.done() and not read_drained.is_set()
    finally:
        read_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(worker, 5)
    assert read_drained.is_set()
    assert not read_cancelled.is_set()
    state = await original_read("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]
    assert not await repo.claim()


@pytest.mark.asyncio
async def test_database_drain_survives_repeated_cancellation_without_restarting():
    from app.evaluation.execution import _drained_database

    entered, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
    operations = []

    async def operation():
        operations.append(asyncio.current_task())
        entered.set()
        await release.wait()
        drained.set()

    task = asyncio.create_task(_drained_database(operation()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert operations[0].cancelling() == 0
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert drained.is_set() and len(operations) == 1


@pytest.mark.asyncio
async def test_shutdown_during_claim_drains_and_finishes_original_claim(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    entered, release = asyncio.Event(), asyncio.Event()
    original = repo.claim

    async def delayed_ack():
        claim = await original()
        entered.set()
        await release.wait()
        return claim

    monkeypatch.setattr(repo, "claim", delayed_ack)
    task = asyncio.create_task(QAExecutionWorker(repo, repo.config_getter).run_once())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]


@pytest.mark.asyncio
async def test_known_unknown_delivery_blocks_new_sends_while_evidence_write_drains(prepared, policy, monkeypatch):
    from app.evaluation.plans import PlanCreate

    old, _, project, plan, _ = prepared
    definition = plan["definition"]
    repeated = await old.create_plan(
        "owner",
        project,
        plan["component_id"],
        PlanCreate.model_validate(
            {
                **{key: value for key, value in definition.items() if key in PlanCreate.model_fields},
                "version_label": "Synthetic repeated load",
                "limits": {**definition["limits"], "mode": "performance", "request_count": 4},
                "confirmed": True,
            }
        ),
    )
    repeated_fixture = (*prepared[:3], repeated, prepared[4])
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, repeated_fixture)
    sends = []
    original = repo.record_attempt

    async def collect(*args):
        sends.append(True)
        if len(sends) == 1:
            return AttemptObservation("delivery_unknown", None, 0, 1.0, None)
        return AttemptObservation("output_collected", 200, 35, 1.0, "SYNTHETIC_ACTUAL")

    async def delayed_record(*args):
        if args[-1].kind == "delivery_unknown":
            await asyncio.sleep(0.1)
        return await original(*args)

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    monkeypatch.setattr(repo, "record_attempt", delayed_record)
    await QAExecutionWorker(repo, repo.config_getter).run_once()
    assert len(sends) <= 2
    state = await repo.get_execution("owner", project, row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]
