"""Complete bounded run orchestration: synthetic capabilities, never authority."""

import asyncio
import threading
from dataclasses import FrozenInstanceError

import pytest
from devpilot.qa_json_attempt import AttemptObservation
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits, JSONRunStopped, run_json_attempts
from devpilot.request_versions import FrozenRequest

VERSION = "qa-json-run.v1"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket

    def denied(*args, **kwargs):
        raise AssertionError("Synthetic run cannot perform real DNS/socket I/O")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)


def request():
    return FrozenRequest(url="https://example.test/qa", method="POST", headers=(("Authorization", "SYNTHETIC_SECRET"),), body='{"q":""}')


def limits(**changes):
    return JSONRunLimits(**{"request_count": 4, "concurrency": 1, "timeout_ms": 30000, "deadline_ms": 61000, "max_response_bytes": 128, **changes})


class Hooks:
    def __init__(self):
        self.now = 1000
        self.trace = []
        self.active = 0
        self.maximum_active = 0
        self.ordinal = {}

    def now_ms(self):
        return self.now

    async def reserve(self, ordinal, body_bytes):
        assert type(ordinal) is int and ordinal >= 1
        assert ordinal not in self.ordinal
        self.trace.append(("reserve", ordinal, body_bytes))
        self.ordinal[ordinal] = object()
        return ordinal

    async def collect(self, spec, binding, attempt_limits):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.trace.append(("collect", spec.body, attempt_limits.timeout_ms))
        try:
            await asyncio.sleep(0)
            return AttemptObservation("output_collected", 200, 8, 1, "synthetic output")
        finally:
            self.active -= 1

    async def record(self, ticket, observation):
        assert ticket in self.ordinal and isinstance(observation, AttemptObservation)
        self.trace.append(("record", ticket, observation.kind))
        await asyncio.sleep(0)

    async def check_active(self):
        return True

    def kwargs(self):
        return {"now_ms": self.now_ms, "reserve_attempt": self.reserve, "collect_attempt": self.collect, "record_attempt": self.record, "check_active": self.check_active}


async def run(hooks, configured=None, **changes):
    return await run_json_attempts(request(), QAJSONBinding("/q", "/a"), ("first", "second"), configured or limits(), **{**hooks.kwargs(), **changes})


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_count", 0),
        ("request_count", 10001),
        ("request_count", True),
        ("concurrency", 0),
        ("concurrency", 65),
        ("concurrency", 1.0),
        ("timeout_ms", 99),
        ("timeout_ms", 300001),
        ("timeout_ms", False),
        ("deadline_ms", 0),
        ("deadline_ms", 1.0),
        ("max_response_bytes", 0),
        ("max_response_bytes", 1048577),
        ("max_response_bytes", True),
    ],
)
def test_strict_run_limits(field, value):
    with pytest.raises(ValueError, match="Invalid JSON run limits"):
        limits(**{field: value})


def test_limits_immutable_and_no_sensitive_snapshot():
    configured = limits()
    with pytest.raises(FrozenInstanceError):
        configured.request_count = 1
    assert not hasattr(configured, "request") and not hasattr(configured, "inputs")


@pytest.mark.parametrize("version", [None, "", "qa-json-run.v2"])
@pytest.mark.asyncio
async def test_unknown_version_rejected_without_callbacks(version):
    hooks = Hooks()
    with pytest.raises(ValueError):
        await run(hooks, version=version)
    assert hooks.trace == []


@pytest.mark.parametrize("name", ["now_ms", "reserve_attempt", "collect_attempt", "record_attempt", "check_active"])
@pytest.mark.asyncio
async def test_all_capabilities_explicit_and_callable(name):
    hooks = Hooks()
    with pytest.raises(ValueError):
        await run(hooks, **{name: None})
    assert hooks.trace == []
    args = hooks.kwargs()
    del args[name]
    with pytest.raises(TypeError):
        await run_json_attempts(request(), QAJSONBinding("/q", "/a"), ("first",), limits(), **args)
    assert hooks.trace == []


@pytest.mark.parametrize("inputs", [None, [], ["first"], (), (3,), ("first",) * 501, ("first",) * 5])
@pytest.mark.asyncio
async def test_invalid_or_uncovered_input_snapshot_rejected_before_callbacks(inputs):
    hooks = Hooks()
    with pytest.raises(ValueError):
        await run_json_attempts(request(), QAJSONBinding("/q", "/a"), inputs, limits(), **hooks.kwargs())
    assert hooks.trace == []


