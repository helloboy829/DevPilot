"""Collect synthetic copies only; never run LLMs or inherit real credentials."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def collect(tmp_path, *, opt_in=False, ci=False, key=True, dotenv_opt_in=False, offline=False, preload_dotenv=False):
    tests = tmp_path / "repo" / "backend" / "tests"
    tests.mkdir(parents=True)
    source = BACKEND / "tests" / "test_client_e2e.py"
    (tests / source.name).write_text(source.read_text(encoding="utf8"), encoding="utf8")
    dotenv_path = tests.parents[1] / ".env"
    dotenv_path.write_text("DEER_FLOW_RUN_LIVE_TESTS=1\nOPENAI_API_KEY=SYNTHETIC_NOT_A_KEY\n" if dotenv_opt_in else "", encoding="utf8")
    # Redirect every dotenv read, including imports of the real app_config, to
    # the synthetic repo. Copy the actual session policy rather than simulating it.
    isolation = (
        "import json, socket, dotenv\n"
        "def blocked(*a, **kw): raise AssertionError('Network forbidden during collection')\n"
        "socket.socket.connect = blocked\n"
        "socket.socket.connect_ex = blocked\n"
        "_original_load_dotenv = dotenv.load_dotenv\n"
        f"def isolated_dotenv(*a, **kw): return _original_load_dotenv({str(dotenv_path)!r})\n"
        "dotenv.load_dotenv = isolated_dotenv\n"
        "def pytest_collection_finish(session):\n"
        " rows = []\n"
        " for item in session.items:\n"
        "  skipped = item.get_closest_marker('skip') is not None or any(bool(m.args[0]) for m in item.iter_markers('skipif'))\n"
        "  rows.append({'node': item.nodeid, 'live': item.get_closest_marker('live') is not None, 'skip': skipped})\n"
        " print('SYNTHETIC_POLICY_RECEIPT=' + json.dumps(rows))\n"
    )
    # A nested conftest executes after the real parent session gate captures env.
    (tests.parent / "conftest.py").write_text((BACKEND / "tests" / "conftest.py").read_text(encoding="utf8"), encoding="utf8")
    (tests / "conftest.py").write_text(isolation, encoding="utf8")
    if preload_dotenv:
        (tests / "test_000_dotenv.py").write_text("import dotenv\ndotenv.load_dotenv()\n", encoding="utf8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(BACKEND),
        "PYTHONIOENCODING": "utf8",
        "PYTHONUTF8": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    # Windows requires its system root for Winsock; never inherit credentials.
    for name in ("SYSTEMROOT", "WINDIR"):
        if name in os.environ:
            env[name] = os.environ[name]
    if key:
        env["OPENAI_API_KEY"] = "SYNTHETIC_NOT_A_KEY"
    if opt_in:
        env["DEER_FLOW_RUN_LIVE_TESTS"] = "1"
    if ci:
        env["CI"] = "true"
    args = [sys.executable, "-m", "pytest", "-c", str(BACKEND / "pyproject.toml"), "--collect-only", "-q", "-s", "-p", "no:cacheprovider", str(tests)]
    if offline:
        args += ["-m", "not live"]
    result = subprocess.run(args, cwd=tests.parent, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = next(line.split("=", 1)[1] for line in result.stdout.splitlines() if line.startswith("SYNTHETIC_POLICY_RECEIPT="))
    return json.loads(receipt)


@pytest.mark.parametrize("options", [{}, {"opt_in": True}, {"key": False, "dotenv_opt_in": True, "preload_dotenv": True}])
def test_default_offline_selection_excludes_llm_but_keeps_filesystem_tests(tmp_path, options):
    rows = collect(tmp_path, offline=True, **options)
    assert rows and not any("TestBasicChat" in row["node"] for row in rows)
    assert any("TestFileUploadIntegration" in row["node"] for row in rows)
    assert not any(row["live"] for row in rows)


@pytest.mark.parametrize(
    "options,skip",
    [
        ({}, True),
        ({"opt_in": True}, False),
        ({"opt_in": True, "ci": True}, True),
        ({"opt_in": True, "key": False}, True),
        ({"key": False, "dotenv_opt_in": True}, True),
        ({"key": False, "dotenv_opt_in": True, "preload_dotenv": True}, True),
    ],
)
def test_direct_collection_requires_explicit_process_opt_in_and_key(tmp_path, options, skip):
    rows = collect(tmp_path, **options)
    live = [row for row in rows if row["live"]]
    assert len(live) == 11
    assert all(row["skip"] is skip for row in live)
    assert all(row["live"] for row in rows if "TestBasicChat" in row["node"])
    assert not any(row["skip"] for row in rows if not row["live"])
