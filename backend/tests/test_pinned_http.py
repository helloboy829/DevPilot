"""Shared DNS-pinned transport: synthetic I/O only, no execution authority."""

import asyncio
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from devpilot.http import RequestSpec
from devpilot.pinned_http import EvaluationPolicyError, PinnedHTTPTransport

from app.evaluation import http as outbound


def inner_transport(monkeypatch, *, handler=None):
    inner = SimpleNamespace(handle_async_request=AsyncMock(side_effect=handler, return_value=httpx.Response(200)), aclose=AsyncMock())
    constructor = Mock(return_value=inner)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", constructor)
    return inner, constructor


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Synthetic transport tests cannot use real DNS/socket I/O")

    import socket

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,ip",
    [
        ("https://example.test/a%2Fb?q=one+two&q=%2f", "93.184.216.34"),
        ("http://example.test:8080/a?empty=", "93.184.216.35"),
        ("https://example.test:8443/path", "2606:4700:4700::1111"),
        ("https://[2606:4700:4700::1111]:8443/a?q=x", "2606:4700:4700::1001"),
    ],
)
async def test_version_exact_wire_projection_and_tls_identity(monkeypatch, url, ip):
    inner, constructor = inner_transport(monkeypatch)
    resolver = AsyncMock(return_value=ip)
    transport = PinnedHTTPTransport(url, resolver)
    sent = httpx.Request("POST", url, headers=[("Host", "attacker.test"), ("X-Case", "one"), ("X-Case", "two")], content=b'{ "q": "literal" }', extensions={"sni_hostname": "attacker.test", "synthetic": True})
    original = sent.url
    await transport.handle_async_request(sent)
    assert transport.version == "pinned-http.v1"
    assert sent.url.host == ip and sent.url.scheme == original.scheme and sent.url.port == original.port
    assert sent.url.raw_path == original.raw_path and sent.content == b'{ "q": "literal" }'
    assert sent.headers["host"] == original.netloc.decode("ascii")
    assert sent.headers.get_list("x-case") == ["one", "two"]
    assert sent.extensions["sni_hostname"] == original.host and sent.extensions["synthetic"] is True
    assert resolver.call_args.args == (RequestSpec(url=str(original)),)
    constructor.assert_called_once_with(verify=True, trust_env=False, retries=0)
    inner.handle_async_request.assert_awaited_once_with(sent)
    await transport.aclose()
    inner.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_each_send_resolves_again_and_policy_changes_are_not_cached(monkeypatch):
    inner, _ = inner_transport(monkeypatch)
    resolver = AsyncMock(side_effect=["93.184.216.34", "93.184.216.35", EvaluationPolicyError("Denied")])
    transport = PinnedHTTPTransport("https://example.test/a", resolver)
    for ip in ("93.184.216.34", "93.184.216.35"):
        sent = httpx.Request("POST", "https://example.test/b")
        await transport.handle_async_request(sent)
        assert sent.url.host == ip
    with pytest.raises(EvaluationPolicyError):
        await transport.handle_async_request(httpx.Request("POST", "https://example.test/c"))
    assert resolver.await_count == 3 and inner.handle_async_request.await_count == 2
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://example.test/a", "https://other.test/a", "https://example.test:8443/a", "https://user:secret@example.test/a", "https://example.test/a#fragment"])
async def test_origin_or_url_violation_precedes_resolver_and_inner(monkeypatch, url):
    inner, _ = inner_transport(monkeypatch)
    resolver = AsyncMock(return_value="93.184.216.34")
    transport = PinnedHTTPTransport("https://example.test/a", resolver)
    with pytest.raises(ValueError):
        await transport.handle_async_request(httpx.Request("GET", url))
    resolver.assert_not_awaited()
    inner.handle_async_request.assert_not_awaited()
    await transport.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [None, True, 123, b"93.184.216.34", "", "other.test", "93.184.216.34:443", "[::1]", "fe80::1%eth0", "2606:4700::1%synthetic", " 93.184.216.34", "999.1.1.1"])
