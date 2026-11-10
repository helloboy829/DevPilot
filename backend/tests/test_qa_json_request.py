"""Pinned pure JSON request projection; no export/transport or admission power."""

import asyncio
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import httpx
import pytest
from devpilot import qa_json_attempt
from devpilot.http import RequestSpec
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_request import QAJSONRequest
from devpilot.request_versions import FrozenRequest
from test_qa_attempts import Body, install_client

from app.evaluation import qa_attempts

VERSION = "qa-json-request.v1"


def frozen(*, url="https://example.test/qa?token=SYNTHETIC_URL_SECRET", method="POST", headers=(), body='{"q":"only input"}'):
    return FrozenRequest(url=url, method=method, headers=headers, body=body)


def test_fixed_version_literal_values_and_sensitive_repr():
    original = frozen(headers=(("Authorization", "Bearer SYNTHETIC_HEADER_SECRET"),), body='{"q":"SYNTHETIC_BODY_SECRET"}')
    ready = QAJSONRequest(original)
    assert ready.version == VERSION and ready.method == "POST"
    assert ready.url == original.url and ready.body == original.body
    assert ready.content == original.body.encode("utf-8")
    assert ready.headers == (*original.headers, ("Accept-Encoding", "identity"))
    assert "SYNTHETIC" not in repr(original) + repr(ready)
    assert not hasattr(ready, "send") and not hasattr(ready, "to_dict")
    assert not hasattr(ready, "authorized") and not hasattr(ready, "gold")
    for name, value in [("url", "https://other.test"), ("body", "x"), ("headers", ()), ("version", "latest")]:
        with pytest.raises(FrozenInstanceError):
            setattr(ready, name, value)


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
@pytest.mark.parametrize("body", ["", "not JSON", '{ "q": "  input  ", "n": 1.123456789012345678901234567890 }'])
def test_preparation_never_renders_parses_or_reserializes_body(method, body):
    original = frozen(method=method, body=body)
    ready = QAJSONRequest(original)
    assert ready.method == method and ready.content == body.encode("utf-8")
    assert original.body == body


@pytest.mark.parametrize(
    "headers,expected",
    [
        ((), (("Accept-Encoding", "identity"),)),
        ((("X-Z", "one"), ("X-Z", "two")), (("X-Z", "one"), ("X-Z", "two"), ("Accept-Encoding", "identity"))),
        ((("accept-encoding", "gzip"),), (("accept-encoding", "gzip"),)),
        ((("AcCePt-EnCoDiNg", ""),), (("AcCePt-EnCoDiNg", ""),)),
        ((("Accept-Encoding", "gzip"), ("accept-encoding", "br")), (("Accept-Encoding", "gzip"), ("accept-encoding", "br"))),
        ((("X-Z", "  literal  "), ("aCcEpT-EnCoDiNg", "identity"), ("Cookie", "SYNTHETIC_COOKIE_SECRET")), (("X-Z", "  literal  "), ("aCcEpT-EnCoDiNg", "identity"), ("Cookie", "SYNTHETIC_COOKIE_SECRET"))),
    ],
)
def test_header_order_case_duplicates_empty_and_explicit_encoding_are_literal(headers, expected):
    original = frozen(headers=headers)
    ready = QAJSONRequest(original)
    assert ready.headers == expected and original.headers == headers
    assert isinstance(ready.headers, tuple) and all(isinstance(pair, tuple) for pair in ready.headers)


@pytest.mark.parametrize("explicit", [False, True])
def test_original_64_header_limit_and_derived_identity_match_old_collector(explicit):
    headers = tuple(("X-Case", str(i)) for i in range(63)) + (("Accept-Encoding" if explicit else "X-Last", "gzip" if explicit else "64"),)
    original = frozen(headers=headers)
    ready = QAJSONRequest(original)
    assert ready.headers == headers if explicit else ready.headers == (*headers, ("Accept-Encoding", "identity"))
    assert len(ready.headers) == (64 if explicit else 65)
    assert len(original.headers) == 64


@pytest.mark.parametrize("url", ["https://EXAMPLE.test:443/a%2Fb?q=a+b&q=%2f", "http://example.test:8080/x?empty=&x=%20", "https://example.test/"])
def test_projection_does_not_canonicalize_url_or_query(url):
    assert QAJSONRequest(frozen(url=url)).url == url


@pytest.mark.parametrize("body", ["x" * 262144, "\u00e9" * 131072, "\U0001f642" * 65536])
def test_exact_request_utf8_byte_limit_is_preserved(body):
    ready = QAJSONRequest(frozen(body=body))
    assert len(ready.content) == 262144 and ready.body == body


@pytest.mark.parametrize("version", ["latest", "qa-json-request.v2", "", None, 1])
def test_version_is_explicitly_pinned(version):
    with pytest.raises(ValueError, match="Invalid QA JSON request"):
        QAJSONRequest(frozen(), version=version)