@pytest.mark.parametrize("index", [0, 1, 3])
@pytest.mark.asyncio
async def test_invalid_run_inputs_rejected_before_callbacks(index):
    hooks = Hooks()
    args = [request(), QAJSONBinding("/q", "/a"), ("first",), limits()]
    args[index] = None
    with pytest.raises(ValueError):
        await run_json_attempts(*args, **hooks.kwargs())
    assert hooks.trace == []


@pytest.mark.parametrize("concurrency", [1, 2, 4])
@pytest.mark.asyncio
async def test_complete_run_cycles_inputs_bounded_concurrency_and_records_every_ordinal(concurrency):
    hooks = Hooks()
    assert await run(hooks, limits(request_count=7, concurrency=concurrency)) is None
    assert hooks.active == 0 and hooks.maximum_active <= concurrency
    assert sorted(item[1] for item in hooks.trace if item[0] == "reserve") == list(range(1, 8))
    assert sorted(item[1] for item in hooks.trace if item[0] == "record") == list(range(1, 8))
    bodies = [item[1] for item in hooks.trace if item[0] == "collect"]
    assert bodies.count('{"q":"first"}') == 4 and bodies.count('{"q":"second"}') == 3
    assert all(item[2] == len(('{"q":"first"}' if item[1] % 2 else '{"q":"second"}').encode()) for item in hooks.trace if item[0] == "reserve")
    for ordinal in range(1, 8):
        reserved = next(i for i, item in enumerate(hooks.trace) if item[:2] == ("reserve", ordinal))
        recorded = next(i for i, item in enumerate(hooks.trace) if item[:2] == ("record", ordinal))
        assert reserved < recorded


@pytest.mark.asyncio
async def test_render_is_offloop_and_dispatch_ack_precedes_collect(monkeypatch):
    hooks = Hooks()
    original = QAJSONBinding.render
    entered, release = asyncio.Event(), asyncio.Event()
    threads = []

    def render(self, frozen, text):
        threads.append(threading.current_thread() is not threading.main_thread())
        return original(self, frozen, text)

    async def reserve(ordinal, body_bytes):
        entered.set()
        await release.wait()
        return await hooks.reserve(ordinal, body_bytes)

    monkeypatch.setattr(QAJSONBinding, "render", render)
    task = asyncio.create_task(run(hooks, reserve_attempt=reserve))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert hooks.trace == []
        release.set()
        await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert threads == [True] * 4
    assert [item[0] for item in hooks.trace] == ["reserve", "collect", "record"] * 4


@pytest.mark.parametrize("stage", ["reserve_attempt", "collect_attempt", "record_attempt"])
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_capability_error_propagates_without_retry(stage, cancel):
    hooks = Hooks()
    error = asyncio.CancelledError("synthetic") if cancel else RuntimeError("synthetic")

    async def fail(*args):
        raise error

    with pytest.raises(type(error)) as caught:
        await run(hooks, **{stage: fail})
    assert caught.value is error and hooks.active == 0
    assert len([item for item in hooks.trace if item[0] == "reserve"]) <= 1
    assert len([item for item in hooks.trace if item[0] == "collect"]) <= (0 if stage == "reserve_attempt" else 1)


@pytest.mark.parametrize("remaining", [99, 100, 1000, 50000])
@pytest.mark.asyncio
async def test_remaining_attempt_deadline_computed_only_after_dispatch_ack(remaining):
    hooks = Hooks()

    async def reserve(ordinal, body_bytes):
        ticket = await hooks.reserve(ordinal, body_bytes)
        hooks.now = 61000 - remaining
        return ticket

    if remaining < 100:
        with pytest.raises(JSONRunStopped):
            await run(hooks, reserve_attempt=reserve)
        assert [item[0] for item in hooks.trace] == ["reserve"]
    else:
        await run(hooks, reserve_attempt=reserve)
        assert [item[2] for item in hooks.trace if item[0] == "collect"] == [min(30000, remaining)] * 4


@pytest.mark.parametrize("kind", ["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"])
@pytest.mark.asyncio
async def test_technical_classifications_are_not_verdicts_or_retries(kind):
    hooks = Hooks()

    async def collect(spec, binding, attempt_limits):
        hooks.trace.append(("collect",))
        return AttemptObservation(kind, None, 0, 1, None)

    if kind == "delivery_unknown":
        with pytest.raises(JSONRunStopped):
            await run(hooks, collect_attempt=collect)
        assert len(hooks.ordinal) == 1
    else:
        assert await run(hooks, collect_attempt=collect) is None
        assert len(hooks.ordinal) == 4
    assert all(item[2] == kind for item in hooks.trace if item[0] == "record")


