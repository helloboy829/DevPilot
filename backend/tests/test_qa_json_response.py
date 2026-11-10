"""Pure response adapter contract and offline parity with the admitted collector."""

import asyncio
import json
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import httpx
import pytest
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_response import QAJSONResponseBuffer, ResponseResult
from devpilot.request_versions import FrozenRequest
from test_qa_attempts import Body, install_client

from app.evaluation import qa_attempts

VERSION = "qa-json-response.v1"


def buffer(*, maximum=1024, binding=None, **head):
    return QAJSONResponseBuffer(binding or QAJSONBinding(input_pointer="/q", output_pointer="/a"), max_response_bytes=maximum, http_status=200, content_type="application/json", **head)


def test_fixed_version_and_sensitive_result_and_buffer_are_not_log_dtos():
    state = buffer()
    assert state.version == VERSION and state.body_bytes == 0 and not state.terminal
    state.feed(b'{"a":"SYNTHETIC_RESPONSE_SECRET"}')
    result = state.finish()
    assert result.kind == "output_collected" and result.output == "SYNTHETIC_RESPONSE_SECRET"
    assert result.body_bytes == state.body_bytes == 33
    assert "SYNTHETIC" not in repr(state) + repr(result)
    assert not hasattr(result, "passed") and not hasattr(result, "headers")
    assert not hasattr(result, "body") and not hasattr(result, "ttft_ms")
    assert state.terminal and state.finish() is result
    with pytest.raises(FrozenInstanceError):
        result.kind = "passed"
    with pytest.raises(ValueError, match="Response buffer is closed"):
        state.feed(b"late")


@pytest.mark.parametrize("status", [100, 199, 300, 301, 307, 400, 401, 429, 500, 599, 600, 999])
def test_http_failure_precedes_media_and_length_and_never_reads(status):
    state = QAJSONResponseBuffer(QAJSONBinding("/q", "/a"), http_status=status, content_type="text/html", content_encoding="gzip", content_length="99999999", max_response_bytes=16)
    assert state.terminal and state.finish() == ResponseResult("http_error", 0, None)
    with pytest.raises(ValueError, match="Response buffer is closed"):
        state.feed(b"SYNTHETIC_SECRET")


@pytest.mark.parametrize("media", ["application/json", "Application/JSON; charset=UTF-8", " application/vnd.example+json ", "application/problem+json;charset=utf-8"])
def test_supported_json_media_keeps_literal_output(media):
    state = QAJSONResponseBuffer(QAJSONBinding("/q", "/a"), http_status=299, content_type=media, content_encoding=" Identity ")
    state.feed(b'{"a":"  literal\\ntext  "}')
    assert state.finish().output == "  literal\ntext  "


@pytest.mark.parametrize(
    "media,encoding",
    [
        ("", "identity"),
        ("text/json", "identity"),
        ("text/event-stream", "identity"),
        ("application/+json", "identity"),
        ("application/json", "gzip"),
        ("application/json", "br"),
        ("application/json", "identity, gzip"),
        ("application/json", ""),
    ],
)
def test_unsupported_framing_precedes_length_without_consuming(media, encoding):
    state = QAJSONResponseBuffer(QAJSONBinding("/q", "/a"), http_status=200, content_type=media, content_encoding=encoding, content_length="99999", max_response_bytes=16)
    assert state.terminal and state.finish() == ResponseResult("unsupported_response", 0, None)


@pytest.mark.parametrize("declared,early", [("17", True), ("9" * 21, True), ("000000000000000000000", True), ("16", False), ("0", False), ("", False), ("nonsense", False), ("+17", False), (" 17 ", False), ("\u0661\u0667", False)])
def test_content_length_is_only_an_early_rejection_not_a_body_budget(declared, early):
    state = buffer(maximum=16, content_length=declared)
    assert state.terminal is early
    if early:
        assert state.finish() == ResponseResult("response_limit", 0, None)
    else:
        state.feed(b"x" * 50000)
        assert state.finish() == ResponseResult("response_limit", 17, None)