@pytest.mark.parametrize("invalid", [None, {}, "SYNTHETIC_SECRET", RequestSpec(url="https://example.test")])
def test_only_frozen_request_is_accepted(invalid):
    with pytest.raises(ValueError, match="Invalid QA JSON request") as error:
        QAJSONRequest(invalid)
    assert "SYNTHETIC" not in str(error.value)


@pytest.mark.parametrize(
    "name,value",
    [
        ("url", "https://example.test/ SYNTHETIC_URL_SECRET"),
        ("url", "https://SYNTHETIC_USER:SYNTHETIC_PASSWORD@example.test"),
        ("method", "TRACE"),
        ("headers", (("Host", "SYNTHETIC_HOST_SECRET"),)),
        ("headers", (("X-Test", "SYNTHETIC_HEADER_SECRET\r\nInjected: value"),)),
        ("headers", (("X-Test", "\u4e2d"),)),
        ("headers", tuple(("X-Test", str(i)) for i in range(65))),
        ("body", "x" * 262145),
        ("body", "\ud800"),
        ("body", None),
    ],
)
@pytest.mark.asyncio
async def test_defensive_revalidation_is_generic_before_client(monkeypatch, name, value):
    original = frozen()
    object.__setattr__(original, name, value)  # Deliberately bypass immutability only to test revalidation.
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        pytest.fail("Invalid request must fail before any client")

    monkeypatch.setattr(qa_attempts, "evaluation_client", forbidden)
    with pytest.raises(ValueError, match="Invalid QA JSON request") as error:
        QAJSONRequest(original)
    assert "SYNTHETIC" not in str(error.value)
    with pytest.raises(ValueError):
        await qa_attempts.collect_json_attempt(original, QAJSONBinding("/q", "/a"), None, qa_attempts.AttemptLimits())
    assert calls == []


def test_snapshot_does_not_retain_mutable_spec_or_original_object(monkeypatch):
    original = frozen(headers=(("X-Test", "one"),))
    ready = QAJSONRequest(original)
    changed = original.to_request()
    changed.headers[0][1] = "mutated"
    object.__setattr__(original, "body", "changed after prepare")
    assert ready.body == '{"q":"only input"}' and ready.headers[0] == ("X-Test", "one")
    assert ready.content == b'{"q":"only input"}'


@pytest.mark.asyncio
async def test_app_delegates_to_pinned_preparation_once_and_encodes_inside_client(monkeypatch):
    original = frozen(body='{"q":"\u7b54\U0001f642"}', headers=(("Content-Type", "application/json"),))
    prepared = []
    encoded = []
    entered_client = False
    prepare = qa_json_attempt.QAJSONRequest
    get_content = QAJSONRequest.content.fget

    def projection(request):
        value = prepare(request)
        prepared.append(value)
        return value

    def content(self):
        assert entered_client
        encoded.append(self)
        return get_content(self)

    monkeypatch.setattr(qa_json_attempt, "QAJSONRequest", projection)
    monkeypatch.setattr(QAJSONRequest, "content", property(content))

    async def handle(sent):
        assert sent.content == original.body.encode("utf-8")
        assert sent.headers["accept-encoding"] == "identity"
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=Body([b'{"a":"ok"}']))

    calls = install_client(monkeypatch, handle)
    client = qa_attempts.evaluation_client

    def enter(*args, **kwargs):
        nonlocal entered_client
        assert len(prepared) == 1
        entered_client = True
        return client(*args, **kwargs)

    monkeypatch.setattr(qa_attempts, "evaluation_client", enter)
    result = await qa_attempts.collect_json_attempt(original, QAJSONBinding("/q", "/a"), None, qa_attempts.AttemptLimits())
    assert result.kind == "output_collected" and result.output == "ok"
    assert len(calls) == 1 and encoded == prepared


@pytest.mark.asyncio
async def test_pure_source_runs_without_site_packages_or_business_imports():
    source = Path(__file__).resolve().parents[2] / "devpilot" / "src"
    script = """import importlib.abc,sys
sys.path.insert(0,sys.argv[1])
class Deny(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,*args):
  if fullname.split('.')[0] in {'app','deerflow','httpx','sqlalchemy','fastapi','openpyxl'}:raise AssertionError('business import')
sys.meta_path.insert(0,Deny())
from devpilot.request_versions import FrozenRequest
from devpilot.qa_json_request import QAJSONRequest
ready=QAJSONRequest(FrozenRequest(url="https://example.test",method="POST",headers=(),body="input"))
assert ready.content==b"input" and ready.headers==(("Accept-Encoding","identity"),)
print(ready.version)
"""
    result = await asyncio.to_thread(subprocess.run, [sys.executable, "-I", "-S", "-c", script, str(source)], cwd=source.parent, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == VERSION
