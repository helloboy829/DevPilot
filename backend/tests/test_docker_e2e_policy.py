"""Collect Docker integration tests without ever executing a Docker command."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "opt_in,ci,late_opt_in,skipped",
    [(False, False, False, True), (True, False, False, False), (True, True, False, True), (False, False, True, True)],
)
def test_docker_collection_requires_explicit_process_opt_in(tmp_path, opt_in, ci, late_opt_in, skipped):
    tests = tmp_path / "repo" / "tests"
    tests.mkdir(parents=True)
    source = BACKEND / "tests" / "test_sandbox_orphan_reconciliation_e2e.py"
    (tests / source.name).write_text(source.read_text(encoding="utf8"), encoding="utf8")
    (tests.parent / "conftest.py").write_text((BACKEND / "tests" / "conftest.py").read_text(encoding="utf8"), encoding="utf8")
    isolation = (
        "import json, os, subprocess\n"
        "def blocked(*a, **kw): raise AssertionError('Docker commands forbidden during collection')\n"
        "subprocess.run = blocked\n"
        "def pytest_collection_finish(session):\n"
        " rows = []\n"
        " for item in session.items:\n"
        "  skipped = item.get_closest_marker('skip') is not None\n"
        "  rows.append({'docker': item.get_closest_marker('docker') is not None, 'skip': skipped})\n"
        " print('SYNTHETIC_DOCKER_POLICY=' + json.dumps(rows))\n"
    )
    if late_opt_in:
        isolation += "os.environ['DEVPILOT_RUN_DOCKER_TESTS'] = '1'\n"
    (tests / "conftest.py").write_text(isolation, encoding="utf8")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(BACKEND), "PYTHONIOENCODING": "utf8", "PYTHONUTF8": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    if opt_in:
        env["DEVPILOT_RUN_DOCKER_TESTS"] = "1"
    if ci:
        env["CI"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-c", str(BACKEND / "pyproject.toml"), "--collect-only", "-q", "-s", "-p", "no:cacheprovider", str(tests)],
        cwd=tests.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("SYNTHETIC_DOCKER_POLICY="))
    rows = json.loads(receipt)
    assert len(rows) == 3
    assert all(row["docker"] and row["skip"] is skipped for row in rows)


@pytest.fixture
def lifecycle_module():
    spec = importlib.util.spec_from_file_location("synthetic_docker_lifecycle", BACKEND / "tests" / "test_sandbox_orphan_reconciliation_e2e.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_never_pulls_or_mounts_and_records_intent_before_timeout(lifecycle_module, monkeypatch):
    module = lifecycle_module
    calls = []

    def timeout(args, **kwargs):
        calls.append(args)
        assert "synthetic-attempt" in module._START_ATTEMPTS
        raise subprocess.TimeoutExpired(args, 30)

    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        module._start_test_container("synthetic-attempt")
    args = calls[0]
    assert "--pull=never" in args
    assert args[args.index("--network") + 1] == "none"
    assert args[args.index("--label") + 1] == f"{module._RUN_LABEL}={module._RUN_ID}"
    assert not any(arg in args for arg in ("-v", "--volume", "--mount", "-p", "--publish", "--privileged", "--force"))


@pytest.mark.parametrize("ownership,returncode,stopped", [("same", 0, True), ("other-run", 0, False), ("", 1, False)])
def test_cleanup_requires_both_recorded_name_and_matching_run_label(lifecycle_module, monkeypatch, ownership, returncode, stopped):
    module = lifecycle_module
    calls = []
    module._START_ATTEMPTS.add("synthetic-owned")

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=returncode, stdout=module._RUN_ID if ownership == "same" else ownership)

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module._stop_container("unrecorded-name")
    assert not calls
    module._stop_container("synthetic-owned")
    assert calls[0] == ["docker", "inspect", "-f", '{{index .Config.Labels "' + module._RUN_LABEL + '"}}', "synthetic-owned"]
    assert (len(calls) == 2) is stopped
    if stopped:
        assert calls[1] == ["docker", "stop", "--time", "2", "synthetic-owned"]
    assert not any("--force" in args or "-f" in args and "rm" in args for args in calls)
