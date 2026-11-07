"""Report previews are authenticated, stateless and never verified by the client."""

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED
from app.gateway.authz import AuthContext, Permissions
from app.gateway.routers import reports


def client(*, authenticated=True, writable=True, runnable=False):
    app = FastAPI()
    user = User(email="synthetic@example.com", password_hash="x", system_role="user", id=uuid4())

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if authenticated:
            request.state.user = user
            request.state.auth_source = AUTH_SOURCE_AUTH_DISABLED
            permissions = [Permissions.THREADS_READ]
            if writable:
                permissions.append(Permissions.THREADS_WRITE)
            if runnable:
                permissions.append(Permissions.RUNS_CREATE)
            request.state.auth = AuthContext(user=user, permissions=permissions)
        return await call_next(request)

    app.include_router(reports.router)
    return TestClient(app), str(user.id)


def payload():
    return {
        "template_id": "component-evaluation-zh",
        "template_version": "1.0.0",
        "facts": {
            "title": "Synthetic report",
            "project_name": "Fictional project",
            "component_name": "Demo",
            "component_version": "demo",
            "tester": "Synthetic tester",
            "test_period": "Synthetic window",
            "environment": "Mock",
            "scope": "Synthetic only",
            "methodology": "Manual",
            "evidence_notes": "Fictional reference",
            "limitations": "Not verified",
            "evaluation_mode": "BASELINE",
            "effect": {"total": 4, "passed": 2, "failed": 1, "errors": 0, "pending": 1, "not_run": 0},
        },
    }


def test_catalog_and_preview_require_authentication():
    api, _ = client(authenticated=False)
    with api:
        assert api.get("/api/reports/templates").status_code == 401
        assert api.post("/api/reports/preview", json=payload()).status_code == 401


def test_read_only_user_cannot_generate_previews():
    api, _ = client(writable=False)
    with api:
        assert api.get("/api/reports/templates").status_code == 200
        assert api.post("/api/reports/preview", json=payload()).status_code == 403


def test_preview_uses_authenticated_actor_and_disables_caching():
    api, user_id = client()
    with api:
        response = api.post("/api/reports/preview", json=payload())
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["manifest"]["generated_by"] == user_id
    assert response.json()["source"] == "manual_unverified"


def test_invalid_counts_unknown_templates_and_spoofed_verification_are_rejected():
    api, _ = client()
    with api:
        data = payload()
        data["facts"]["effect"]["passed"] = 9
        assert api.post("/api/reports/preview", json=data).status_code == 422
        data = payload()
        data["template_version"] = "latest"
        assert api.post("/api/reports/preview", json=data).status_code == 422
        data = payload()
        data["facts"]["source"] = "platform_verified"
        assert api.post("/api/reports/preview", json=data).status_code == 422
        data = payload()
        del data["template_version"]
        assert api.post("/api/reports/preview", json=data).status_code == 422
