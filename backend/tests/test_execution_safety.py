"""Deadline, queue state and terminal flags never authorize release or resend."""

import ast
import inspect
from pathlib import Path

import pytest
from sqlalchemy import select
from test_dispatch_journal import prepared as prepared
from test_qa_execution import admit as admit_execution
from test_qa_execution import repository as execution_repository

from app.evaluation import tables as t
from app.evaluation.execution import ExecutionPolicy
from app.evaluation.execution_safety import classify_held_reservation

APP = Path(__file__).resolve().parents[1] / "app" / "evaluation"


def row(**changes):
    values = {
        "state": "running",
        "reservation_held": True,
        "deadline_ms": 2000,
        "reserved_concurrency": 2,
        "reserved_body_bytes": 100,
        "reserved_response_bytes": 50,
        "id": "synthetic-execution-id",
        "run_id": "synthetic-run-id",
        "claim_hash": "synthetic-claim-hash",
        "encrypted_output": "SYNTHETIC_CIPHERTEXT",
    }
    values.update(changes)
    return values


@pytest.mark.parametrize(
    ("changes", "now", "state", "terminal", "deadline_reached"),
    [
        ({"state": "queued"}, 1500, "queued_ready", False, False),
        ({"state": "queued"}, 2000, "queued_deadline_reached", False, True),
        ({"state": "running"}, 1500, "running_within_deadline", False, False),
        ({"state": "running"}, 2001, "running_deadline_reached", False, True),
        ({"state": "cancel_requested"}, 2001, "cancel_requested_pending", False, True),
        ({"state": "collected", "reservation_held": False}, 1500, "collected_terminal", True, False),
        ({"state": "interrupted", "reservation_held": False}, 2500, "interrupted_terminal", True, True),
        ({"state": "interrupted"}, 1500, "interrupted_terminal", True, False),
    ],
)
def test_every_state_never_authorizes_release_reclaim_or_resend(changes, now, state, terminal, deadline_reached):
    result = classify_held_reservation(row(**changes), now_ms=now)
    assert result["state"] == state
    assert result["terminal"] is terminal
    assert result["deadline_reached"] is deadline_reached
    assert result["worker_liveness"] == "not_established"
    for key in ("release_authorized", "reclaim_authorized", "requeue_authorized", "retry_authorized", "resend_authorized", "dispatch_authorized"):
        assert result[key] is False
    assert not any(secret in str(result) for secret in ("synthetic-execution-id", "synthetic-run-id", "synthetic-claim-hash", "SYNTHETIC_CIPHERTEXT"))


def test_projection_is_fixed_and_excludes_identifiers_or_claim_material():
    result = classify_held_reservation(row(), now_ms=1500)
    assert set(result) == {
        "scope",
        "observed_at_ms",
        "state",
        "reservation_held",
        "deadline_reached",
        "terminal",
        "worker_liveness",
        "reservation",
        "blockers",
        "release_authorized",
        "reclaim_authorized",
        "requeue_authorized",
        "retry_authorized",
        "resend_authorized",
        "dispatch_authorized",
    }
    assert set(result["reservation"]) == {"concurrency", "body_bytes", "response_bytes"}
    assert result["observed_at_ms"] == 1500 and result["scope"] == "execution_safety_observation_only"


def test_deadline_and_quota_blockers_are_fixed_codes():
    running = classify_held_reservation(row(), now_ms=2500)
    assert running["blockers"] == ["worker_liveness_not_established", "deadline_is_not_worker_death", "quota_retained_until_original_worker_drains"]
    queued = classify_held_reservation(row(state="queued"), now_ms=2500)
    assert queued["blockers"] == ["worker_liveness_not_established", "deadline_is_not_worker_death"]
    expired_running = classify_held_reservation(row(state="interrupted"), now_ms=2500)
    assert expired_running["blockers"] == ["worker_liveness_not_established", "deadline_is_not_worker_death", "quota_retained_until_original_worker_drains"]
    done = classify_held_reservation(row(state="collected", reservation_held=False), now_ms=1000)
    assert done["blockers"] == ["terminal_record_grants_nothing"]


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {"state": "running"},
        row(state="passed"),
        row(reservation_held=1),
        row(state="collected"),
        row(state="queued", reservation_held=False),
        row(deadline_ms="2000"),
        row(deadline_ms=True),
        row(deadline_ms=0),
        row(reserved_concurrency=-1),
        row(reserved_response_bytes="50"),
    ],
)
def test_malformed_or_incoherent_rows_fail_closed(bad):
    with pytest.raises(ValueError):
        classify_held_reservation(bad, now_ms=1500)


