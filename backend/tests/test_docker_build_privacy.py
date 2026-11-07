"""Build contexts must not contain local customer facts or credentials."""

from pathlib import Path


def test_docker_context_excludes_private_runtime_files():
    root = Path(__file__).resolve().parents[2]
    patterns = set((root / ".dockerignore").read_text().splitlines())
    assert {".deer-flow/", "config.yaml", "extensions_config.json", "**/.env", "**/.env.*"} <= patterns


def test_project_draft_downloads_are_gitignored():
    root = Path(__file__).resolve().parents[2]
    patterns = set((root / ".gitignore").read_text().splitlines())
    assert {"project-evaluation-draft.md", "project-evaluation-draft.json"} <= patterns
