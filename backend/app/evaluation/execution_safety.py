"""Bounded technical classification of held QA execution reservations.

Observation only. Deadline passage, queue membership and terminal flags never
prove a Worker is gone and never authorize release, reclaim, requeue, retry,
resend or dispatch. A running/cancel_requested reservation keeps its global
quota until the original worker drains, and malformed or incoherent rows fail
closed instead of being guessed.
"""

from __future__ import annotations

_STATES = frozenset({"queued", "running", "cancel_requested", "collected", "interrupted"})
_HELD = frozenset({"queued", "running", "cancel_requested"})
_TERMINAL = frozenset({"collected", "interrupted"})
_REQUIRED = ("state", "reservation_held", "deadline_ms", "reserved_concurrency", "reserved_body_bytes", "reserved_response_bytes")
_MAX_INT = 9_007_199_250_000_000

# Fixed output keys: callers must never receive identifiers, claim material,
# endpoints, keys, Q/A/gold or ciphertext from this observation.


def _state_code(state, deadline_reached):
    if state == "queued":
        return "queued_deadline_reached" if deadline_reached else "queued_ready"
    if state == "running":
        return "running_deadline_reached" if deadline_reached else "running_within_deadline"
    if state == "cancel_requested":
        return "cancel_requested_pending"
    if state == "collected":
        return "collected_terminal"
    return "interrupted_terminal"


def _integer(value, maximum=_MAX_INT):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("Invalid reservation field")
    return value


def _nonnegative(value):
    if type(value) is not int or not 0 <= value <= _MAX_INT:
        raise ValueError("Invalid reservation field")
    return value


def classify_held_reservation(row, *, now_ms):
    """Return a fixed technical projection; never a liveness or release grant.

    ``row`` is one execution row (extra columns are ignored). Unknown states,
    non-strict integers/bools, missing fields and incoherent held/state pairs
    raise ``ValueError`` so a caller cannot turn a damaged row into authority.
    """
    if not isinstance(row, dict) or not set(_REQUIRED).issubset(row):
        raise ValueError("Invalid reservation row")
    state = row["state"]
    if state not in _STATES:
        raise ValueError("Invalid reservation state")
    held = row["reservation_held"]
    if type(held) is not bool:
        raise ValueError("Invalid reservation field")
    if state in _HELD and held is not True:
        raise ValueError("Incoherent reservation row")
    if state == "collected" and held is not False:
        raise ValueError("Incoherent reservation row")
    deadline = _integer(row["deadline_ms"])
    now = _integer(now_ms)
    concurrency = _nonnegative(row["reserved_concurrency"])
    body_bytes = _nonnegative(row["reserved_body_bytes"])
    response_bytes = _nonnegative(row["reserved_response_bytes"])
    deadline_reached = deadline <= now
    blockers = []
    if held:
        blockers.append("worker_liveness_not_established")
    else:
        blockers.append("terminal_record_grants_nothing")
    if held and deadline_reached:
        blockers.append("deadline_is_not_worker_death")
    if held and state in {"running", "cancel_requested"}:
        blockers.append("quota_retained_until_original_worker_drains")
    return {
        "scope": "execution_safety_observation_only",
        "observed_at_ms": now,
        "state": _state_code(state, deadline_reached),
        "reservation_held": held,
        "deadline_reached": deadline_reached,
        "terminal": state in _TERMINAL,
        "worker_liveness": "not_established",
        "reservation": {"concurrency": concurrency, "body_bytes": body_bytes, "response_bytes": response_bytes},
        "blockers": blockers,
        "release_authorized": False,
        "reclaim_authorized": False,
        "requeue_authorized": False,
        "retry_authorized": False,
        "resend_authorized": False,
        "dispatch_authorized": False,
    }