@pytest.mark.parametrize("size", [1, 2, 3, 7, 16, 50000])
def test_every_chunk_partition_preserves_utf8_pointer_and_exact_boundary(size):
    raw = json.dumps({"a": "\u7b54\u590d\U0001f642", "n": 1}, ensure_ascii=False).encode()
    state = buffer(maximum=len(raw))
    for start in range(0, len(raw), size):
        state.feed(raw[start : start + size])
    result = state.finish()
    assert result == ResponseResult("output_collected", len(raw), "\u7b54\u590d\U0001f642")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"not json",
        b'{"a":""}',
        b'{"a":"  \\n"}',
        b'{"a":1}',
        b'{"a":null}',
        b'{"a":false}',
        b'{"other":"x"}',
        b'{"a":"one","a":"two"}',
        b'{"a":NaN}',
        b'{"n":Infinity,"a":"x"}',
        b'{"a":"\xff"}',
        b'{"a":"\\ud800"}',
        b'{"a":"x"} trailing',
    ],
)
def test_invalid_output_is_not_collected_and_errors_never_expose_text(raw):
    state = buffer()
    state.feed(raw)
    assert state.finish() == ResponseResult("invalid_output", len(raw), None)


@pytest.mark.parametrize("maximum", [True, 1.0, "16", 0, -1, 1048577])
def test_invalid_budget_fails_before_any_chunk(maximum):
    with pytest.raises(ValueError, match="Invalid QA JSON response input"):
        buffer(maximum=maximum)


@pytest.mark.parametrize(
    "kwargs", [{"version": "latest"}, {"version": "qa-json-response.v2"}, {"http_status": True}, {"http_status": "200"}, {"http_status": 99}, {"http_status": 1000}, {"content_type": None}, {"content_encoding": None}, {"content_length": 10}]
)
def test_strict_adapter_input_and_version(kwargs):
    head = {"http_status": 200, "content_type": "application/json", **kwargs}
    with pytest.raises(ValueError, match="Invalid QA JSON response input"):
        QAJSONResponseBuffer(QAJSONBinding("/q", "/a"), **head)


def test_binding_is_revalidated_and_nonbytes_rejected_without_polluting_buffer():
    with pytest.raises(ValueError, match="Invalid QA JSON response input"):
        QAJSONResponseBuffer({"output_pointer": "/a"}, http_status=200)
    state = buffer()
    for chunk in [None, "SYNTHETIC_SECRET", 123, bytearray(b"bad"), memoryview(b"bad")]:
        with pytest.raises(ValueError, match="Invalid QA JSON response chunk") as error:
            state.feed(chunk)
        assert "SYNTHETIC" not in str(error.value) and state.body_bytes == 0
    state.feed(b'{"a":"safe"}')
    assert state.finish().output == "safe"


@pytest.mark.parametrize("pointer,raw,expected", [("", b'"root"', "root"), ("/a~1b/~0/0", b'{"a/b":{"~":["value"]}}', "value"), ("/a", b'{"untouched":1.123456789012345678901234567890,"a":"exact"}', "exact")])
def test_existing_binding_semantics_are_shared(pointer, raw, expected):
    state = buffer(binding=QAJSONBinding("/q", pointer))
    state.feed(raw)
    assert state.finish().output == expected


