"""HTTP boundaries use only synthetic data and mock all outbound execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
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


def mock_model_http(monkeypatch, module, handler):
    client_options = []

    def create_client(**kwargs):
        client_options.append(kwargs)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(
        module,
        "httpx",
        SimpleNamespace(AsyncClient=create_client, Timeout=httpx.Timeout),
        raising=False,
    )
    return client_options


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


def test_insecure_tls_send_requires_separate_consent_and_is_one_shot(monkeypatch):
    send = AsyncMock(return_value={"status": 200, "body": "synthetic"})
    monkeypatch.setattr(request_debugger, "send_request", send)
    client = api(request_debugger.router)
    body = {"spec": {"url": "https://example.test"}, "consent": True, "insecure_tls": True}

    denied = client.post("/api/component-tests/debug/send", json=body)
    assert denied.status_code == 422
    assert "one-time consent" in denied.text
    send.assert_not_awaited()

    allowed = client.post("/api/component-tests/debug/send", json=body | {"insecure_tls_consent": True})
    assert allowed.status_code == 200
    send.assert_awaited_once()
    assert send.await_args.kwargs["insecure_tls"] is True


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


@pytest.mark.parametrize(
    ("provider", "base_url", "expected_url", "auth_header", "payload", "expected_id", "expected_display_name"),
    [
        (
            "openai_compatible",
            "https://relay.example/v1",
            "https://relay.example/v1/models",
            "authorization",
            {"data": [{"id": "relay-chat", "name": "Relay Chat"}]},
            "relay-chat",
            "Relay Chat",
        ),
        (
            "openai_responses",
            "https://relay.example/v1",
            "https://relay.example/v1/models",
            "authorization",
            {"data": [{"id": "relay-responses"}]},
            "relay-responses",
            "relay-responses",
        ),
        (
            "anthropic",
            "https://relay.example",
            "https://relay.example/v1/models",
            "x-api-key",
            {"data": [{"id": "claude-custom", "display_name": "Claude Custom"}]},
            "claude-custom",
            "Claude Custom",
        ),
        (
            "gemini",
            "https://relay.example",
            "https://relay.example/v1beta/models",
            "x-goog-api-key",
            {"models": [{"name": "models/gemini-custom", "displayName": "Gemini Custom"}]},
            "gemini-custom",
            "Gemini Custom",
        ),
    ],
)
def test_model_discovery_uses_protocol_listing_and_returns_only_public_ids(tmp_path, monkeypatch, provider, base_url, expected_url, auth_header, payload, expected_id, expected_display_name):
    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    client_options = mock_model_http(monkeypatch, model_management, respond)
    client = api(model_management.router)
    body = {
        "provider": provider,
        "base_url": base_url,
        "profile_name": "synthetic",
        "api_key": "synthetic-secret",
        "consent": True,
    }

    response = client.post("/api/model-management/models/discover", json=body)

    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json() == {
        "models": [
            {
                "id": expected_id,
                "display_name": expected_display_name,
            }
        ],
        "truncated": False,
    }
    assert "synthetic-secret" not in response.text
    assert len(requests) == 1
    assert str(requests[0].url) == expected_url
    if auth_header == "authorization":
        assert requests[0].headers[auth_header] == "Bearer synthetic-secret"
    else:
        assert requests[0].headers[auth_header] == "synthetic-secret"
    assert "synthetic-secret" not in str(requests[0].url)
    assert client_options[0]["follow_redirects"] is False
    assert client_options[0]["trust_env"] is False
    if provider == "anthropic":
        assert requests[0].headers["anthropic-version"] == "2023-06-01"


def test_model_discovery_requires_admin_and_explicit_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    body = {
        "provider": "openai_compatible",
        "base_url": "https://relay.example/v1",
        "api_key": "synthetic-secret",
        "consent": True,
    }
    anonymous = api(model_management.router, authenticated=False)
    non_admin = api(model_management.router, role="user")
    admin = api(model_management.router)

    assert anonymous.post("/api/model-management/models/discover", json=body).status_code == 401
    assert non_admin.post("/api/model-management/models/discover", json=body).status_code == 403
    assert admin.post("/api/model-management/models/discover", json=body | {"consent": False}).status_code == 422
    assert admin.post("/api/model-management/models/discover", json=body | {"extra": "synthetic-secret"}).status_code == 422


def test_model_discovery_reuses_only_matching_saved_credentials(tmp_path, monkeypatch):
    from deerflow.config.managed_models import ManagedModel, ModelCatalog

    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    ModelCatalog(tmp_path).save_model(
        ManagedModel(
            name="saved",
            provider="openai_compatible",
            model="old-id",
            base_url="https://relay.example/v1",
            api_key="stored-secret",
        ),
        actor="synthetic-admin",
    )
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "relay-chat"}]})

    mock_model_http(monkeypatch, model_management, respond)
    client = api(model_management.router)
    matching = {
        "provider": "openai_compatible",
        "base_url": "https://relay.example/v1",
        "profile_name": "saved",
        "consent": True,
    }
    assert client.post("/api/model-management/models/discover", json=matching).status_code == 200
    assert requests[0].headers["authorization"] == "Bearer stored-secret"

    changed = matching | {"base_url": "https://other.example/v1"}
    response = client.post("/api/model-management/models/discover", json=changed)
    assert response.status_code == 409
    assert "stored-secret" not in response.text
    assert len(requests) == 1


@pytest.mark.parametrize("response_status", [302, 401])
def test_model_discovery_does_not_follow_redirects_or_return_provider_errors(tmp_path, monkeypatch, response_status):
    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(response_status, headers={"location": "https://other.example/models"}, json={"error": "synthetic-secret"})

    mock_model_http(monkeypatch, model_management, respond)
    response = api(model_management.router).post(
        "/api/model-management/models/discover",
        json={"provider": "openai_compatible", "base_url": "https://relay.example/v1", "api_key": "synthetic-secret", "consent": True},
    )

    assert response.status_code == 502
    assert "synthetic-secret" not in response.text
    assert len(requests) == 1


def test_model_discovery_limits_response_and_option_count(tmp_path, monkeypatch):
    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": f"relay-{index}"} for index in range(101)]})

    mock_model_http(monkeypatch, model_management, respond)
    response = api(model_management.router).post(
        "/api/model-management/models/discover",
        json={"provider": "openai_compatible", "base_url": "https://relay.example/v1", "consent": True},
    )

    assert response.status_code == 200
    assert len(response.json()["models"]) == 100
    assert response.json()["truncated"] is True
    assert len(requests) == 1

    monkeypatch.setattr(model_management, "_MAX_MODEL_LIST_BYTES", 16)
    oversized = api(model_management.router).post(
        "/api/model-management/models/discover",
        json={"provider": "openai_compatible", "base_url": "https://relay.example/v1", "consent": True},
    )
    assert oversized.status_code == 502
    assert "relay-" not in oversized.text


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