@pytest.mark.parametrize("cause", ["inactive", "deadline", "error"])
@pytest.mark.asyncio
async def test_monitor_stops_consumers_and_waits_for_cleanup(cause):
    hooks = Hooks()
    entered, closing, release = (asyncio.Event() for _ in range(3))
    error = RuntimeError("synthetic monitor failure")

    async def collect(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()

    async def check():
        await entered.wait()
        if cause == "error":
            raise error
        if cause == "deadline":
            hooks.now = 61000
        return cause != "inactive"

    task = asyncio.create_task(run(hooks, collect_attempt=collect, check_active=check))
    try:
        await asyncio.wait_for(closing.wait(), 2)
        assert not task.done() and len(hooks.ordinal) == 1
        release.set()
        with pytest.raises(RuntimeError if cause == "error" else JSONRunStopped) as caught:
            await task
        if cause == "error":
            assert caught.value is error
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_wall_deadline_or_external_cancel_drains_consumers(cancel):
    hooks = Hooks()
    entered, closing, release = (asyncio.Event() for _ in range(3))

    async def collect(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closing.set()
            await release.wait()

    task = asyncio.create_task(run(hooks, limits(deadline_ms=1100), collect_attempt=collect))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            task.cancel()
        await asyncio.wait_for(closing.wait(), 2)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(hooks.ordinal) == 1


@pytest.mark.asyncio
async def test_unknown_fences_other_consumer_before_record_finishes_and_drains_callback():
    hooks = Hooks()
    second, recording, draining, release = (asyncio.Event() for _ in range(4))
    calls = []

    async def collect(spec, binding, attempt_limits):
        calls.append(spec.body)
        if len(calls) == 1:
            await second.wait()
            return AttemptObservation("delivery_unknown", None, 0, 1, None)
        second.set()
        await recording.wait()
        return AttemptObservation("output_collected", 200, 1, 1, "synthetic")

    async def record(ticket, observation):
        if observation.kind == "delivery_unknown":
            recording.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                draining.set()
                await release.wait()
                raise
        await hooks.record(ticket, observation)

    task = asyncio.create_task(run(hooks, limits(concurrency=2), collect_attempt=collect, record_attempt=record))
    try:
        await asyncio.wait_for(draining.wait(), 2)
        assert not task.done() and len(calls) == 2 and len(hooks.ordinal) == 2
        release.set()
        with pytest.raises(JSONRunStopped):
            await task
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancelled_render_thread_cannot_dispatch_late(monkeypatch):
    hooks = Hooks()
    loop = asyncio.get_running_loop()
    entered, release, drained = asyncio.Event(), threading.Event(), threading.Event()
    original = QAJSONBinding.render

    def render(self, frozen, text):
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(2), "Test must release render thread"
            return original(self, frozen, text)
        finally:
            drained.set()

    monkeypatch.setattr(QAJSONBinding, "render", render)
    task = asyncio.create_task(run(hooks))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert hooks.trace == []
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(drained.wait, 2)
    assert hooks.trace == []


@pytest.mark.asyncio
async def test_shared_source_complete_mock_run_without_business_dependencies():
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
from contextlib import asynccontextmanager
import httpx
from devpilot.qa_json_attempt import collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_run import JSONRunLimits,run_json_attempts
from devpilot.request_versions import FrozenRequest
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):yield b'{"a":"synthetic"}'
 async def aclose(self):pass
async def main():
 reserved=[];sent=[];recorded=[]
 async def reserve(ordinal,body_bytes):
  reserved.append(ordinal);return ordinal
 async def send(request):
  assert len(reserved)>len(sent)
  assert request.headers['accept-encoding']=='identity'
  sent.append(request.content)
  return httpx.Response(200,headers={'content-type':'application/json'},stream=Body())
 @asynccontextmanager
 async def factory(url,*,timeout_seconds):
  async with httpx.AsyncClient(transport=httpx.MockTransport(send),trust_env=False,follow_redirects=False) as client:yield client
 async def collect(spec,binding,limits):return await collect_json_attempt(spec,binding,limits,client_factory=factory)
 async def record(ticket,observation):
  assert observation.kind=='output_collected' and observation.output=='synthetic'
  recorded.append(ticket)
 async def active():return True
 await run_json_attempts(FrozenRequest(url='https://example.test/qa',method='POST',headers=(),body='{"q":""}'),QAJSONBinding('/q','/a'),('first','second'),JSONRunLimits(5,2,1000,61000,128),now_ms=lambda:1000,reserve_attempt=reserve,collect_attempt=collect,record_attempt=record,check_active=active)
 assert sorted(reserved)==sorted(recorded)==[1,2,3,4,5] and len(sent)==5
 assert sent.count(b'{"q":"first"}')==3 and sent.count(b'{"q":"second"}')==2
 print('qa-json-run.v1')
asyncio.run(main())
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-c", script, str(source)], cwd=source.parent, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION
