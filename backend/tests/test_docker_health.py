"""Synthetic offline tests for the metadata-only Docker health probe."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import docker_health as health
import pytest

SERVICES = ("gateway", "frontend", "nginx", "redis")


def rows(**overrides):
    return [{"service": name, "state": "running", "health": "healthy", "restart_count": 0, "oom_killed": False, "exit_code": 0, **overrides} for name in SERVICES]


def fake_docker(monkeypatch, *, states=None, info=None, ids=None):
    calls = []

    def run(args, timeout):
        calls.append((args, timeout))
        if args[0] == "info":
            return json.dumps(info if info is not None else {"cpu_count": 4, "memory_total_bytes": 8 * 1024**3})
        if args[0] == "ps":
            return ids if ids is not None else "\n".join(f"{i:012x}" for i in range(1, 5))
        if args[:2] == ["container", "inspect"]:
            return "\n".join(json.dumps(row) for row in (states if states is not None else rows()))
        raise AssertionError(args)

    monkeypatch.setattr(health, "run_docker", run)
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _: SimpleNamespace(total=100 * 1024**3, free=20 * 1024**3))
    return calls


def test_healthy_project_uses_only_metadata_and_project_filter(monkeypatch, tmp_path):
    calls = fake_docker(monkeypatch)
    result = health.collect("devpilot-local", 2, tmp_path)
    assert result["status"] == "ok"
    assert result["docker"]["cpu_count"] == 4
    assert set(result["services"]) == set(SERVICES)
    assert "label=com.docker.compose.project=devpilot-local" in calls[1][0]
    assert len(calls) == 3
    assert all(0 < timeout <= 2 for _, timeout in calls)
    for args, _ in calls:
        assert args[0] in {"info", "ps", "container"}
    assert calls[2][0][:2] == ["container", "inspect"]
    template = calls[2][0][3]
    assert not any(secret in template for secret in (".Config.Env", ".Mounts", ".Log", ".State.Error", ".Name", ".Config.Image"))


@pytest.mark.parametrize("code", ["cli_missing", "cli_unavailable", "command_timeout", "command_failed", "invalid_response"])
def test_daemon_errors_are_fixed_codes_and_stop_further_commands(monkeypatch, tmp_path, code):
    calls = fake_docker(monkeypatch)

    def fail(*_):
        raise health.ProbeError(code)

    monkeypatch.setattr(health, "run_docker", fail)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "fail"
    assert result["docker"] == {"status": "fail", "reason": code}
    assert all(value is None for value in result["services"].values())
    assert calls == []


@pytest.mark.parametrize("info", [{}, {"cpu_count": True, "memory_total_bytes": 4}, {"cpu_count": 2, "memory_total_bytes": -1}, {"cpu_count": 0, "memory_total_bytes": 3}])
def test_malformed_daemon_metadata_fails_closed(monkeypatch, tmp_path, info):
    calls = fake_docker(monkeypatch, info=info)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "fail"
    assert result["docker"]["reason"] == "invalid_response"
    assert len(calls) == 1


@pytest.mark.parametrize("value", ["bad id", "--help", "private-customer-host", "0" * 12 + "\n" + "1" * 12 + "\n" + "0" * 12, "\n".join(f"{i:012x}" for i in range(33))])
def test_unbounded_or_invalid_container_ids_never_reach_inspect(monkeypatch, tmp_path, value):
    calls = fake_docker(monkeypatch, ids=value)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "fail"
    assert len(calls) == 2
    assert value not in json.dumps(result)


def test_missing_services_fail_without_claiming_engine_failed(monkeypatch, tmp_path):
    calls = fake_docker(monkeypatch, ids="")
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "fail"
    assert result["docker"]["status"] == "ok"
    assert result["services"] == {name: [] for name in SERVICES}
    assert "missing_gateway" in result["findings"]
    assert len(calls) == 2


def test_missing_healthchecks_are_observability_warnings_not_proof_of_readiness(monkeypatch, tmp_path):
    fake_docker(monkeypatch, states=rows(health="not_configured"))
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "warn"
    assert "healthcheck_not_configured_frontend" in result["findings"]


@pytest.mark.parametrize("change,expected", [({"health": "unhealthy"}, "fail"), ({"health": "starting"}, "warn"), ({"state": "exited", "exit_code": 1}, "fail"), ({"restart_count": 2}, "warn"), ({"oom_killed": True}, "warn")])
def test_application_failures_and_historical_resource_signals_are_distinct(monkeypatch, tmp_path, change, expected):
    states = rows()
    states[0].update(change)
    fake_docker(monkeypatch, states=states)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == expected
    assert result["docker"]["status"] == "ok"


def test_low_storage_is_warning_without_root_cause_or_path_claim(monkeypatch, tmp_path):
    fake_docker(monkeypatch)
    monkeypatch.setattr(health.shutil, "disk_usage", lambda _: SimpleNamespace(total=100 * 1024**3, free=2 * 1024**3))
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "warn"
    assert "low_workspace_disk" in result["findings"]
    assert str(tmp_path) not in json.dumps(result)
    assert "root_cause" not in result


def test_disk_failure_is_not_falsely_reported_as_zero_free(monkeypatch, tmp_path):
    fake_docker(monkeypatch)

    def denied(_):
        raise PermissionError("private-user-path-and-token")

    monkeypatch.setattr(health.shutil, "disk_usage", denied)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["storage"]["workspace"] == {"status": "unknown"}
    assert "private-user" not in json.dumps(result)


def test_unrelated_service_metadata_is_never_published(monkeypatch, tmp_path):
    states = rows() + [{"service": "private-customer-service", "secret": "synthetic-token-do-not-publish"}]
    fake_docker(monkeypatch, states=states, ids="\n".join(f"{i:012x}" for i in range(5)))
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "ok"
    assert "private-customer" not in json.dumps(result)
    assert "synthetic-token" not in json.dumps(result)


@pytest.mark.parametrize("change", [{"state": "raw-private-message"}, {"health": "raw-private-message"}, {"restart_count": True}, {"oom_killed": "no"}, {"exit_code": -1}])
def test_invalid_service_payload_is_not_echoed(monkeypatch, tmp_path, change):
    states = rows()
    states[0].update(change)
    fake_docker(monkeypatch, states=states)
    result = health.collect("devpilot-local", 1, tmp_path)
    assert result["status"] == "fail"
    assert "raw-private-message" not in json.dumps(result)


@pytest.mark.parametrize("project,timeout", [("-invalid", 1), ("private;rm", 1), ("A", 1), ("a" * 65, 1), ("devpilot-local", 0), ("devpilot-local", float("nan")), ("devpilot-local", 31)])
def test_invalid_inputs_fail_before_running_docker(monkeypatch, tmp_path, project, timeout):
    calls = fake_docker(monkeypatch)
    with pytest.raises(ValueError):
        health.collect(project, timeout, tmp_path)
    assert calls == []


def test_runner_timeout_hides_raw_output_and_disables_shell(monkeypatch):
    def fail(args, **kw):
        assert args == ["docker", "info"]
        assert kw["shell"] is False and kw["timeout"] == 0.1
        assert kw["stdin"] == subprocess.DEVNULL and kw["stderr"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired(args, 0.1, output=b"private-customer-token")

    monkeypatch.setattr(health.subprocess, "run", fail)
    with pytest.raises(health.ProbeError, match="^command_timeout$"):
        health.run_docker(["info"], 0.1)


@pytest.mark.parametrize("payload", [b"ok", b"x" * (64 * 1024 + 1), b"\xff"], ids=["valid", "oversized", "invalid-utf8"])
def test_runner_reads_bounded_utf8_output(monkeypatch, payload):
    def complete(args, **kw):
        kw["stdout"].write(payload)
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(health.subprocess, "run", complete)
    if payload == b"ok":
        assert health.run_docker(["info"], 1) == "ok"
    else:
        with pytest.raises(health.ProbeError, match="^invalid_response$"):
            health.run_docker(["info"], 1)


def test_nonzero_runner_never_exposes_raw_stderr(monkeypatch):
    def fail(args, **kw):
        kw["stdout"].write(b"private-customer-endpoint")
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(health.subprocess, "run", fail)
    with pytest.raises(health.ProbeError, match="^command_failed$"):
        health.run_docker(["info"], 1)


@pytest.mark.parametrize("status,expected", [("ok", 0), ("warn", 0), ("fail", 1)])
def test_cli_emits_only_safe_json_and_exit_code(monkeypatch, capsys, status, expected):
    monkeypatch.setattr(health, "collect", lambda *args: {"schema_version": 1, "status": status})
    assert health.main(["--project", "devpilot-local", "--timeout", "2"]) == expected
    assert json.loads(capsys.readouterr().out)["status"] == status


def test_total_cli_deadline_prevents_late_inspect(monkeypatch, tmp_path):
    calls = fake_docker(monkeypatch)
    ticks = iter([0, 0.2, 1.8, 3.1])
    monkeypatch.setattr(health.time, "monotonic", lambda: next(ticks))
    result = health.collect("devpilot-local", 1, tmp_path)
    assert len(calls) == 2
    assert result["docker"]["status"] == "ok"
    assert result["status"] == "fail"
    assert "service_inventory_command_timeout" in result["findings"]


@pytest.mark.parametrize("exception,code", [(FileNotFoundError("private-path"), "cli_missing"), (PermissionError("private-path"), "cli_unavailable")])
def test_runner_os_errors_never_expose_paths(monkeypatch, exception, code):
    def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(health.subprocess, "run", fail)
    with pytest.raises(health.ProbeError, match=f"^{code}$"):
        health.run_docker(["info"], 1)


def test_make_diagnostic_needs_no_backend_venv_or_automatic_recovery():
    makefile = (health.Path(health.__file__).resolve().parents[1] / "Makefile").read_text(encoding="utf-8")
    assert "docker-health:" in makefile
    target = makefile.split("\ndocker-health:\n", 1)[1].split("\n\n", 1)[0]
    assert "$(PYTHON) ./scripts/docker_health.py" in target
    assert all(value not in target for value in ("uv run", "restart", "prune", "down", "up -d"))
