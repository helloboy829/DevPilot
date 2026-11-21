"""Unit tests for docker/dev-entrypoint.sh (UV_EXTRAS validation + parsing).

Exercises the script via its `--print-extras` dry-run hook so we don't actually
launch uvicorn or hit /app/logs. Together with test_detect_uv_extras.py these
cover both the local make-dev path and the docker-compose-dev path with the
same shape — see PR #2767 / Issue #2754.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "dev-entrypoint.sh"
DEV_COMPOSE = REPO_ROOT / "docker" / "docker-compose-dev.yaml"


def test_dev_compose_uses_healthy_postgres_by_default():
    compose = yaml.safe_load(DEV_COMPOSE.read_text(encoding="utf-8"))

    postgres = compose["services"]["postgres"]
    gateway = compose["services"]["gateway"]

    assert postgres["image"].startswith("postgres:")
    assert any("pg_isready" in item for item in postgres["healthcheck"]["test"])
    assert "postgres-data:/var/lib/postgresql/data" in postgres["volumes"]
    assert any(value.startswith("DATABASE_URL=${DATABASE_URL:-postgresql://") for value in gateway["environment"])
    assert gateway["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_default_host_install_includes_postgres_extra():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "cd backend && uv sync --extra postgres" in makefile


def _run(uv_extras: str | None, *, config: str | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke `dev-entrypoint.sh --print-extras` with UV_EXTRAS set."""
    env = os.environ.copy()
    env.pop("UV_EXTRAS", None)
    if uv_extras is not None:
        env["UV_EXTRAS"] = uv_extras
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        (project_root / "scripts").mkdir()
        (project_root / "scripts" / "detect_uv_extras.py").write_bytes((REPO_ROOT / "scripts" / "detect_uv_extras.py").read_bytes())
        if config is not None:
            (project_root / "config.yaml").write_text(config, encoding="utf-8")
        env["DEVPILOT_PROJECT_ROOT"] = str(project_root)
        env["DEER_FLOW_CONFIG_PATH"] = str(project_root / "config.yaml")
        return subprocess.run(
            ["sh", str(ENTRYPOINT), "--print-extras"],
            env=env,
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )


def test_entrypoint_script_exists_and_is_posix_sh():
    assert ENTRYPOINT.is_file()
    # Catch syntax errors before runtime — `sh -n` is a parse-only check.
    proc = subprocess.run(["sh", "-n", str(ENTRYPOINT)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def test_entrypoint_excludes_runtime_state_from_uvicorn_reload():
    content = ENTRYPOINT.read_text(encoding="utf-8")

    assert ': "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"' in content
    # sandbox must be created too, not just .deer-flow (#3459 / #3454).
    assert 'mkdir -p "$DEER_FLOW_HOME" /app/backend/.deer-flow /app/backend/sandbox' in content
    assert "--reload-include='*.yaml .env'" not in content
    assert "--reload-include='*.yaml'" in content
    assert "--reload-include='.env'" in content
    assert "--reload-exclude=/app/backend/sandbox" in content
    assert '--reload-exclude="$DEER_FLOW_HOME"' in content
    assert "--reload-exclude=/app/backend/.deer-flow" in content


def test_production_image_installs_postgres_by_default():
    dockerfile = (REPO_ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert "uv sync --extra redis $extras_flags --extra postgres" in dockerfile


def test_docker_launcher_loads_database_url_from_project_env_file():
    launcher = (REPO_ROOT / "scripts" / "docker.sh").read_text(encoding="utf-8")
    assert "load_compose_env_from_dotenv" in launcher
    env_vars = next(line for line in launcher.splitlines() if line.lstrip().startswith("for var in "))
    assert "DATABASE_URL" in env_vars


def test_default_config_backend_yields_postgres_flags():
    proc = _run(None)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_explicit_sqlite_config_yields_no_postgres_flag():
    proc = _run(None, config="database:\n  backend: sqlite\n")
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_config_backend_selects_postgres_extra_automatically():
    proc = _run(None, config="database:\n  backend: postgres\n")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_single_extra():
    proc = _run("postgres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


def test_multi_extra_comma_separated():
    proc = _run("postgres,ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_whitespace_separated():
    proc = _run("postgres ollama")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_multi_extra_mixed_separators():
    proc = _run(" postgres ,  ollama ,")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres --extra ollama"


def test_empty_string_uses_default_postgres_backend():
    proc = _run("")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra postgres"


@pytest.mark.parametrize(
    "bad_value",
    [
        "; rm -rf /",  # the canonical injection attempt
        "$(whoami)",  # command substitution
        "`echo bad`",  # backticks
        "postgres;evil",  # mixed legal+illegal in a single token
        "1postgres",  # leading digit
        "-postgres",  # leading hyphen
        "post gres extra/path",  # contains slash
    ],
)
def test_metacharacters_abort_with_nonzero_exit(bad_value):
    proc = _run(bad_value)
    assert proc.returncode != 0, f"expected abort for {bad_value!r}, got 0"
    assert "is invalid" in proc.stderr
    assert proc.stdout.strip() == ""


def test_underscores_and_hyphens_in_name_are_allowed():
    """Mirrors uv's accepted shape for `[project.optional-dependencies]` keys."""
    proc = _run("post_gres,post-gres")
    assert proc.returncode == 0
    assert proc.stdout.strip() == "--extra post_gres --extra post-gres"
