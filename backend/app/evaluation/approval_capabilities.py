"""Fixed approval capability diagnostic; never authorization or approval.

The projection states which approval capabilities are intentionally absent so
clients cannot infer login, notifications, enforcement or export support.
"""

from __future__ import annotations

_BLOCKERS = (
    "approver_login_not_implemented",
    "multi_level_enforcement_not_implemented",
    "notification_not_implemented",
    "approval_export_not_implemented",
)


def approval_capabilities():
    """Return an independent fixed capability projection."""
    return {
        "schema": "qa-approval-capabilities.v1",
        "scope": "approval_capability_diagnostic_only",
        "approver_login": "not_implemented",
        "owner_records_on_behalf": True,
        "multi_level_policy": "advisory_only",
        "multi_level_enforcement": "not_implemented",
        "notifications": "not_implemented",
        "export": "not_implemented",
        "approval": "not_authorized",
        "blockers": list(_BLOCKERS),
    }


__all__ = ["approval_capabilities"]
