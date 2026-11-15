"""Fixed approval capability diagnostic; never authorization or approval."""

import pytest
from test_evaluation_registry_router import api as api
from test_qa_approvals_router import setup_approval

from app.evaluation.approval_capabilities import approval_capabilities
from app.gateway.authz import Permissions


def test_capabilities_are_a_fixed_independent_projection():
    first = approval_capabilities()
    second = approval_capabilities()
    assert first == second
    assert first == {
        "schema": "qa-approval-capabilities.v1",
        "scope": "approval_capability_diagnostic_only",
        "approver_login": "not_implemented",
        "owner_records_on_behalf": True,
        "multi_level_policy": "advisory_only",
        "multi_level_enforcement": "not_implemented",
        "notifications": "not_implemented",
        "export": "not_implemented",
        "approval": "not_authorized",
        "blockers": [
            "approver_login_not_implemented",
            "multi_level_enforcement_not_implemented",
            "notification_not_implemented",
            "approval_export_not_implemented",
        ],
    }
    first["blockers"].append("mutated")
    assert approval_capabilities()["blockers"] == second["blockers"]


@pytest.mark.asyncio
async def test_capability_endpoint_is_human_read_only_and_permissioned(api, monkeypatch):
    client, app, base, _ = api
    root, _ = await setup_approval(api, monkeypatch)
    path = base + "/approvals/capabilities"
    result = await client.get(path)
    assert result.status_code == 200 and "no-store" in result.headers["cache-control"]
    assert result.json()["schema"] == "qa-approval-capabilities.v1"
    assert result.json()["approval"] == "not_authorized"
    assert not any(secret in result.text for secret in ("document", "note", "hash", "SYNTHETIC"))
    original = app.state.permissions
    original_actor = app.state.actor
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401
    assert (await client.post(path, json={})).status_code == 405
    app.state.actor = original_actor
    assert (await client.get(root + "/approvals")).status_code == 200
