"""No actual target calls or real credentials in template API tests."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from devpilot.request_templates import RequestTemplate
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.authz import AuthContext
from app.gateway.routers.request_debugger import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def auth(request, call_next):
        request.state.auth = AuthContext(user=SimpleNamespace(id="synthetic"), permissions=["threads:write"])
        return await call_next(request)

    with TestClient(app) as client:
        yield client


def test_export_is_value_free_and_does_not_send(client):
    payload = {"spec": {"url": "https://example.test/SYNTHETIC_PATH?token=SYNTHETIC_QUERY", "method": "POST", "headers": [["Authorization", "Bearer SYNTHETIC_HEADER"]], "body": "SYNTHETIC_BODY"}}
    with patch("app.gateway.routers.request_debugger.send_request", side_effect=AssertionError("must not send")):
        result = client.post("/api/component-tests/debug/template", json=payload)
    assert result.status_code == 200
    assert "no-store" in result.headers["cache-control"]
    assert "SYNTHETIC" not in result.text
    assert RequestTemplate.from_dict(result.json()["template"]).method == "POST"


def test_template_validation_does_not_echo_values(client):
    result = client.post("/api/component-tests/debug/template", json={"spec": {"url": "https://secret:SYNTHETIC@example.test"}})
    assert result.status_code == 422
    assert "SYNTHETIC" not in result.text
    assert "no-store" in result.headers["cache-control"]


def test_unauthenticated_export_is_denied(monkeypatch):
    monkeypatch.delenv("DEER_FLOW_AUTH_DISABLED", raising=False)
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(AuthMiddleware)
    with TestClient(app) as client:
        result = client.post("/api/component-tests/debug/template", json={"spec": {"url": "https://example.test"}})
    assert result.status_code == 401


def test_export_without_write_permission_is_denied():
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def auth(request, call_next):
        request.state.auth = AuthContext(user=SimpleNamespace(id="synthetic"), permissions=["threads:read"])
        return await call_next(request)

    with TestClient(app) as client:
        result = client.post("/api/component-tests/debug/template", json={"spec": {"url": "https://example.test"}})
    assert result.status_code == 403
