"""Synthetic offline tests for the read-only Windows acceptance preflight."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace

import windows_acceptance_preflight as preflight

GIB = 1024**3


def passing():
    return preflight.evaluate_preflight(
        platform="win32",
        docker_available=True,
        port_in_use=False,
        free_bytes=20 * GIB,
        config_present=True,
        extensions_present=True,
        port=2026,
    )


def test_passing_preflight_is_diagnostic_only():
    result = passing()
    assert result == {
        "schema": "windows-acceptance-preflight.v1",
        "scope": "host_prerequisite_diagnostic_only",
        "platform": "win32",
        "port": 2026,
        "checks": {
            "windows": True,
            "docker_cli": True,
            "port_free": True,
            "disk_space": True,
            "private_config_present": True,
        },
        "blockers": [],
        "content_status": "not_inspected",
        "deployment_authorized": False,
        "approval": "not_approved",
    }


def test_each_missing_prerequisite_is_a_fixed_blocker():
    cases = (
        ({"platform": "linux"}, "not_windows"),
        ({"docker_available": False}, "docker_cli_missing"),
        ({"port_in_use": True}, "port_in_use"),
        ({"free_bytes": 9 * GIB}, "insufficient_disk"),
        ({"config_present": False}, "private_config_missing"),
        ({"extensions_present": False}, "private_config_missing"),
    )
    for override, blocker in cases:
        values = {
            "platform": "win32",
            "docker_available": True,
            "port_in_use": False,
            "free_bytes": 20 * GIB,
            "config_present": True,
            "extensions_present": True,
            "port": 2026,
        }
        values.update(override)
        result = preflight.evaluate_preflight(**values)
        assert blocker in result["blockers"]
        assert result["deployment_authorized"] is False
        assert result["approval"] == "not_approved"


def test_port_must_be_loopback_diagnostic_range():
    try:
        preflight.evaluate_preflight(
            platform="win32",
            docker_available=True,
            port_in_use=False,
            free_bytes=20 * GIB,
            config_present=True,
            extensions_present=True,
            port=0,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("port 0 must be rejected")


def test_cli_prints_json_and_never_inspects_config(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "_probe",
        lambda port: SimpleNamespace(
            platform="win32",
            docker_available=True,
            port_in_use=False,
            free_bytes=20 * GIB,
            config_present=True,
            extensions_present=True,
        ),
    )
    output = io.StringIO()
    with redirect_stdout(output):
        code = preflight.main(["--port", "2026"])
    assert code == 0
    assert json.loads(output.getvalue())["schema"] == "windows-acceptance-preflight.v1"


def test_cli_returns_nonzero_when_blocked(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "_probe",
        lambda port: SimpleNamespace(
            platform="linux",
            docker_available=False,
            port_in_use=True,
            free_bytes=0,
            config_present=False,
            extensions_present=False,
        ),
    )
    output = io.StringIO()
    with redirect_stdout(output):
        code = preflight.main([])
    assert code == 1
    assert "not_windows" in json.loads(output.getvalue())["blockers"]