@pytest.mark.parametrize(
    "status,headers,raw,maximum,kind,count",
    [
        (200, {"content-type": "application/json"}, b'{"a":"ok"}', 64, "output_collected", 10),
        (201, {"content-type": "application/problem+json"}, b'{"a":"ok"}', 10, "output_collected", 10),
        (302, {"content-type": "application/json"}, b'{"a":"x"}', 64, "http_error", 0),
        (200, {"content-type": "text/event-stream"}, b"data: x", 64, "unsupported_response", 0),
        (200, {"content-type": "application/json", "content-encoding": "gzip"}, b"compressed", 64, "unsupported_response", 0),
        (200, {"content-type": "application/json", "content-length": "1000"}, b"x", 16, "response_limit", 0),
        (200, {"content-type": "application/json"}, b"x" * 100, 16, "response_limit", 17),
        (200, {"content-type": "application/json", "content-length": "1"}, b"x" * 100, 16, "response_limit", 17),
        (200, {"content-type": "application/json"}, b'{"a":""}', 64, "invalid_output", 8),
        (200, {"content-type": "application/json"}, b'{"a":NaN}', 64, "invalid_output", 9),
        (200, {"content-type": "application/json"}, b'{"a":"x","a":"y"}', 64, "invalid_output", 17),
    ],
)
@pytest.mark.asyncio
async def test_platform_collector_consumes_same_pure_result_once(monkeypatch, status, headers, raw, maximum, kind, count):
    pure = QAJSONResponseBuffer(
        QAJSONBinding("/q", "/a"), http_status=status, content_type=headers.get("content-type", ""), content_encoding=headers.get("content-encoding", "identity"), content_length=headers.get("content-length", ""), max_response_bytes=maximum
    )
    body = Body([raw[:3], raw[3:]])
    if not pure.terminal:
        for chunk in body.chunks:
            pure.feed(chunk)
            if pure.terminal:
                break
    expected = pure.finish()
    assert expected.kind == kind and expected.body_bytes == count

    async def handle(request):
        return httpx.Response(status, headers=headers, stream=body)

    calls = install_client(monkeypatch, handle)
    result = await qa_attempts.collect_json_attempt(FrozenRequest(url="https://example.test/qa", method="POST", headers=(), body='{"q":"only input"}'), QAJSONBinding("/q", "/a"), None, qa_attempts.AttemptLimits(max_response_bytes=maximum))
    assert (result.kind, result.body_bytes, result.output) == (expected.kind, expected.body_bytes, expected.output)
    assert result.http_status == status and body.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_platform_finishes_pure_buffer_off_event_loop(monkeypatch):
    owner_thread = threading.get_ident()
    threads = []
    original = QAJSONResponseBuffer.finish

    def finish(self):
        threads.append(threading.get_ident())
        return original(self)

    monkeypatch.setattr(QAJSONResponseBuffer, "finish", finish)

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Body([b'{"a":"ok"}']))

    install_client(monkeypatch, handle)
    result = await qa_attempts.collect_json_attempt(FrozenRequest(url="https://example.test", method="POST", headers=(), body='{"q":"input"}'), QAJSONBinding("/q", "/a"), None, qa_attempts.AttemptLimits())
    assert result.kind == "output_collected" and threads and all(t != owner_thread for t in threads)


@pytest.mark.asyncio
async def test_core_imports_and_runs_without_app_harness_httpx_or_site_packages():
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """
import importlib.abc,sys
sys.path.insert(0, sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'app','deerflow','httpx','sqlalchemy','fastapi'}:
            raise AssertionError('Business dependency imported')
sys.meta_path.insert(0, Deny())
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_response import QAJSONResponseBuffer
state = QAJSONResponseBuffer(QAJSONBinding('/q','/a'), http_status=200, content_type='application/json')
state.feed(b'{"a":"self-test"}')
assert state.finish().output == 'self-test'
print(state.version)
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-S", "-c", script, str(source)], cwd=source.parent, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_even_complete_json_is_not_finalized_after_stream_failure_or_cancellation(monkeypatch, cancel):
    yielded = asyncio.Event()
    never = asyncio.Event()
    finished = []
    original = QAJSONResponseBuffer.finish

    def finish(self):
        finished.append(True)
        return original(self)

    monkeypatch.setattr(QAJSONResponseBuffer, "finish", finish)

    class InterruptedBody(Body):
        async def __aiter__(self):
            yield b'{"a":"must not collect"}' + b" " * (16384 - len(b'{"a":"must not collect"}'))
            yielded.set()
            if cancel:
                await never.wait()
            raise httpx.ReadError("SYNTHETIC_TRANSPORT_SECRET")

    body = InterruptedBody([])

    async def handle(request):
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=body)

    calls = install_client(monkeypatch, handle)
    task = asyncio.create_task(
        qa_attempts.collect_json_attempt(FrozenRequest(url="https://example.test", method="POST", headers=(), body='{"q":"input"}'), QAJSONBinding("/q", "/a"), None, qa_attempts.AttemptLimits(max_response_bytes=32768))
    )
    try:
        await asyncio.wait_for(yielded.wait(), timeout=2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.kind == "delivery_unknown" and result.output is None
            assert result.body_bytes == 16384
            assert "SYNTHETIC" not in repr(result)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert body.closed and len(calls) == 1 and finished == []
