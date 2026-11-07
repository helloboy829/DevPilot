"""HTTP boundaries use only synthetic data and mock all outbound execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED
from app.gateway.authz import AuthContext, Permissions
from app.gateway.deps import get_config
from app.gateway.routers import evaluation_schedules, model_management, reports, request_debugger


def api(router, *, role="admin", authenticated=True, permissions=None):
    app = FastAPI()
    user = User(id=uuid4(), email="synthetic@example.com", password_hash="x", system_role=role)

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if authenticated:
            request.state.user = user
            request.state.auth_source = AUTH_SOURCE_AUTH_DISABLED
            request.state.auth = AuthContext(user=user, permissions=permissions if permissions is not None else [Permissions.THREADS_READ, Permissions.THREADS_WRITE, Permissions.RUNS_CREATE])
        return await call_next(request)

    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(evaluation_http={"allowed_hosts": []}, scheduler=SimpleNamespace(enabled=True, min_once_delay_seconds=30))
    return TestClient(app)


def test_debug_permissions_consent_and_sanitized_validation(monkeypatch):
    send = AsyncMock(return_value={"status": 200, "body": "synthetic"})
    monkeypatch.setattr(request_debugger, "send_request", send)
    body = {"spec": {"url": "https://example.test"}, "consent": True}
    assert api(request_debugger.router, authenticated=False).post("/api/component-tests/debug/send", json=body).status_code == 401
    assert api(request_debugger.router, permissions=[Permissions.THREADS_WRITE]).post("/api/component-tests/debug/send", json=body).status_code == 403
    client = api(request_debugger.router)
    assert client.post("/api/component-tests/debug/send", json=body | {"consent": False}).status_code == 422
    bad = client.post("/api/component-tests/debug/parse", json={"command": {"api_key": "synthetic-secret"}})
    assert bad.status_code == 422 and "synthetic-secret" not in bad.text
    assert "no-store" in bad.headers["cache-control"]
    send.assert_not_awaited()
    response = client.post("/api/component-tests/debug/send", json=body)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    send.assert_awaited_once()


def test_model_admin_revision_and_write_only_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    monkeypatch.setattr(model_management, "_operator_config", lambda: {"models": []})
    url = "/api/model-management"
    assert api(model_management.router, role="user").get(url).status_code == 403
    assert api(model_management.router, authenticated=False).get(url).status_code == 401
    client = api(model_management.router)
    data = {"model": {"name": "synthetic", "model": "test", "base_url": "https://example.test/v1", "api_key": "synthetic-secret"}, "revision": 0}
    response = client.put(url + "/models", json=data)
    assert response.status_code == 200 and "synthetic-secret" not in response.text
    assert response.json()["models"][0]["has_credential"]
    assert client.put(url + "/models", json=data).status_code == 409
    bad = client.put(url + "/models", json=data | {"revision": "synthetic-secret"})
    assert bad.status_code == 422 and "synthetic-secret" not in bad.text
    assert "no-store" in bad.headers["cache-control"]
    monkeypatch.setattr(model_management, "_operator_config", lambda: {"reports_agent": {"model_name": "synthetic"}})
    assert client.delete(url + "/models/synthetic?revision=1").status_code == 409


def test_report_intake_consent_does_not_call_model(monkeypatch):
    from app.reporting import intake

    run = AsyncMock()
    monkeypatch.setattr(intake, "propose_fields", run)
    client = api(reports.router)
    body = {"message": "synthetic", "language": "en", "consent": False}
    assert client.post("/api/reports/project/intake", json=body).status_code == 422
    run.assert_not_awaited()


def test_schedule_dns_failures_are_safe(monkeypatch):
    client = api(evaluation_schedules.router)
    repo = SimpleNamespace(get=AsyncMock(return_value={"id": "synthetic", "api_url": "https://example.test"}))
    monkeypatch.setattr(evaluation_schedules, "get_component_repo", lambda r: repo)
    stored = SimpleNamespace(create=AsyncMock())
    monkeypatch.setattr(evaluation_schedules, "get_scheduled_task_repo", lambda r: stored)
    monkeypatch.setattr(evaluation_schedules, "resolve_destination", AsyncMock(side_effect=OSError("synthetic-secret")))
    body = {"title": "synthetic", "component_id": "synthetic", "test_type": "perf", "params": {}, "schedule_type": "cron", "schedule_spec": {"cron": "0 2 * * *"}, "timezone": "Asia/Shanghai", "consent": True}
    response = client.post("/api/evaluation-schedules", json=body)
    assert response.status_code == 422 and "synthetic-secret" not in response.text
    stored.create.assert_not_awaited()
