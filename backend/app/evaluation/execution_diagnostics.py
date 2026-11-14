"""Aggregate-only execution reservation diagnostics, never liveness or authority.

A single SELECT over held technical reservations; no guard writes, expiry,
protected evidence, claim material, per-owner identifiers or available-slot grant.
"""

from sqlalchemy import case, func, select

from app.evaluation import tables as t
from app.evaluation.execution import ExecutionPolicy

STATES = ("queued", "running", "cancel_requested", "collected", "interrupted")
# Aggregate classification of held reservations; never per-run identity or authority.
SAFETY_STATES = (
    "queued_ready",
    "queued_deadline_reached",
    "running_within_deadline",
    "running_deadline_reached",
    "cancel_requested_pending",
    "interrupted_terminal",
)


async def reservation_snapshot(repository):
    # This is the serving process's policy, not proof that all Workers agree.
    policy = ExecutionPolicy.model_validate(repository.policy.model_dump())
    at_ms = repository._time()
    columns = [func.count().label("held_runs")]
    for name in ("reserved_concurrency", "reserved_body_bytes", "reserved_response_bytes"):
        columns.append(func.coalesce(func.sum(t.executions.c[name]), 0).label(name))
    state = t.executions.c.state
    deadline_reached = t.executions.c.deadline_ms <= at_ms
    running_after_deadline = t.executions.c.deadline_ms > at_ms
    columns.append(func.coalesce(func.sum(case((deadline_reached, 1), else_=0)), 0).label("deadline_reached_runs"))
    for name, condition in (
        ("queued_ready", (state == "queued") & running_after_deadline),
        ("queued_deadline_reached", (state == "queued") & deadline_reached),
        ("running_within_deadline", (state == "running") & running_after_deadline),
        ("running_deadline_reached", (state == "running") & deadline_reached),
        ("cancel_requested_pending", state == "cancel_requested"),
        ("interrupted_terminal", state == "interrupted"),
    ):
        columns.append(func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label("safety_" + name))
    for state_name in STATES:
        condition = state == state_name
        columns.append(func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(state_name))
        columns.append(func.coalesce(func.sum(case((condition & deadline_reached, 1), else_=0)), 0).label(state_name + "_deadline"))
    async with repository.sf() as session:
        row = (await session.execute(select(*columns).where(t.executions.c.reservation_held.is_(True)))).mappings().one()
    return {
        "scope": "execution_reservations_diagnostic_only",
        "observed_at_ms": at_ms,
        "policy_scope": "serving_process_only",
        "policy": policy.model_dump(),
        "reservations": {name: int(row[name]) for name in ("held_runs", "reserved_concurrency", "reserved_body_bytes", "reserved_response_bytes", "deadline_reached_runs")},
        "states": {state_name: {"held_runs": int(row[state_name]), "deadline_reached_runs": int(row[state_name + "_deadline"])} for state_name in STATES},
        "safety": {"scope": "aggregate_held_reservation_states", "states": {name: int(row["safety_" + name]) for name in SAFETY_STATES}},
        "worker_liveness": "not_established",
        "release_authorized": False,
        "reclaim_authorized": False,
        "retry_authorized": False,
        "dispatch_authorized": False,
    }
