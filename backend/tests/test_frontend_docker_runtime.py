"""Production frontend starts a prebuilt server, not a compiler/package manager."""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _stage(name: str) -> str:
    dockerfile = (ROOT / "frontend/Dockerfile").read_text(encoding="utf-8")
    stages = re.split(r"(?mi)^FROM .+ AS (\w+)\s*$", dockerfile)
    return dict(zip(stages[1::2], stages[2::2], strict=True))[name]


def test_production_command_directly_starts_prebuilt_next_server():
    prod = _stage("prod")
    command = re.search(r"(?m)^CMD (.+)$", prod)
    assert command is not None
    assert json.loads(command[1]) == [
        "node",
        "node_modules/next/dist/bin/next",
        "start",
        "--hostname",
        "0.0.0.0",
        "--port",
        "3000",
    ]
    assert "WORKDIR /app/frontend" in prod
    assert "ENV NODE_ENV=production" in prod


def test_production_stage_copies_build_without_installing_packages():
    builder, prod = _stage("builder"), _stage("prod")
    assert "pnpm build" in builder
    assert "COPY --from=builder /app/frontend ./" in prod
    # No package-manager downloads or compilation in the runtime stage.
    assert not re.search(r"(?m)^RUN\s", prod)
    assert not re.search(r"(?m)^ENTRYPOINT\s", prod)


def test_production_compose_preserves_image_start_command():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yaml").read_text(encoding="utf-8"))
    frontend = compose["services"]["frontend"]
    assert frontend["build"]["target"] == "prod"
    assert "command" not in frontend
    assert "entrypoint" not in frontend


def test_development_compose_keeps_explicit_hot_reload():
    compose = yaml.safe_load((ROOT / "docker/docker-compose-dev.yaml").read_text(encoding="utf-8"))
    frontend = compose["services"]["frontend"]
    assert frontend["build"]["target"] == "dev"
    assert re.search(r"pnpm (?:run )?dev\b", str(frontend["command"]))


def test_production_gateway_never_synchronizes_dependencies_at_startup():
    compose = yaml.safe_load((ROOT / "docker/docker-compose.yaml").read_text(encoding="utf-8"))
    command = compose["services"]["gateway"]["command"]
    assert "uv run --no-sync uvicorn app.gateway.app:app" in command
    assert "--workers ${GATEWAY_WORKERS:-1}" in command
    assert "uv run --no-sync" in (ROOT / "backend/Dockerfile").read_text(encoding="utf-8")
    dev = yaml.safe_load((ROOT / "docker/docker-compose-dev.yaml").read_text(encoding="utf-8"))
    assert "dev-entrypoint.sh" in str(dev["services"]["gateway"]["command"])