@pytest.mark.parametrize("now", [True, 0, -1, "1500", None])
def test_invalid_clock_fails_closed(now):
    with pytest.raises(ValueError):
        classify_held_reservation(row(), now_ms=now)


def test_module_is_synchronous_and_has_no_io_dependencies():
    source = (APP / "execution_safety.py").read_text(encoding="utf-8")
    assert not inspect.iscoroutinefunction(classify_held_reservation)
    for forbidden in ("asyncio", "httpx", "requests", "socket", "sqlalchemy", "update(", "insert("):
        assert forbidden not in source


def test_scheduler_cannot_bypass_qa_execution_admission():
    source = (APP / "schedules.py").read_text(encoding="utf-8")
    assert "ExecutionRepository" not in source
    assert "qa_execution" not in source
    assert "admit(" not in source


def test_formal_approval_cannot_dispatch_or_release_executions():
    source = (APP / "qa_approvals.py").read_text(encoding="utf-8")
    assert "ExecutionRepository" not in source
    assert "admit(" not in source


def test_operations_router_exposes_only_aggregate_get():
    path = Path(__file__).resolve().parents[1] / "app" / "gateway" / "routers" / "evaluation_operations.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "router"]
    assert {node.func.attr for node in calls} == {"get"}
    assert {node.args[0].value for node in calls} == {"/reservations"}


def execution_policy():
    return ExecutionPolicy(enabled=True, max_active_runs=2, max_reserved_concurrency=4, max_response_bytes=128, max_reserved_body_bytes=100000, max_reserved_response_bytes=10000)


async def stored_row(engine, execution_id):
    async with engine.connect() as conn:
        return dict((await conn.execute(select(t.executions).where(t.executions.c.id == execution_id))).mappings().one())


@pytest.mark.asyncio
async def test_real_queued_expiry_releases_quota_and_never_authorizes(prepared):
    repo = execution_repository(prepared, execution_policy())
    await repo.initialize()
    _, engine, _, _, clock = prepared
    admitted = await admit_execution(repo, prepared)
    row = await stored_row(engine, admitted["id"])
    assert row["state"] == "queued" and row["reservation_held"] is True
    pending = classify_held_reservation(row, now_ms=clock["ms"])
    assert pending["state"] == "queued_ready" and pending["terminal"] is False
    clock["ms"] = row["deadline_ms"] + 1
    await repo.expire()
    expired = await stored_row(engine, admitted["id"])
    assert expired["state"] == "interrupted" and expired["reservation_held"] is False
    after = classify_held_reservation(expired, now_ms=clock["ms"])
    assert after["state"] == "interrupted_terminal" and after["terminal"] is True
    assert after["blockers"] == ["terminal_record_grants_nothing"]
    assert all(after[key] is False for key in ("release_authorized", "reclaim_authorized", "requeue_authorized", "retry_authorized", "resend_authorized", "dispatch_authorized"))


@pytest.mark.asyncio
async def test_real_running_expiry_retains_quota_and_never_authorizes(prepared):
    repo = execution_repository(prepared, execution_policy())
    await repo.initialize()
    _, engine, _, _, clock = prepared
    admitted = await admit_execution(repo, prepared)
    claim = await repo.claim()
    assert claim is not None
    row = await stored_row(engine, admitted["id"])
    assert row["state"] == "running" and row["reservation_held"] is True
    assert classify_held_reservation(row, now_ms=clock["ms"])["state"] == "running_within_deadline"
    clock["ms"] = row["deadline_ms"] + 1
    await repo.expire()
    expired = await stored_row(engine, admitted["id"])
    assert expired["state"] == "interrupted" and expired["reservation_held"] is True
    after = classify_held_reservation(expired, now_ms=clock["ms"])
    assert after["state"] == "interrupted_terminal"
    assert after["blockers"] == ["worker_liveness_not_established", "deadline_is_not_worker_death", "quota_retained_until_original_worker_drains"]
    assert after["reservation"] == {"concurrency": row["reserved_concurrency"], "body_bytes": row["reserved_body_bytes"], "response_bytes": row["reserved_response_bytes"]}
    assert all(after[key] is False for key in ("release_authorized", "reclaim_authorized", "requeue_authorized", "retry_authorized", "resend_authorized", "dispatch_authorized"))
