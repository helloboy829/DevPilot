"""Synthetic, offline single-attempt collection; not run admission or grading."""

import asyncio
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import httpx
import pytest
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest

from app.evaluation import qa_attempts as attempts
from app.evaluation.http import EvaluationPolicyError


@pytest.fixture
def request_definition():
    return FrozenRequest(url="https://example.test/qa", method="POST", headers=(("Content-Type", "application/json"), ("Authorization", "Bearer SYNTHETIC_SECRET")), body='{"q":"only the input"}')


@pytest.fixture
def binding():
    return QAJSONBinding(input_pointer="/q", output_pointer="/a")


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks, self.delay, self.closed = chunks, delay, False

    async def __aiter__(self):
        for chunk in self.chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def install_client(monkeypatch, handler):
    calls = []

    async def wrapped(request):
        calls.append(request)
        return await handler(request)

    def client(config, url, *, timeout_seconds=30):
        return httpx.AsyncClient(transport=httpx.MockTransport(wrapped), follow_redirects=False, trust_env=False, timeout=timeout_seconds)

    monkeypatch.setattr(attempts, "evaluation_client", client)
    return calls


@pytest.mark.asyncio
async def test_collects_internal_output_without_verdict_or_secrets_in_repr(monkeypatch, request_definition, binding):
    body = Body([b'{"a":"SYNTHETIC_OUTPUT"}'])

    async def handle(request):
        assert request.method == "POST"
        assert request.headers["accept-encoding"] == "identity"
        assert request.content == b'{"q":"only the input"}'
        assert request.headers["authorization"] == "Bearer SYNTHETIC_SECRET"
        return httpx.Response(200, headers={"content-type": "application/json; charset=utf-8", "set-cookie": "SYNTHETIC_SECRET"}, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, SimpleNamespace(), attempts.AttemptLimits(timeout_ms=1000, max_response_bytes=1024))
    assert result.kind == "output_collected"
    assert result.output == "SYNTHETIC_OUTPUT"
    assert result.http_status == 200 and result.body_bytes == 24
    assert result.elapsed_ms >= 0
    assert body.closed and len(calls) == 1
    assert "SYNTHETIC" not in repr(result) and "example.test" not in repr(result)
    assert not hasattr(result, "passed") and not hasattr(result, "ttft_ms")
    assert not hasattr(result, "headers") and not hasattr(result, "body")
    with pytest.raises(FrozenInstanceError):
        result.kind = "passed"


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 429, 500, 503])
@pytest.mark.asyncio
async def test_http_errors_are_not_followed_or_judged(monkeypatch, request_definition, binding, status):
    body = Body([b'{"a":"must not be collected"}'])

    async def handle(request):
        return httpx.Response(status, headers={"content-type": "application/json", "location": "https://second.test/"}, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits())
    assert result.kind == "http_error" and result.output is None and result.body_bytes == 0
    assert result.http_status == status and body.closed and len(calls) == 1


@pytest.mark.parametrize(
    "headers", [{}, {"content-type": "text/event-stream"}, {"content-type": "text/html"}, {"content-type": "application/json", "content-encoding": "gzip"}, {"content-type": "application/json", "content-encoding": "br"}]
)
@pytest.mark.asyncio
async def test_unsupported_content_is_closed_without_decoding(monkeypatch, request_definition, binding, headers):
    body = Body([b"not consumed"])

    async def handle(request):
        return httpx.Response(200, headers=headers, stream=body)

    install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits())
    assert result.kind == "unsupported_response" and result.output is None and result.body_bytes == 0 and body.closed


@pytest.mark.parametrize("content", [b'{"a":""}', b'{"a":"   "}', b'{"a":2}', b'{"other":"text"}', b'{"a":"one","a":"two"}', b'{"a":NaN}', b'{"a":"\xff"}', b"not json", b"{", b""])
@pytest.mark.asyncio
async def test_invalid_or_empty_output_is_not_usable_evidence(monkeypatch, request_definition, binding, content):
    body = Body([content])

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits())
    assert result.kind == "invalid_output" and result.output is None and body.closed
    assert result.body_bytes == len(content)


