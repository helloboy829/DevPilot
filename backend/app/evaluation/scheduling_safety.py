"""Read-only QA scheduling admission diagnostic.

The legacy scheduler remains scoped to component tests. There is no versioned
admission contract binding it to the admitted QA execution chain, no proof that
a lost Worker can no longer send, and no release/reclaim/dispatch authority.
This projection is fixed and must never be treated as an execution permit.
"""

from __future__ import annotations

_BLOCKERS = (
    "no_versioned_admission_contract",
    "scheduler_not_bound_to_qa_execution",
    "worker_liveness_not_established",
)


def scheduling_admission():
    """Return the fixed technical admission projection; never dispatch authority."""
    return {
        "schema": "qa-scheduling-admission.v1",
        "scope": "qa_scheduling_admission_diagnostic_only",
        "scheduler_scope": "component_tests_only",
        "qa_chain_admitted": False,
        "dispatch_authorized": False,
        "release_authorized": False,
        "blockers": list(_BLOCKERS),
    }


__all__ = ["scheduling_admission"]
