"""The backend image must ship the sibling toolkit its pyproject resolves by path.

``backend/pyproject.toml`` declares ``devpilot`` as an editable path source
(``path = "../devpilot"``), so ``uv sync`` inside the builder needs
``/app/devpilot`` to exist. The Dockerfile previously copied only ``backend``,
and a clean build failed with ``Distribution not found at: file:///app/devpilot``.
The runtime image needs the same sources because the editable install points at
``/app/devpilot/src`` rather than at a wheel.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _stages() -> list[tuple[str | None, str]]:
    """Split backend/Dockerfile into (alias, body) stages; the last one is runtime."""

    dockerfile = (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    parts = re.split(r"(?mi)^FROM\s+(?P<image>[^\s]+)(?:\s+AS\s+(?P<alias>\w+))?\s*$", dockerfile)
    # parts = [preamble, image, alias, body, image, alias, body, ...]
    stages: list[tuple[str | None, str]] = []
    for index in range(1, len(parts), 3):
        alias = parts[index + 1]
        stages.append((alias or None, parts[index + 2]))
    return stages


def _stage(alias: str | None) -> str:
    for name, body in _stages():
        if name == alias:
            return body
    raise AssertionError(f"stage {alias!r} not found in backend/Dockerfile")


def test_pyproject_still_resolves_devpilot_from_a_sibling_path():
    with (ROOT / "backend/pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)

    assert "devpilot" in project["project"]["dependencies"]
    source = project["tool"]["uv"]["sources"]["devpilot"]
    assert source["path"] == "../devpilot"


def test_builder_copies_devpilot_before_synchronizing_dependencies():
    builder = _stage("builder")
    copy_index = builder.find("COPY devpilot ./devpilot")
    sync_index = builder.find("uv sync --extra redis")
    assert sync_index != -1, "builder is expected to run uv sync"

    assert copy_index != -1, "builder must copy the devpilot path source"
    assert sync_index != -1, "builder is expected to run uv sync"
    assert copy_index < sync_index, "uv sync cannot resolve devpilot copied afterwards"


def test_runtime_stage_carries_the_editable_source_from_the_builder():
    stages = _stages()
    assert stages[-1][0] is None, "the last Dockerfile stage is the runtime image"
    runtime = stages[-1][1]

    assert "COPY --from=builder /app/devpilot ./devpilot" in runtime


def test_development_compose_mounts_the_same_toolkit_path():
    compose = yaml.safe_load((ROOT / "docker/docker-compose-dev.yaml").read_text(encoding="utf-8"))
    volumes = compose["services"]["gateway"]["volumes"]

    mounts = {(source.rstrip("/"), target.rstrip("/")) for source, target, *_ in (str(volume).split(":") for volume in volumes) if source and target}

    assert ("../devpilot", "/app/devpilot") in mounts, "the dev gateway must mount the host toolkit at the image's resolved path"
