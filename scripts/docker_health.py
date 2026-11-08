#!/usr/bin/env python3
"""Bounded, read-only Docker diagnostics; standard library only.

No restarts, builds, target/model calls, logs, environment, mount paths, image
names, credentials, or configuration files are read. A warning is not a root
cause diagnosis, and running containers do not prove application readiness.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SERVICES = ("gateway", "frontend", "nginx", "redis")
PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
ID_RE = re.compile(r"[0-9a-f]{12,64}")
MAX_CONTAINERS = 32
MAX_OUTPUT = 64 * 1024
MIN_DISK_BYTES = 5 * 1024**3
INFO_FORMAT = '{"cpu_count":{{.NCPU}},"memory_total_bytes":{{.MemTotal}}}'
STATE_FORMAT = (
    '{"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
    '"state":{{json .State.Status}},'
    '"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}"not_configured"{{end}},'
    '"restart_count":{{.RestartCount}},"oom_killed":{{.State.OOMKilled}},"exit_code":{{.State.ExitCode}}}'
)


class ProbeError(Exception):
    """A fixed public error code, never raw subprocess output."""


def run_docker(args: list[str], timeout: float) -> str:
    """Timeout kills/reaps the CLI child; never retries or changes daemon state."""
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                ["docker", *args],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
                shell=False,
            )
            if result.returncode:
                raise ProbeError("command_failed")
            output.seek(0)
            payload = output.read(MAX_OUTPUT + 1)
        if len(payload) > MAX_OUTPUT:
            raise ProbeError("invalid_response")
        return payload.decode("utf-8", errors="strict").strip()
    except FileNotFoundError:
        raise ProbeError("cli_missing") from None
    except subprocess.TimeoutExpired:
        raise ProbeError("command_timeout") from None
    except UnicodeError:
        raise ProbeError("invalid_response") from None
    except OSError:
        raise ProbeError("cli_unavailable") from None


def _storage(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path)
        if (
            type(usage.total) is not int
            or type(usage.free) is not int
            or not 0 <= usage.free <= usage.total
            or usage.total <= 0
        ):
            return {"status": "unknown"}
        low = usage.free < MIN_DISK_BYTES or usage.free / usage.total < 0.05
        return {
            "status": "warn" if low else "ok",
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }
    except OSError:
        return {"status": "unknown"}


def _integer(value, *, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value < 2**63


def _json(text: str):
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        raise ProbeError("invalid_response") from None


def collect(project: str, timeout: float, workspace: Path) -> dict:
    if (
        not PROJECT_RE.fullmatch(project)
        or not math.isfinite(timeout)
        or not 0 < timeout <= 30
    ):
        raise ValueError("Invalid project or timeout")
    system = (
        Path(Path(os.environ.get("SystemRoot", "C:/Windows")).anchor)
        if os.name == "nt"
        else Path("/")
    )
    storage = {"workspace": _storage(workspace), "system": _storage(system)}
    findings = []
    for scope, entry in storage.items():
        if entry["status"] == "warn":
            findings.append(f"low_{scope}_disk")
        elif entry["status"] == "unknown":
            findings.append(f"{scope}_disk_unknown")
    report = {
        "schema_version": 1,
        "status": "warn" if findings else "ok",
        "storage": storage,
        "docker": {"status": "unknown"},
        "services": {name: None for name in SERVICES},
        "findings": findings,
        "limits": {
            "command_timeout_seconds": timeout,
            "max_containers": MAX_CONTAINERS,
            "metadata_only": True,
        },
    }
    deadline = time.monotonic() + timeout * 3

    def command(args):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProbeError("command_timeout")
        return run_docker(args, min(timeout, remaining))

    phase = "docker"
    try:
        info = _json(command(["info", "--format", INFO_FORMAT]))
        if (
            not isinstance(info, dict)
            or not _integer(info.get("cpu_count"), minimum=1)
            or not _integer(info.get("memory_total_bytes"), minimum=1)
        ):
            raise ProbeError("invalid_response")
        report["docker"] = {
            "status": "ok",
            "cpu_count": info["cpu_count"],
            "memory_total_bytes": info["memory_total_bytes"],
        }
        phase = "service_inventory"
        text = command(
            [
                "ps",
                "--all",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.ID}}",
            ]
        )
        ids = text.splitlines() if text else []
        if (
            len(ids) > MAX_CONTAINERS
            or len(set(ids)) != len(ids)
            or any(not ID_RE.fullmatch(value) for value in ids)
        ):
            raise ProbeError("invalid_response")
        grouped = {name: [] for name in SERVICES}
        if ids:
            payload = command(["container", "inspect", "--format", STATE_FORMAT, *ids])
            lines = payload.splitlines()
            if len(lines) != len(ids):
                raise ProbeError("invalid_response")
            for line in lines:
                value = _json(line)
                if not isinstance(value, dict) or not isinstance(
                    value.get("service"), str
                ):
                    raise ProbeError("invalid_response")
                service = value["service"]
                if service not in SERVICES:
                    continue
                if (
                    value.get("state")
                    not in (
                        "created",
                        "running",
                        "paused",
                        "restarting",
                        "removing",
                        "exited",
                        "dead",
                    )
                    or value.get("health")
                    not in ("healthy", "unhealthy", "starting", "not_configured")
                    or not _integer(value.get("restart_count"))
                    or type(value.get("oom_killed")) is not bool
                    or not _integer(value.get("exit_code"))
                ):
                    raise ProbeError("invalid_response")
                grouped[service].append(
                    {
                        key: value[key]
                        for key in (
                            "state",
                            "health",
                            "restart_count",
                            "oom_killed",
                            "exit_code",
                        )
                    }
                )
        report["services"] = grouped
        for service, instances in grouped.items():
            if not instances:
                findings.append(f"missing_{service}")
                report["status"] = "fail"
            for instance in instances:
                if instance["state"] != "running" or instance["health"] == "unhealthy":
                    findings.append(f"not_ready_{service}")
                    report["status"] = "fail"
                for condition, code in (
                    (instance["health"] == "starting", "healthcheck_starting"),
                    (
                        instance["health"] == "not_configured",
                        "healthcheck_not_configured",
                    ),
                    (instance["restart_count"] > 0, "previous_restarts"),
                    (instance["oom_killed"], "previous_oom"),
                ):
                    if condition:
                        findings.append(f"{code}_{service}")
                        if report["status"] == "ok":
                            report["status"] = "warn"
    except ProbeError as exc:
        code = str(exc)
        report["status"] = "fail"
        if phase == "docker":
            report["docker"] = {"status": "fail", "reason": code}
        findings.append(f"{phase}_{code}")
    report["findings"] = sorted(set(findings))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default="devpilot-local",
        help="Compose project (default: devpilot-local)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5,
        help="Per-command seconds, 0 < value <= 30 (three commands maximum)",
    )
    args = parser.parse_args(argv)
    if (
        not PROJECT_RE.fullmatch(args.project)
        or not math.isfinite(args.timeout)
        or not 0 < args.timeout <= 30
    ):
        parser.error(
            "project must be 1-64 lowercase Compose characters; timeout must be finite and > 0 and <= 30"
        )
    report = collect(args.project, args.timeout, Path(__file__).resolve().parents[1])
    print(json.dumps(report, sort_keys=True, indent=2))
    return int(report["status"] == "fail")


if __name__ == "__main__":
    raise SystemExit(main())
