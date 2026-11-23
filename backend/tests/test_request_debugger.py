"""Synthetic cURL inputs; parsing never invokes a shell or reads files."""

import json

import pytest
from devpilot.http import RequestSpec, parse_curl
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
        "curl https://example.test --proxy http://localhost",
        "curl https://example.test/$(whoami)",
        "curl file:///etc/passwd",
        "curl -K https://example.test",
        "curl -sK https://example.test",
        "curl https://user:password@example.test",
        "curl https://example.test https://second.test",
        'curl https://example.test -H "Host: localhost"',
    ],
)
def test_unsafe_or_unsupported_curl_rejected(command):
    with pytest.raises(ValueError):
        parse_curl(command)


@pytest.mark.parametrize("option", ["-k", "-sk", "-kS", "--insecure"])
def test_insecure_tls_import_is_marked_for_one_shot_consent(option):
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import(f"curl {option} https://10.149.73.28:5035/dify/v1/chat-messages")
    assert parsed.insecure_tls is True
    assert parsed.spec.url.endswith("/dify/v1/chat-messages")


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


def test_supplied_dify_curl_parses_k_and_preserves_json_body():
    from devpilot.http import parse_curl_import

    command = r"""curl -k -X POST 'https\://10.149.73.28:5035/dify/v1/chat-messages' --header 'Authorization: Bearer synthetic' --header 'Content-Type: application/json' --data '{\
&#x20; "inputs":{"userId":"1","kbCodes":"#S1-4#S5-1#"},\
&#x20; "query": "Example question?",\
&#x20; "response_mode": "blocking",\
&#x20; "user": "test"\
}'"""
    parsed = parse_curl_import(command)
    assert parsed.insecure_tls is True
    assert parsed.spec.url == "https://10.149.73.28:5035/dify/v1/chat-messages"
    assert json.loads(parsed.spec.body)["query"] == "Example question?"
    assert set(parsed.warnings) == {"normalized_url_scheme", "normalized_json_indentation"}


def test_literal_dollar_in_json_body_is_preserved_but_shell_expansion_is_rejected():
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import("""curl https://example.test --json '{"text":"$5.00 literal"}'""")
    assert json.loads(parsed.spec.body) == {"text": "$5.00 literal"}
    with pytest.raises(ValueError, match="Shell expansion"):
        parse_curl_import('curl https://example.test --data "$(whoami)"')


@pytest.mark.parametrize(("flags", "insecure"), [("-sk", True), ("-ks", True), ("-k", True), ("-k --no-insecure", False), ("--no-insecure -k", True)])
def test_tls_short_flag_order_matches_curl_semantics(flags, insecure):
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import(f"curl {flags} https://example.test")
    assert parsed.insecure_tls is insecure


@pytest.mark.parametrize("continuation", ["^\r\n", "`\r\n", "\\\n"])
def test_curl_import_accepts_common_line_continuations(continuation):
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import(f"curl -sk {continuation} https://example.test {continuation} --json '{{}}'")
    assert parsed.insecure_tls is True
    assert parsed.spec.body == "{}"


def test_valid_json_with_literal_entity_is_not_rewritten():
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import("""curl https://example.test --json '{"text":"&#x20;"}'""")
    assert json.loads(parsed.spec.body) == {"text": "&#x20;"}
    assert parsed.warnings == ()


def test_unsupported_inline_flag_does_not_echo_value():
    with pytest.raises(ValueError, match=r"Unsupported cURL option --unknown") as exc:
        parse_curl("curl https://example.test --unknown=synthetic-secret")
    assert "synthetic-secret" not in str(exc.value)


def test_no_insecure_cancels_previous_k():
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import("curl -ksS --no-insecure https://example.test")
    assert parsed.insecure_tls is False


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


def test_insecure_tls_is_reported_as_one_shot_parse_metadata():
    from devpilot.http import parse_curl_import

    parsed = parse_curl_import("curl -sk -X POST https://internal.example/api --json '{}'")
    assert parsed.spec.url == "https://internal.example/api"
    assert parsed.spec.method == "POST"
    assert parsed.insecure_tls is True


def test_curl_parse_endpoint_reports_insecure_tls_without_sending():

    from app.gateway.routers.request_debugger import router

    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def auth(request, call_next):
        from types import SimpleNamespace

        from app.gateway.authz import AuthContext

        request.state.auth = AuthContext(user=SimpleNamespace(id="synthetic"), permissions=["threads:write"])
        return await call_next(request)

    with TestClient(app) as client:
        response = client.post(
            "/api/component-tests/debug/parse",
            json={"command": "curl -k https://example.test"},
        )
    assert response.status_code == 200
    assert response.json()["insecure_tls"] is True
    assert response.json()["warnings"]
