"""Shared bounded single-attempt execution: synthetic I/O, no run authority."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError

import httpx
import pytest
from devpilot.pinned_http import EvaluationPolicyError
from devpilot.qa_json_attempt import AttemptLimits, AttemptObservation, collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest

VERSION = "qa-json-attempt.v1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("Synthetic attempt core cannot perform real DNS/socket I/O")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)


def request():
    return FrozenRequest(url="https://example.test/qa", method="POST", headers=(("Content-Type", "application/json"), ("Authorization", "SYNTHETIC_SECRET")), body='{"q":"only input"}')


class Body(httpx.AsyncByteStream):
    def __init__(self, chunks, *, error=None):
        self.chunks, self.error, self.closed = chunks, error, False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error

    async def aclose(self):
        self.closed = True


def client_factory(handler, trace):
    @asynccontextmanager
    async def factory(url, *, timeout_seconds):
        trace.append(("create", url, timeout_seconds))

        async def send(sent):
            trace.append(("send", sent.method, str(sent.url), sent.content, tuple(sent.headers.raw)))
            return await handler(sent)

        async with httpx.AsyncClient(transport=httpx.MockTransport(send), trust_env=False, follow_redirects=False, timeout=timeout_seconds) as client:
            try:
                yield client
            finally:
                trace.append(("close",))

    return factory


@pytest.mark.parametrize("version", [None, "", "qa-json-attempt.v2"])
@pytest.mark.asyncio
async def test_unknown_version_rejected_before_factory(version):
    def denied(*args, **kwargs):
        raise AssertionError("Must not create a client")

    with pytest.raises(ValueError):
        await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=denied, version=version)


@pytest.mark.parametrize("factory", [None, False, "httpx.AsyncClient"])
@pytest.mark.asyncio
async def test_factory_must_be_explicit_callable(factory):
    with pytest.raises(ValueError):
        await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=factory)


@pytest.mark.parametrize("invalid", ["request", "binding", "limits"])
@pytest.mark.asyncio
async def test_bad_input_rejected_before_factory(invalid):
    args = [request(), QAJSONBinding("/q", "/a"), AttemptLimits()]
    args[["request", "binding", "limits"].index(invalid)] = None

    def denied(*args, **kwargs):
        raise AssertionError("Must not create a client")

    with pytest.raises(ValueError):
        await collect_json_attempt(*args, client_factory=denied)


@pytest.mark.parametrize("status", [200, 299, 300, 400, 429, 500, 600])
@pytest.mark.asyncio
async def test_single_send_response_classification_and_close(status):
    trace = []
    body = Body([b'{"a":"SYNTHETIC_OUTPUT"}'])

    async def handle(sent):
        assert sent.headers["accept-encoding"] == "identity"
        return httpx.Response(status, headers={"content-type": "application/json"}, stream=body)

    result = await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=client_factory(handle, trace), version=VERSION)
    assert result.kind == ("output_collected" if status < 300 else "http_error")
    assert result.http_status == status and result.elapsed_ms >= 0
    assert result.output == ("SYNTHETIC_OUTPUT" if status < 300 else None)
    assert result.body_bytes == (24 if status < 300 else 0)
    assert [item[0] for item in trace] == ["create", "send", "close"] and body.closed
    assert trace[0] == ("create", "https://example.test/qa", 30)
    assert "SYNTHETIC" not in repr(result) and "example.test" not in repr(result)
    assert not hasattr(result, "passed") and not hasattr(result, "headers")
    with pytest.raises(FrozenInstanceError):
        result.kind = "passed"


@pytest.mark.parametrize(
    "error,kind",
    [
        (httpx.ConnectError("SYNTHETIC"), "delivery_unknown"),
        (httpx.ReadTimeout("SYNTHETIC"), "delivery_unknown"),
        (ValueError("SYNTHETIC"), "delivery_unknown"),
        (EvaluationPolicyError("SYNTHETIC"), "policy_rejected"),
    ],
)
@pytest.mark.asyncio
async def test_no_resend_or_error_detail_in_observation(error, kind):
    trace = []

    async def handle(sent):
        raise error

    result = await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=client_factory(handle, trace))
    assert result.kind == kind and result.output is None and result.http_status is None and result.body_bytes == 0
    assert [item[0] for item in trace] == ["create", "send", "close"]
    assert "SYNTHETIC" not in repr(result)


@pytest.mark.asyncio
async def test_unrecognized_error_identity_is_not_hidden():
    trace = []
    error = RuntimeError("synthetic implementation error")

    async def handle(sent):
        raise error

    with pytest.raises(RuntimeError) as caught:
        await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=client_factory(handle, trace))
    assert caught.value is error
    assert [item[0] for item in trace] == ["create", "send", "close"]


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_partial_stream_error_or_cancellation_never_extracts_complete_looking_json(cancel):
    entered = asyncio.Event()
    wait = asyncio.Event()
    trace = []

    class Interrupted(Body):
        async def __aiter__(self):
            yield b'{"a":"must not collect"}' + b" " * (16384 - len(b'{"a":"must not collect"}'))
            entered.set()
            await wait.wait()
            raise httpx.ReadError("SYNTHETIC_READ_ERROR")

    body = Interrupted([])

    async def handle(sent):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    task = asyncio.create_task(collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(max_response_bytes=32768), client_factory=client_factory(handle, trace)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            wait.set()
            result = await task
            assert result.kind == "delivery_unknown" and result.output is None and result.body_bytes == 16384 and result.http_status == 200
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert body.closed and [item[0] for item in trace] == ["create", "send", "close"]


def test_app_reexports_same_observation_identity():
    from app.evaluation import qa_attempts

    assert qa_attempts.AttemptLimits is AttemptLimits and qa_attempts.AttemptObservation is AttemptObservation


@pytest.mark.parametrize(
    "kwargs",
    [{"timeout_ms": True}, {"timeout_ms": 99}, {"timeout_ms": 300001}, {"timeout_ms": 100.0}, {"max_response_bytes": False}, {"max_response_bytes": 0}, {"max_response_bytes": 1048577}, {"max_response_bytes": "1024"}],
)
def test_limits_remain_strict_and_bounded(kwargs):
    with pytest.raises(ValueError, match="^Invalid attempt limits$"):
        AttemptLimits(**kwargs)


@pytest.mark.parametrize("corrupt", ["request", "binding", "limits"])
@pytest.mark.asyncio
async def test_defensive_snapshot_validation_precedes_client(corrupt):
    frozen, binding, limits = request(), QAJSONBinding("/q", "/a"), AttemptLimits()
    if corrupt == "request":
        object.__setattr__(frozen, "body", 123)
    elif corrupt == "binding":
        object.__setattr__(binding, "output_pointer", "not-a-pointer")
    else:
        object.__setattr__(limits, "timeout_ms", True)

    def denied(*args, **kwargs):
        raise AssertionError("Must validate before creating any client")

    with pytest.raises(ValueError):
        await collect_json_attempt(frozen, binding, limits, client_factory=denied)


@pytest.mark.parametrize("stage", ["create", "enter", "exit"])
@pytest.mark.asyncio
async def test_client_lifecycle_errors_are_unknown_not_resend(stage):
    trace = []
    body = Body([b'{"a":"must discard on exit error"}'])

    async def handle(sent):
        trace.append("send")
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    @asynccontextmanager
    async def context():
        trace.append("enter")
        if stage == "enter":
            raise httpx.ConnectError("SYNTHETIC_ENTER")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=False, trust_env=False) as client:
            try:
                yield client
            finally:
                trace.append("close")
        raise httpx.ReadError("SYNTHETIC_EXIT")

    def factory(url, *, timeout_seconds):
        trace.append("create")
        if stage == "create":
            raise ValueError("SYNTHETIC_CREATE")
        return context()

    result = await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=factory)
    assert result.kind == "delivery_unknown" and result.output is None
    assert trace == {"create": ["create"], "enter": ["create", "enter"], "exit": ["create", "enter", "send", "close"]}[stage]
    if stage == "exit":
        assert body.closed and result.http_status == 200 and result.body_bytes == len(body.chunks[0])
    else:
        assert result.http_status is None and result.body_bytes == 0


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_timeout_and_cancellation_include_client_enter_cleanup(cancel):
    entered = asyncio.Event()
    trace = []

    @asynccontextmanager
    async def factory(url, *, timeout_seconds):
        trace.append(("enter", timeout_seconds))
        entered.set()
        try:
            await asyncio.Event().wait()
            yield None
        finally:
            trace.append(("drained",))

    task = asyncio.create_task(collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(timeout_ms=100), client_factory=factory))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=2)
            assert result.kind == "delivery_unknown" and result.output is None and result.http_status is None
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert trace == [("enter", 0.1), ("drained",)]


@pytest.mark.asyncio
async def test_cancellation_waits_for_response_close_without_retry():
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    trace = []

    class WaitingBody(Body):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"never"

        async def aclose(self):
            closing.set()
            await release.wait()
            self.closed = True

    body = WaitingBody([])

    async def handle(sent):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    task = asyncio.create_task(collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=client_factory(handle, trace)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        await asyncio.wait_for(closing.wait(), timeout=2)
        assert not task.done() and not body.closed
        assert [item[0] for item in trace] == ["create", "send"]
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert body.closed and [item[0] for item in trace] == ["create", "send", "close"]


@pytest.mark.asyncio
async def test_cancelled_offloop_decode_cannot_publish_output(monkeypatch):
    import threading

    from devpilot.qa_json_response import QAJSONResponseBuffer

    loop = asyncio.get_running_loop()
    entered, release, drained = asyncio.Event(), threading.Event(), threading.Event()
    finish = QAJSONResponseBuffer.finish
    trace = []
    body = Body([b'{"a":"cancelled output"}'])

    def blocked_finish(self):
        assert threading.current_thread() is not threading.main_thread()
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(timeout=2), "Test must release the parser thread"
            return finish(self)
        finally:
            drained.set()

    monkeypatch.setattr(QAJSONResponseBuffer, "finish", blocked_finish)

    async def handle(sent):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    task = asyncio.create_task(collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits(), client_factory=client_factory(handle, trace)))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert body.closed and [item[0] for item in trace] == ["create", "send", "close"]
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(drained.wait, 2), "Parser thread must not escape test teardown"


@pytest.mark.asyncio
async def test_shared_source_import_and_mock_attempt_without_business_dependencies():
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """import asyncio,importlib.abc,socket,sys
sys.path.insert(0,sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','sqlalchemy','fastapi','openpyxl'}:raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
def denied(*args,**kwargs):raise AssertionError('real network')
socket.getaddrinfo=denied;socket.socket.connect=denied;socket.socket.connect_ex=denied;socket.socket.sendto=denied
import httpx
from devpilot.qa_json_attempt import AttemptLimits,collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):yield b'{"a":"synthetic"}'
 async def aclose(self):pass
async def main():
 calls=[]
 async def send(request):
  calls.append(request)
  assert request.content==b'{"q":"input"}' and request.headers['accept-encoding']=='identity'
  return httpx.Response(200,headers={'content-type':'application/json'},stream=Body())
 def factory(url,*,timeout_seconds):
  assert url=='https://example.test' and timeout_seconds==30
  return httpx.AsyncClient(transport=httpx.MockTransport(send),trust_env=False,follow_redirects=False,timeout=timeout_seconds)
 result=await collect_json_attempt(FrozenRequest(url='https://example.test',method='POST',headers=(),body='{"q":"input"}'),QAJSONBinding('/q','/a'),AttemptLimits(),client_factory=factory)
 assert result.kind=='output_collected' and result.output=='synthetic' and len(calls)==1
 print('qa-json-attempt.v1')
asyncio.run(main())
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", script, str(source)], cwd=source.parent, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION


@pytest.mark.asyncio
async def test_no_implicit_default_client_factory():
    with pytest.raises(TypeError):
        await collect_json_attempt(request(), QAJSONBinding("/q", "/a"), AttemptLimits())
