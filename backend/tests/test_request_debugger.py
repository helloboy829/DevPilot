"""Synthetic cURL inputs; parsing never invokes a shell or reads files."""

import json

import pytest
from devpilot.http import RequestSpec, parse_curl


def test_curl_import_preserves_json_and_query():
    spec = parse_curl("""curl 'https://example.test/v1?x=one%20two' -H 'Content-Type: application/json' -H 'Authorization: Bearer synthetic' --data-raw '{"q":"hello; world"}'""")
    assert spec.method == "POST"
    assert spec.url.endswith("?x=one%20two")
    assert spec.body == '{"q":"hello; world"}'
    assert spec.headers[-1] == ["Authorization", "Bearer synthetic"]
    assert spec.version == "request.v1"


@pytest.mark.parametrize(
    "command",
    [
        "curl https://example.test && whoami",
        "curl https://example.test --data @private.txt",
        "curl https://example.test -k",
        "curl https://example.test --proxy http://localhost",
        "curl https://example.test/$(whoami)",
        "curl file:///etc/passwd",
        "curl https://user:password@example.test",
        "curl https://example.test https://second.test",
        'curl https://example.test -H "Host: localhost"',
    ],
)
def test_unsafe_or_unsupported_curl_rejected(command):
    with pytest.raises(ValueError):
        parse_curl(command)


@pytest.mark.parametrize("option", ["-k", "-sk", "-kS", "--insecure"])
def test_insecure_tls_option_has_actionable_error(option):
    with pytest.raises(ValueError, match=r"-k/--insecure"):
        parse_curl(f"curl {option} https://10.149.73.28:5035/dify/v1/chat-messages")


def test_dify_multiline_request_parses_without_insecure_tls_option():
    spec = parse_curl(
        """curl -X POST 'https://10.149.73.28:5035/dify/v1/chat-messages' \\
--header 'Authorization: Bearer synthetic' \\
--header 'Content-Type: application/json' \\
--data '{\\
  \"inputs\":{\"userId\":\"1\",\"kbCodes\":\"#S1-4#S5-1#\"},\\
  \"query\": \"并网的整体流程是怎么样子的？\",\\
  \"response_mode\": \"blocking\",\\
  \"user\": \"test\"\\
}'"""
    )
    assert spec.method == "POST"
    assert spec.url == "https://10.149.73.28:5035/dify/v1/chat-messages"
    parsed = json.loads(spec.body)
    assert parsed["inputs"]["kbCodes"] == "#S1-4#S5-1#"
    assert parsed["user"] == "test"


def test_common_escaped_scheme_separator_is_normalized():
    spec = parse_curl("curl 'https\\://10.149.73.28:5035/dify/v1/chat-messages'")
    assert spec.url == "https://10.149.73.28:5035/dify/v1/chat-messages"

def test_multiline_and_auth_and_strict_schema():
    spec = parse_curl(
        'curl --url https://example.test \
 -X PUT -u demo:synthetic --json "{}"'
    )
    assert spec.method == "PUT"
    assert any(h[0].lower() == "authorization" for h in spec.headers)
    with pytest.raises(ValueError):
        RequestSpec.from_dict({"method": "GET", "url": "https://example.test", "shell": "bad"})


@pytest.mark.asyncio
async def test_outbound_policy_default_denies_and_dns_is_checked(monkeypatch):
    from types import SimpleNamespace

    from app.evaluation.http import resolve_destination

    spec = parse_curl("curl https://example.test")
    with pytest.raises(ValueError):
        await resolve_destination(spec, SimpleNamespace())
    import asyncio

    loop = asyncio.get_running_loop()

    async def lookup(*args, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    with pytest.raises(ValueError):
        await resolve_destination(spec, SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]}))
    result = await resolve_destination(spec, SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"], "allow_private": True}))
    assert result == "127.0.0.1"
