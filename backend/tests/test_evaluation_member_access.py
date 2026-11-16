"""Evaluation membership belongs to every initialized human, without role grants."""

from types import SimpleNamespace

import pytest
from test_evaluation_registry_router import api as api
from test_review_tasks_router import ROOT, TASK, command, ready

from app.gateway.authz import Permissions, resolve_route_permissions
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.authorization_config import AuthorizationConfig

MEMBER_PERMISSIONS = [
    Permissions.EVALUATION_PROJECTS_READ,
    Permissions.EVALUATION_PROJECTS_WRITE,
    Permissions.EVALUATION_PROJECTS_REVIEW,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["user", "admin"])
@pytest.mark.parametrize("provider_mode", ["empty", "deny", "unavailable"])
async def test_every_initialized_human_has_evaluation_access(monkeypatch, role, provider_mode):
    config = AuthorizationConfig(enabled=True, fail_closed=True)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    policy = {"routes": {"allow": [], "deny": MEMBER_PERMISSIONS if provider_mode == "deny" else []}}
    provider = RbacAuthorizationProvider(roles={role: policy})

    def resolve_provider(_config):
        if provider_mode == "unavailable":
            raise RuntimeError("SYNTHETIC_UNAVAILABLE")
        return provider

    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", resolve_provider)
    user = SimpleNamespace(id="synthetic-user", system_role=role, needs_setup=False)
    permissions = await resolve_route_permissions(user, is_internal=False)
    assert permissions == MEMBER_PERMISSIONS


@pytest.mark.asyncio
@pytest.mark.parametrize("role,needs_setup,is_internal", [("user", False, True), ("internal", False, False), ("user", True, False)])
async def test_membership_does_not_promote_internal_or_uninitialized_accounts(monkeypatch, role, needs_setup, is_internal):
    config = AuthorizationConfig(enabled=True, fail_closed=True)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config)
    monkeypatch.setattr("app.gateway.authz._get_cached_route_provider", lambda _: RbacAuthorizationProvider(roles={}))
    user = SimpleNamespace(id="synthetic-user", system_role=role, needs_setup=needs_setup)
    assert await resolve_route_permissions(user, is_internal=is_internal) == []


@pytest.mark.asyncio
async def test_assigned_ordinary_member_reviews_without_any_role_permissions(api, monkeypatch):
    client, app, base, _ = api
    await ready(api, monkeypatch)
    app.state.permissions = []
    app.state.actor = 2
    task = await client.get(ROOT + "/" + TASK)
    assert task.status_code == 200
    claimed = await client.post(ROOT + "/" + TASK + "/claim", json=command(task.json()))
    assert claimed.status_code == 200
    opened = await client.get(ROOT + "/" + TASK + "/case")
    assert opened.status_code == 200
    assert opened.json()["prior_decisions"] == []
    decision = await client.post(
        ROOT + "/" + TASK + "/decisions",
        json={**command(claimed.json()), "subject_hash": claimed.json()["subject_hash"], "decision": "pass", "note": "SYNTHETIC_MEMBER_REVIEW"},
    )
    assert decision.status_code == 200
    assert (await client.get(base + "/datasets")).status_code == 404
    assert (await client.post(ROOT + "/" + TASK + "/cancel", json=command(decision.json()))).status_code == 404
    app.state.actor = 5
    assert (await client.get(ROOT + "/" + TASK)).status_code == 404
    app.state.actor = 2
    app.state.internal = True
    assert (await client.get(ROOT + "/" + TASK)).status_code == 403
    app.state.internal = False
    app.state.actor = 0
    assert (await client.get(ROOT)).status_code == 401
