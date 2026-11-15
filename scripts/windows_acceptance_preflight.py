"""Read-only Windows acceptance prerequisite diagnostic; never deploys or reads config.

Checks platform, Docker CLI presence, loopback port availability, free disk and
private-config file presence only. It never opens config contents, starts
services, calls models/targets or grants deployment/approval authority.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

_ERROR = "Invalid Windows preflight request"
_MIN_FREE_BYTES = 10 * 1024**3
_ROOT = Path(__file__).resolve().parents[1]


def evaluate_preflight(*, platform, docker_available, port_in_use, free_bytes, config_present, extensions_present, port):
    """Return the fixed projection; inputs are supplied by the caller/probe."""
    if type(port) is not int or not 1 <= port <= 65_535:
        raise ValueError(_ERROR)
    blockers = []
    if platform != "win32":
        blockers.append("not_windows")
    if docker_available is not True:
        blockers.append("docker_cli_missing")
    if port_in_use is not False:
        blockers.append("port_in_use")
    if type(free_bytes) is not int or free_bytes < _MIN_FREE_BYTES:
        blockers.append("insufficient_disk")
    if config_present is not True or extensions_present is not True:
        blockers.append("private_config_missing")
    return {
        "schema": "windows-acceptance-preflight.v1",
        "scope": "host_prerequisite_diagnostic_only",
        "platform": platform,
        "port": port,
        "checks": {
            "windows": platform == "win32",
            "docker_cli": docker_available is True,
            "port_free": port_in_use is False,
            "disk_space": type(free_bytes) is int and free_bytes >= _MIN_FREE_BYTES,
            "private_config_present": config_present is True and extensions_present is True,
        },
        "blockers": sorted(blockers),
        "content_status": "not_inspected",
        "deployment_authorized": False,
        "approval": "not_approved",
    }


def _probe(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        port_in_use = probe.connect_ex(("127.0.0.1", port)) == 0
    return SimpleNamespace(
        platform=sys.platform,
        docker_available=shutil.which("docker") is not None,
        port_in_use=port_in_use,
        free_bytes=shutil.disk_usage(_ROOT).free,
        config_present=(_ROOT / "config.yaml").is_file(),
        extensions_present=(_ROOT / "extensions_config.json").is_file(),
    )


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(_ERROR)

    parser = Parser(description="Read-only Windows host prerequisite diagnostic. Never deploys, reads config or calls models.", allow_abbrev=False)
    parser.add_argument("--port", type=int, default=2026)
    try:
        args = parser.parse_args(argv)
        probe = _probe(args.port)
        result = evaluate_preflight(
            platform=probe.platform,
            docker_available=probe.docker_available,
            port_in_use=probe.port_in_use,
            free_bytes=probe.free_bytes,
            config_present=probe.config_present,
            extensions_present=probe.extensions_present,
            port=args.port,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if not result["blockers"] else 1
    except KeyboardInterrupt:
        print(_ERROR, file=sys.stderr)
        return 130
    except Exception:
        print(_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
