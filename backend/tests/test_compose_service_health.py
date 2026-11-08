"""Offline startup/readiness contracts; no Docker, configuration or live targets."""

import http.client
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker-compose.yaml", "docker-compose-dev.yaml"]


def _services(variant):
    return yaml.safe_load((ROOT / "docker" / variant).read_text(encoding="utf-8"))["services"]


@pytest.mark.parametrize("variant", COMPOSE)
@pytest.mark.parametrize("service", ["gateway", "frontend", "nginx"])
def test_core_healthchecks_are_explicit_bounded_and_non_mutating(variant, service):
    spec = _services(variant)[service]
    check = spec["healthcheck"]
    assert check["test"][0] == "CMD"
    assert check["interval"] == "30s"
    assert check["timeout"] == "5s"
    assert check["retries"] == 3
    assert check["start_period"] == ("10s" if service == "nginx" else "60s")
    assert "disable" not in check
    assert spec["restart"] == "unless-stopped"
    for unsafe in ["docker ", "restart", "prune", "config.yaml", "Authorization", "curl "]:
        assert unsafe not in " ".join(check["test"])


@pytest.mark.parametrize("variant", COMPOSE)
def test_proxy_waits_for_both_upstreams_without_cascading_restarts(variant):
    services = _services(variant)
    assert services["nginx"]["depends_on"] == {
        "frontend": {"condition": "service_healthy"},
        "gateway": {"condition": "service_healthy"},
    }
    assert services["gateway"]["depends_on"]["redis"] == {"condition": "service_healthy"}
    assert "depends_on" not in services["frontend"]


def test_nginx_probe_only_reads_the_local_proxy_endpoint():
    for variant in COMPOSE:
        assert _services(variant)["nginx"]["healthcheck"]["test"] == [
            "CMD",
            "wget",
            "-q",
            "-Y",
            "off",
            "-O",
            "/dev/null",
            "-T",
            "2",
            "-t",
            "1",
            "http://127.0.0.1:2026/nginx-health",
        ]
    config = (ROOT / "docker/nginx/nginx.conf").read_text(encoding="utf-8")
    block = config.split("location = /nginx-health {", 1)[1].split("}", 1)[0]
    assert "access_log off;" in block
    assert 'return 200 "ok\\n";' in block
    assert "default_type text/plain;" in block
    assert "proxy_pass" not in block


@pytest.mark.parametrize("status", [200, 204, 301, 302, 401, 500])
def test_gateway_probe_requires_exact_200_without_proxy_redirect_or_body_read(monkeypatch, status):
    seen = []

    class Connection:
        def __init__(self, *args, **kwargs):
            seen.append((args, kwargs))

        def request(self, *args):
            seen.append(args)

        def getresponse(self):
            return type("Response", (), {"status": status})()

        def close(self):
            seen.append("closed")

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    commands = [_services(variant)["gateway"]["healthcheck"]["test"] for variant in COMPOSE]
    assert commands[0] == commands[1]
    assert commands[0][:3] == ["CMD", "python", "-c"]
    with pytest.raises(SystemExit) as result:
        exec(compile(commands[0][3], "<gateway-probe>", "exec"), {})
    assert result.value.code == (0 if status == 200 else 1)
    assert seen == [(("127.0.0.1", 8001), {"timeout": 2}), ("GET", "/health"), "closed"]


@pytest.mark.parametrize("error", [TimeoutError, ConnectionRefusedError])
def test_gateway_probe_errors_fail_quietly_without_private_output(monkeypatch, capsys, error):
    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args):
            raise error("synthetic-private-text")

        def close(self):
            pass

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    command = _services(COMPOSE[0])["gateway"]["healthcheck"]["test"]
    with pytest.raises(SystemExit) as result:
        exec(compile(command[3], "<gateway-probe>", "exec"), {})
    assert result.value.code == 1
    output = capsys.readouterr()
    assert not output.out and not output.err


NODE_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
let callback, onError, timer, target, destroyed = false;
const exit = {};
let result = null;
const sandbox = {
  require(name) {
    if (name !== 'node:http') throw new Error('unexpected import');
    return {get(url, options, cb) {
      if (options.agent !== false || Object.keys(options).length !== 1) throw new Error("proxy bypass required");
      target = url; callback = cb;
      return {on(event, fn) {
        if (event !== 'error') throw new Error('unexpected event');
        onError = fn; return this;
      }};
    }};
  },
  setTimeout(fn, ms) {
    if (ms !== 3000) throw new Error('unbounded deadline');
    timer = fn;
  },
  process: {exit(code) {result = code; throw exit;}}
};
try {
  vm.runInNewContext(input.source, sandbox, {timeout: 1000});
  if (input.scenario === 'error') onError(new Error('synthetic-private-text'));
  else if (input.scenario === 'timeout') timer();
  else callback({statusCode: input.status, destroy() {destroyed = true;}});
} catch (err) {if (err !== exit) throw err;}
console.log(JSON.stringify({result, target, destroyed}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node needed to execute the exact frontend probe")
@pytest.mark.parametrize("scenario,status", [("response", 200), ("response", 204), ("response", 302), ("response", 401), ("response", 500), ("error", None), ("timeout", None)])
def test_frontend_probe_fails_closed_quietly_with_a_total_deadline(scenario, status):
    commands = [_services(variant)["frontend"]["healthcheck"]["test"] for variant in COMPOSE]
    assert commands[0] == commands[1]
    assert commands[0][:3] == ["CMD", "node", "-e"]
    result = subprocess.run(
        [shutil.which("node"), "-e", NODE_HARNESS],
        input=json.dumps({"source": commands[0][3], "scenario": scenario, "status": status}),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert not result.stderr
    assert json.loads(result.stdout) == {
        "result": 0 if status == 200 else 1,
        "target": "http://127.0.0.1:3000/login",
        "destroyed": scenario == "response",
    }