@pytest.mark.parametrize("declared", [None, "1000", "nonsense"])
@pytest.mark.asyncio
async def test_response_byte_budget_fails_closed_even_without_honest_content_length(monkeypatch, request_definition, binding, declared):
    body = Body([b"x" * 50000])
    headers = {"content-type": "application/json"}
    if declared is not None:
        headers["content-length"] = declared

    async def handle(request):
        return httpx.Response(200, headers=headers, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits(max_response_bytes=16))
    assert result.kind == "response_limit" and result.output is None
    assert 0 <= result.body_bytes <= 17 and body.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_exact_budget_vendor_json_and_unicode_are_preserved(monkeypatch, request_definition, binding):
    content = '{"a":"答复"}'.encode()

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/vnd.example+json", "content-encoding": "identity"}, stream=Body([content[:7], content[7:]]))

    install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits(max_response_bytes=len(content)))
    assert result.kind == "output_collected" and result.output == "答复" and result.body_bytes == len(content)


@pytest.mark.parametrize("error", [httpx.ConnectError("SYNTHETIC_SECRET"), httpx.ReadError("SYNTHETIC_SECRET"), httpx.ReadTimeout("SYNTHETIC_SECRET"), ValueError("SYNTHETIC_SECRET")])
@pytest.mark.asyncio
async def test_transport_failure_is_unknown_delivery_never_automatically_retried(monkeypatch, request_definition, binding, error):
    async def handle(request):
        raise error

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits())
    assert result.kind == "delivery_unknown" and result.output is None and len(calls) == 1
    assert "SYNTHETIC_SECRET" not in repr(result)


@pytest.mark.asyncio
async def test_total_attempt_timeout_covers_slow_body_and_closes(monkeypatch, request_definition, binding):
    body = Body([b'{"a":"text"}'], delay=1)

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits(timeout_ms=100))
    assert result.kind == "delivery_unknown" and body.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_closes_and_does_not_retry(monkeypatch, request_definition, binding):
    started = asyncio.Event()
    body = Body([b"later"], delay=10)

    async def handle(request):
        started.set()
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    calls = install_client(monkeypatch, handle)
    task = asyncio.create_task(attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits()))
    await started.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert body.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_real_default_outbound_policy_denies_before_dns(monkeypatch, request_definition, binding):
    async def forbidden(*args, **kwargs):
        pytest.fail("Default-denied host must never resolve or send")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", forbidden)
    result = await attempts.collect_json_attempt(request_definition, binding, SimpleNamespace(), attempts.AttemptLimits())
    assert result.kind == "policy_rejected" and result.http_status is None and result.body_bytes == 0


@pytest.mark.parametrize("kwargs", [{"timeout_ms": True}, {"timeout_ms": 99}, {"timeout_ms": 300001}, {"timeout_ms": 100.0}, {"max_response_bytes": 0}, {"max_response_bytes": 1048577}, {"max_response_bytes": "1024"}])
def test_strict_attempt_limits(kwargs):
    with pytest.raises(ValueError, match="Invalid attempt limits"):
        attempts.AttemptLimits(**kwargs)


def test_policy_error_remains_compatible_with_existing_value_error_callers():
    assert issubclass(EvaluationPolicyError, ValueError)


@pytest.mark.asyncio
async def test_partial_transport_failure_keeps_consumed_byte_count_without_response_body(monkeypatch, request_definition, binding):
    class FailingBody(Body):
        async def __aiter__(self):
            yield b"x" * 16384
            raise httpx.ReadError("SYNTHETIC_SECRET")

    body = FailingBody([])

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request_definition, binding, None, attempts.AttemptLimits())
    assert result.kind == "delivery_unknown" and result.body_bytes == 16384
    assert result.output is None and body.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_explicit_encoding_header_is_not_silently_changed(monkeypatch, request_definition, binding):
    request = FrozenRequest(url=request_definition.url, method=request_definition.method, headers=(*request_definition.headers, ("Accept-Encoding", "gzip")), body=request_definition.body)

    async def handle(sent):
        assert sent.headers["accept-encoding"] == "gzip"
        return httpx.Response(200, headers={"content-type": "application/json", "content-encoding": "gzip"}, stream=Body([b"compressed"]))

    install_client(monkeypatch, handle)
    result = await attempts.collect_json_attempt(request, binding, None, attempts.AttemptLimits())
    assert result.kind == "unsupported_response" and request.headers[-1] == ("Accept-Encoding", "gzip")