async def test_resolver_must_yield_literal_unscoped_ip_without_second_dns(monkeypatch, address):
    inner, _ = inner_transport(monkeypatch)
    resolver = AsyncMock(return_value=address)
    transport = PinnedHTTPTransport("https://example.test/a", resolver)
    sent = httpx.Request("GET", "https://example.test/a")
    with pytest.raises(EvaluationPolicyError, match="^Invalid resolved destination$"):
        await transport.handle_async_request(sent)
    assert sent.url.host == "example.test"
    inner.handle_async_request.assert_not_awaited()
    await transport.aclose()


@pytest.mark.parametrize(
    "url,resolver,version",
    [("https://user:secret@example.test", AsyncMock(), "pinned-http.v1"), ("file:///private", AsyncMock(), "pinned-http.v1"), ("https://example.test", None, "pinned-http.v1"), ("https://example.test", AsyncMock(), "latest")],
)
def test_invalid_constructor_does_not_create_http_transport(monkeypatch, url, resolver, version):
    _, constructor = inner_transport(monkeypatch)
    with pytest.raises(ValueError):
        PinnedHTTPTransport(url, resolver, version=version)
    constructor.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["resolve", "send"])
@pytest.mark.parametrize("error", [EvaluationPolicyError("synthetic denial"), TimeoutError("synthetic timeout"), httpx.ReadTimeout("synthetic read"), asyncio.CancelledError()])
async def test_errors_and_cancellation_propagate_without_retry_and_client_closes(monkeypatch, stage, error):
    inner, _ = inner_transport(monkeypatch)
    resolver = AsyncMock(return_value="93.184.216.34")
    if stage == "resolve":
        resolver.side_effect = error
    else:
        inner.handle_async_request.side_effect = error
    transport = PinnedHTTPTransport("https://example.test/a", resolver)
    with pytest.raises(type(error)) as raised:
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False) as client:
            await client.get("https://example.test/a")
    assert raised.value is error
    resolver.assert_awaited_once()
    assert inner.handle_async_request.await_count == (stage == "send")
    inner.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_app_adapter_uses_same_core_and_live_operator_policy(monkeypatch):
    inner, _ = inner_transport(monkeypatch)
    config = SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]})
    loop = asyncio.get_running_loop()
    lookup = AsyncMock(return_value=[(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    transport = outbound.PinnedEvaluationTransport(config, "https://example.test/a")
    assert isinstance(transport, PinnedHTTPTransport)
    assert outbound.EvaluationPolicyError is EvaluationPolicyError
    assert transport.config is config
    await transport.handle_async_request(httpx.Request("GET", "https://example.test/a"))
    config.evaluation_http["allowed_hosts"] = []
    with pytest.raises(outbound.EvaluationPolicyError):
        await transport.handle_async_request(httpx.Request("GET", "https://example.test/a"))
    lookup.assert_awaited_once()
    inner.handle_async_request.assert_awaited_once()
    await transport.aclose()


@pytest.mark.asyncio
async def test_cancellation_while_resolving_never_reaches_inner(monkeypatch):
    inner, _ = inner_transport(monkeypatch)
    entered = asyncio.Event()
    drained = asyncio.Event()

    async def resolve(spec):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()

    transport = PinnedHTTPTransport("https://example.test", resolve)
    async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False) as client:
        task = asyncio.create_task(client.get("https://example.test"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert drained.is_set()
    inner.handle_async_request.assert_not_awaited()
    inner.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_shared_source_import_and_mock_send_without_app_or_harness():
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """import asyncio,importlib.abc,sys,socket
sys.path.insert(0,sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','openpyxl'}:raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('real network')
socket.getaddrinfo=denied;socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.socket.sendto=denied
import httpx
from devpilot.pinned_http import PinnedHTTPTransport
async def main():
 async def resolve(spec):return '93.184.216.34'
 async def handle(request):
  assert request.url.host=='93.184.216.34' and request.headers['host']=='example.test'
  assert request.extensions['sni_hostname']=='example.test'
  return httpx.Response(200,json={'a':'synthetic'})
 transport=PinnedHTTPTransport('https://example.test',resolve)
 await transport.inner.aclose()
 transport.inner=httpx.MockTransport(handle)
 async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False) as client:
  response=await client.get('https://example.test')
  assert response.json()=={'a':'synthetic'}
 print(transport.version)
asyncio.run(main())
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", script, str(source)], cwd=source.parent, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "pinned-http.v1"
