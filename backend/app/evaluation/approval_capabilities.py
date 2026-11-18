"""Fixed approval capability diagnostic; never authorization or approval.

Assigned signatures are available to every initialized human account. Notices
are an explicitly loaded in-app event feed, not external delivery.
"""

from __future__ import annotations

_BLOCKERS = (
    "multi_level_enforcement_not_implemented",
    "external_notification_delivery_not_implemented",
    "approval_export_not_implemented",
)


def approval_capabilities():
    """Return an independent fixed capability projection."""
    return {
        "schema": "qa-approval-capabilities.v1",
        "scope": "approval_capability_diagnostic_only",
        "approver_login": "assigned_request_only",
        "owner_records_on_behalf": True,
        "multi_level_policy": "advisory_only",
        "multi_level_enforcement": "not_implemented",
        "notifications": "in_app_only",
        "export": "not_implemented",
        "approval": "not_authorized",
        "blockers": list(_BLOCKERS),
    }


__all__ = ["approval_capabilities"]
