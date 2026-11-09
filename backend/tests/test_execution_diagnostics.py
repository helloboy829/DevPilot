"""Read-only synthetic reservation aggregates; expiry never proves Worker death."""

import json

import pytest
from sqlalchemy import event, select
from test_qa_execution import admit, repository
from test_qa_execution import policy as policy
from test_qa_execution import prepared as prepared

from app.evaluation import tables as t
from app.evaluation.execution import ExecutionPolicy
from app.evaluation.execution_diagnostics import STATES, reservation_snapshot


async def database_state(repo):
    async with repo.sf() as session:
        return {table.name: [dict(row) for row in (await session.execute(select(table))).mappings()] for table in (t.executions, t.execution_guard, t.dispatch_runs, t.dispatches, t.dispatch_audit)}


def assert_no_authority(snapshot):
    assert snapshot["scope"] == "execution_reservations_diagnostic_only"
    assert snapshot["worker_liveness"] == "not_established"
    assert snapshot["policy_scope"] == "serving_process_only"
    assert all(snapshot[key] is False for key in ("release_authorized", "reclaim_authorized", "retry_authorized", "dispatch_authorized"))
    assert set(snapshot["states"]) == set(STATES)


@pytest.mark.asyncio
async def test_empty_diagnostics_do_not_initialize_guard_or_require_keys(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)
    repo.protection = repo.evidence_protection = None
    before = await database_state(repo)
    result = await reservation_snapshot(repo)
    assert_no_authority(result)
    assert set(result["reservations"].values()) == {0}
    assert all(set(counts.values()) == {0} for counts in result["states"].values())
    assert result["policy"] == policy.model_dump()
    assert result["observed_at_ms"] == prepared[4]["ms"]
    assert await database_state(repo) == before and before[t.execution_guard.name] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["queued", "running", "cancel_requested", "deadline_running", "expired_running", "cancelled_queued", "expired_queued", "finished_original"])
async def test_all_lifecycle_reservations_are_observed_not_mutated_or_released(prepared, policy, mode):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    claim = None
    state = "queued"
    held, deadline = 1, 0
    if mode in {"running", "cancel_requested", "deadline_running", "expired_running", "finished_original"}:
        claim = await repo.claim()
        state = "running"
    if mode in {"cancel_requested", "cancelled_queued", "finished_original"}:
        await repo.cancel("owner", prepared[2], row["id"])
        state = "cancel_requested" if claim else "interrupted"
        if claim is None:
            held = 0
    if mode in {"deadline_running", "expired_running", "expired_queued"}:
        prepared[4]["ms"] = row["deadline_ms"]
        deadline = 1
    if mode in {"expired_running", "expired_queued"}:
        await repo.expire()
        state = "interrupted"
        if claim is None:
            held = deadline = 0
    if mode == "finished_original":
        await repo.finish(claim, completed=False)
        held = 0
        state = "interrupted"
    before = await database_state(repo)
    result = await reservation_snapshot(repo)
    assert_no_authority(result)
    assert result["reservations"] == {
        "held_runs": held,
        "reserved_concurrency": held * row["reserved_concurrency"],
        "reserved_body_bytes": held * row["reserved_body_bytes"],
        "reserved_response_bytes": held * row["reserved_response_bytes"],
        "deadline_reached_runs": held * deadline,
    }
    assert result["states"][state] == {"held_runs": held, "deadline_reached_runs": held * deadline}
    assert sum(values["held_runs"] for values in result["states"].values()) == held
    assert await database_state(repo) == before
    text = json.dumps(result)
    assert all(value not in text for value in ("SYNTHETIC", row["id"], row["run_id"], row["plan_hash"], prepared[2]))
    if claim:
        assert claim.token not in text
    if mode in {"deadline_running", "expired_running"}:
        assert await repo.claim() is None
        # Only the original claim can finish after it has drained; diagnostics cannot.
        await repo.finish(claim, completed=False)
        assert (await reservation_snapshot(repo))["reservations"]["held_runs"] == 0


@pytest.mark.asyncio
async def test_one_aggregate_select_has_no_secret_columns_joins_locks_or_owner_scope(prepared, policy):
    repo = repository(prepared, policy)
    await repo.initialize()
    rows = [await admit(repo, prepared), await admit(repo, prepared)]
    await repo.claim()
    prepared[4]["ms"] = rows[0]["deadline_ms"]
    # Changed/disabled local policy must not rewrite the guard while quota is held.
    repo.policy = ExecutionPolicy(max_active_runs=1)
    before = await database_state(repo)
    statements = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    event.listen(prepared[1].sync_engine, "before_cursor_execute", capture)
    try:
        result = await reservation_snapshot(repo)
    finally:
        event.remove(prepared[1].sync_engine, "before_cursor_execute", capture)
    assert len(statements) == 1 and statements[0].lstrip().startswith("select ")
    sql = statements[0]
    assert "evaluation_executions.reservation_held" in sql
    assert all(word not in sql for word in ("claim_hash", "owner_id", "project_id", "plan_hash", "join ", "for update", "evaluation_execution_guard", "ciphertext", "evaluation_samples"))
    assert result["reservations"] == {
        "held_runs": 2,
        "reserved_concurrency": sum(row["reserved_concurrency"] for row in rows),
        "reserved_body_bytes": sum(row["reserved_body_bytes"] for row in rows),
        "reserved_response_bytes": sum(row["reserved_response_bytes"] for row in rows),
        "deadline_reached_runs": 2,
    }
    assert result["states"]["running"] == result["states"]["queued"] == {"held_runs": 1, "deadline_reached_runs": 1}
    assert result["policy"]["enabled"] is False and result["policy"]["max_active_runs"] == 1
    assert await database_state(repo) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", [True, 0, -1, 1.5])
async def test_invalid_clock_fails_before_database_reads(prepared, policy, clock):
    repo = repository(prepared, policy)
    repo.clock_ms = lambda: clock
    with pytest.raises(ValueError, match="Invalid journal parameter"):
        await reservation_snapshot(repo)
