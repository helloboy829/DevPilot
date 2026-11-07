"""Synthetic-only regressions for one outbound boundary across evaluation entry points."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.evaluation import http as outbound
from app.gateway.auth.models import User
from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED
from app.gateway.authz import AuthContext, Permissions
from app.gateway.deps import get_config
from app.gateway.routers import component_tests


@pytest.mark.asyncio
async def test_transport_pins_every_request_and_preserves_tls_identity(monkeypatch):
    inner = SimpleNamespace(handle_async_request=AsyncMock(return_value=httpx.Response(200)), aclose=AsyncMock())
    constructor = Mock(return_value=inner)
    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", constructor)
    resolver = AsyncMock(side_effect=["93.184.216.34", "93.184.216.35"])
    monkeypatch.setattr(outbound, "resolve_destination", resolver)
    transport = outbound.PinnedEvaluationTransport(object(), "https://example.test/api")
    for ip in ("93.184.216.34", "93.184.216.35"):
        request = httpx.Request("POST", "https://example.test:443/api?q=synthetic", headers={"Host": "attacker.test"})
        await transport.handle_async_request(request)
        assert request.url.host == ip
        assert request.headers["host"] == "example.test"
        assert request.extensions["sni_hostname"] == "example.test"
        assert request.url.query == b"q=synthetic"
    assert resolver.await_count == 2
    constructor.assert_called_once_with(verify=True, trust_env=False, retries=0)
    await transport.aclose()
    inner.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://example.test/api", "https://other.test/api", "https://example.test:8443/api", "https://user:synthetic@example.test/api"])
async def test_transport_cannot_change_origin_or_embed_credentials(monkeypatch, url):
    inner = SimpleNamespace(handle_async_request=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", Mock(return_value=inner))
    resolver = AsyncMock(return_value="93.184.216.34")
    monkeypatch.setattr(outbound, "resolve_destination", resolver)
    transport = outbound.PinnedEvaluationTransport(object(), "https://example.test/api")
    with pytest.raises(ValueError):
        await transport.handle_async_request(httpx.Request("POST", url))
    resolver.assert_not_awaited()
    inner.handle_async_request.assert_not_awaited()
    await transport.aclose()


@pytest.mark.asyncio
async def test_transport_rechecks_policy_at_send_time(monkeypatch):
    inner = SimpleNamespace(handle_async_request=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", Mock(return_value=inner))
    monkeypatch.setattr(outbound, "resolve_destination", AsyncMock(side_effect=ValueError("Denied")))
    transport = outbound.PinnedEvaluationTransport(object(), "https://example.test/api")
    with pytest.raises(ValueError):
        await transport.handle_async_request(httpx.Request("POST", "https://example.test/api"))
    inner.handle_async_request.assert_not_awaited()
    await transport.aclose()


def test_factory_disables_redirects_proxy_environment_and_insecure_tls(monkeypatch):
    transport = Mock()
    monkeypatch.setattr(outbound, "PinnedEvaluationTransport", Mock(return_value=transport))
    constructor = Mock()
    monkeypatch.setattr(outbound.httpx, "AsyncClient", constructor)
    outbound.evaluation_client(object(), "https://example.test/api", timeout_seconds=12)
    options = constructor.call_args.kwargs
    assert options["transport"] is transport
    assert options["trust_env"] is False
    assert options["follow_redirects"] is False
    assert options["timeout"] == 12


def manual_api(monkeypatch, *, permissions=None, component=None):
    user = User(id=uuid4(), email="synthetic@example.com", password_hash="x", system_role="user")
    app = FastAPI()

    @app.middleware("http")
    async def auth(request: Request, call_next):
        request.state.user = user
        request.state.auth_source = AUTH_SOURCE_AUTH_DISABLED
        request.state.auth = AuthContext(user=user, permissions=permissions if permissions is not None else [Permissions.THREADS_WRITE, Permissions.RUNS_CREATE])
        return await call_next(request)

    repo = SimpleNamespace(get=AsyncMock(return_value=component if component is not None else {"id": "synthetic", "api_url": "https://example.test/api", "enabled": True}))
    runs = SimpleNamespace(create=AsyncMock(return_value={"id": "run-synthetic"}))
    service = SimpleNamespace(enqueue=Mock())
    monkeypatch.setattr(component_tests, "get_component_repo", lambda request: repo)
    monkeypatch.setattr(component_tests, "get_component_test_run_repo", lambda request: runs)
    monkeypatch.setattr(component_tests, "get_component_test_service", lambda request: service)
    app.dependency_overrides[get_config] = lambda: SimpleNamespace(evaluation_http={"allowed_hosts": []})
    app.include_router(component_tests.router)
    return TestClient(app), repo, runs, service, str(user.id)


def test_manual_run_requires_runs_create_permission(monkeypatch):
    client, _, runs, service, _ = manual_api(monkeypatch, permissions=[Permissions.THREADS_WRITE])
    response = client.post("/api/component-tests/components/synthetic/runs", json={"test_type": "perf", "params": {}})
    assert response.status_code == 403
    runs.create.assert_not_awaited()
    service.enqueue.assert_not_called()


def test_manual_run_denies_unapproved_host_before_admission(monkeypatch):
    client, _, runs, service, _ = manual_api(monkeypatch)
    response = client.post("/api/component-tests/components/synthetic/runs", json={"test_type": "effect", "params": {}})
    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]
    runs.create.assert_not_awaited()
    service.enqueue.assert_not_called()


def test_manual_run_dns_error_is_private_and_does_not_queue(monkeypatch):
    monkeypatch.setattr(component_tests, "resolve_destination", AsyncMock(side_effect=OSError("synthetic-secret")), raising=False)
    client, _, runs, service, _ = manual_api(monkeypatch)
    response = client.post("/api/component-tests/components/synthetic/runs", json={"test_type": "perf", "params": {}})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
    assert "no-store" in response.headers["cache-control"]
    runs.create.assert_not_awaited()
    service.enqueue.assert_not_called()


def test_manual_run_uses_owner_scoped_component_and_checks_policy(monkeypatch):
    resolve = AsyncMock(return_value="93.184.216.34")
    monkeypatch.setattr(component_tests, "resolve_destination", resolve, raising=False)
    client, repo, runs, service, owner = manual_api(monkeypatch)
    response = client.post("/api/component-tests/components/synthetic/runs", json={"test_type": "perf", "params": {}})
    assert response.status_code == 200
    repo.get.assert_awaited_once_with("synthetic", user_id=owner)
    resolve.assert_awaited_once()
    assert resolve.call_args.args[0].url == "https://example.test/api"
    assert runs.create.call_args.kwargs["user_id"] == owner
    assert service.enqueue.call_args.kwargs["user_id"] == owner


def test_manual_validation_does_not_echo_submitted_secrets(monkeypatch):
    client, _, runs, service, _ = manual_api(monkeypatch)
    response = client.post("/api/component-tests/components/synthetic/runs", json={"test_type": {"secret": "synthetic-secret"}})
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text
    assert "no-store" in response.headers["cache-control"]
    runs.create.assert_not_awaited()
    service.enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_default_component_execution_uses_shared_outbound_client(monkeypatch):
    from app.component_tests import service

    client = AsyncMock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(service, "evaluation_client", factory, raising=False)
    monkeypatch.setattr(service, "get_app_config", lambda: object(), raising=False)
    monkeypatch.setattr(service, "perf_run", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "perf_eval", lambda *args, **kwargs: object())
    monkeypatch.setattr(service, "build_component_test_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(service, "build_run_summary", lambda *args, **kwargs: {})
    runner = service.ComponentTestService(component_repo=AsyncMock(), run_repo=AsyncMock())
    runner._persist = AsyncMock(return_value="synthetic/raw.json")
    await runner._execute(run_id="synthetic", user_id="owner", component={"transport": "http_post", "api_url": "https://example.test/api"}, test_type="perf", params={})
    factory.assert_called_once()
    assert factory.call_args.args[1] == "https://example.test/api"
    client.aclose.assert_awaited_once()


@pytest.mark.parametrize("headers", [{"Host": "attacker.test"}, {"Content-Length": "0"}, {"Connection": "keep-alive"}, {"X-Test": "x\r\nInjected: value"}])
def test_manual_headers_use_request_spec_validation(headers):
    from app.component_tests.service import ComponentTestService

    with pytest.raises(ValueError):
        ComponentTestService._build_config({"transport": "http_post", "api_url": "https://example.test"}, {"headers": headers})


def test_standalone_toolkit_never_disables_tls(monkeypatch):
    from devpilot.toolkit import transports

    constructor = Mock()
    monkeypatch.setattr(transports.httpx, "AsyncClient", constructor)
    transports._build_client(10)
    assert constructor.call_args.kwargs["verify"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("ips", [[], ["127.0.0.1"], ["169.254.169.254"], ["::1"], ["93.184.216.34", "10.0.0.1"], ["93.184.216.34", "169.254.169.254"]])
async def test_dns_checks_every_answer_not_only_first(monkeypatch, ips):
    import asyncio

    from devpilot.http import RequestSpec

    lookup = AsyncMock(return_value=[(2, 1, 6, "", (ip, 443)) for ip in ips])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    with pytest.raises(ValueError):
        await outbound.resolve_destination(RequestSpec(url="https://example.test"), SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]}))


@pytest.mark.asyncio
async def test_private_opt_in_still_cannot_reach_metadata(monkeypatch):
    import asyncio

    from devpilot.http import RequestSpec

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=[(2, 1, 6, "", ("169.254.169.254", 80))]))
    with pytest.raises(ValueError):
        await outbound.resolve_destination(RequestSpec(url="http://example.test"), SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"], "allow_private": True}))


@pytest.mark.asyncio
async def test_debugger_uses_shared_transport_without_following_redirects(monkeypatch):
    from devpilot.http import RequestSpec

    seen = []

    async def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://169.254.169.254", "set-cookie": "synthetic-cookie"}, text="Bearer synthetic-token")

    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handler))
    monkeypatch.setattr(outbound, "resolve_destination", AsyncMock(return_value="93.184.216.34"))
    result = await outbound.send_request(RequestSpec(url="https://example.test/api", headers=[["Authorization", "Bearer synthetic-token"]]), object())
    assert len(seen) == 1
    assert seen[0].url.host == "93.184.216.34"
    assert seen[0].extensions["sni_hostname"] == "example.test"
    assert result["status"] == 302
    assert result["redirects_followed"] is False
    assert "synthetic-token" not in result["body"]
    assert ["set-cookie", "[redacted]"] in result["headers"]


@pytest.mark.asyncio
async def test_debugger_keeps_response_limit_after_transport_unification(monkeypatch):
    from devpilot.http import RequestSpec

    monkeypatch.setattr(outbound.httpx, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 1048577)))
    monkeypatch.setattr(outbound, "resolve_destination", AsyncMock(return_value="93.184.216.34"))
    result = await outbound.send_request(RequestSpec(url="https://example.test"), object())
    assert result["truncated"] is True
    assert result["size_bytes"] == 1048576
    assert len(result["body"]) == 1048576
