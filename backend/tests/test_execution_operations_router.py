"""Actual login/RBAC administrator diagnostics, synthetic DB and no network."""

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.exc import OperationalError
from test_qa_authenticated_workflow_api import ORIGIN, PASSWORD
from test_qa_authenticated_workflow_api import api as api
from test_qa_authenticated_workflow_api import workflow as workflow
from test_qa_workflow_api import CANARIES, create_plan, response_json

from app.gateway.authz import Permissions
from app.gateway.routers import evaluation_operations
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig

PATH = "/api/evaluation/operations/reservations"


def policy(*, allowed=True, denied=False, user_allowed=False):
    return AuthorizationConfig(
        enabled=True,
        fail_closed=True,
        provider=AuthorizationProviderConfig(
            use="deerflow.authz.rbac:RbacAuthorizationProvider",
            config={
                "roles": {
                    "user": {"routes": {"allow": [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW] + ([Permissions.EVALUATION_OPERATIONS_READ] if user_allowed else [])}},
                    "admin": {"routes": {"allow": [Permissions.EVALUATION_PROJECTS_READ] + ([Permissions.EVALUATION_OPERATIONS_READ] if allowed else []), "deny": [Permissions.EVALUATION_OPERATIONS_READ] if denied else []}},
                }
            },
        ),
    )


async def administrator(app):
    identities = app.state.test_accounts
    user = await identities.provider.get_user(str(identities.users["outsider"].id))
    user.system_role = "admin"
    await identities.provider.update_user(user)
    identities.policy["value"] = policy()
    app.include_router(evaluation_operations.router)
    return identities.clients["outsider"]


@pytest.mark.asyncio
async def test_authenticated_human_admin_plus_explicit_permission_not_project_membership(workflow):
    state = workflow
    admin = await administrator(state.app)
    identities = state.app.state.test_accounts
    plan = await create_plan(state, "v1")
    path = state.base + "/execution-runs/" + uuid4().hex
    queued = response_json(await state.client.put(path, json={"plan_id": plan["id"], "plan_hash": plan["definition_hash"], "confirmed": True, "target_authorized": True}))
    before = response_json(await state.client.get(path))
    result = await admin.get(PATH)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    data = result.json()
    assert data["reservations"]["held_runs"] == 1 and data["states"]["queued"]["held_runs"] == 1
    assert data["release_authorized"] is data["dispatch_authorized"] is False
    assert all(value not in result.text for value in [*CANARIES, PASSWORD, queued["id"], queued["run_id"], plan["definition_hash"], state.base.rsplit("/", 1)[1]])
    # The global aggregate grant does not grant access to any project or evidence.
    response_json(await admin.get(path), 404)
    identities.policy["value"] = policy(allowed=False)
    response_json(await admin.get(PATH), 403)
    identities.policy["value"] = policy(user_allowed=True)
    response_json(await state.client.get(PATH), 403)
    for actor in ("reviewer_a", "reviewer_b", "arbitrator"):
        response_json(await identities.clients[actor].get(PATH), 403)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(state.app), base_url=ORIGIN) as anonymous:
        denied = await anonymous.get(PATH)
        # AuthMiddleware rejects before a route/private response exists.
        assert denied.status_code == 401 and all(value not in denied.text for value in [*CANARIES, PASSWORD])
    assert response_json(await state.client.get(path)) == before
    assert state.sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("denied", [False, True])
async def test_enabled_rbac_missing_or_explicitly_denied_permission_cannot_read(api, denied):
    _, app, _, _ = api
    admin = await administrator(app)
    app.state.test_accounts.policy["value"] = policy(allowed=denied, denied=denied)
    response = await admin.get(PATH)
    assert response.status_code == 403 and response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_valid_internal_token_cannot_impersonate_admin_or_read_diagnostics(api):
    _, app, _, _ = api
    admin = await administrator(app)
    app.state.test_accounts.policy["value"] = policy(user_allowed=True)
    response = await admin.get(PATH, headers={"X-DeerFlow-Internal-Token": "synthetic-test-only-internal-token"})
    assert response.status_code == 403 and response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_unavailable_service_fails_private_without_reading_production_config(api):
    _, app, _, _ = api
    admin = await administrator(app)
    response = await admin.get(PATH)
    assert response.status_code == 503 and response.headers["cache-control"] == "private, no-store"
    assert response.json() == {"detail": "Evaluation execution diagnostics are unavailable"}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["database", "clock"])
async def test_database_and_clock_failures_are_generic_private_and_not_logged(workflow, monkeypatch, caplog, failure):
    state = workflow
    admin = await administrator(state.app)
    secret = "SYNTHETIC_DIAGNOSTICS_SECRET"
    if failure == "database":

        class BrokenSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return False

            async def execute(self, *_args):
                raise OperationalError("secret SQL " + secret, {"gold": secret}, Exception(secret))

        monkeypatch.setattr(state.repository, "sf", BrokenSession)
    else:
        monkeypatch.setattr(state.repository, "clock_ms", lambda: -1)
    response = await admin.get(PATH)
    assert response.status_code == 503 and response.headers["cache-control"] == "private, no-store"
    assert secret not in response.text + caplog.text
    assert all(value not in response.text + caplog.text for value in CANARIES)
    assert state.sent == []


@pytest.mark.asyncio
async def test_route_exposes_only_get_no_release_reclaim_expire_or_execution(workflow):
    state = workflow
    admin = await administrator(state.app)
    routes = [route for route in evaluation_operations.router.routes if getattr(route, "path", "").startswith("/api/evaluation/operations")]
    assert [(route.path, route.methods) for route in routes] == [(PATH, {"GET"})]
    for method in ("post", "put", "patch", "delete"):
        response = await getattr(admin, method)(PATH)
        assert response.status_code == 405
    for suffix in ("release", "reclaim", "expire", "execute"):
        assert (await admin.post(PATH + "/" + suffix)).status_code == 404
    result = await admin.get(PATH + "?ignored=SYNTHETIC_SECRET")
    assert result.status_code == 200 and "SYNTHETIC" not in json.dumps(result.json())
    assert state.sent == []
