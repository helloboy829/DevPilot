"""Pin fail-loud repo-root resolution and the shared CLI shim for the detector tooling.

The failure mode being guarded: depth-indexed `parents[N]` resolution from a
relocated detector file silently resolves a wrong root, scans nothing, and
reports zero findings. Resolution must instead raise when no repository
marker is found.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from support.detectors import blocking_io_changed, blocking_io_static, thread_boundaries
from support.detectors.repo_root import resolve_repo_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_resolve_repo_root_finds_marker_from_detector_location():
    resolved = resolve_repo_root(Path(blocking_io_static.__file__))
    assert resolved == REPO_ROOT
    assert (resolved / ".git").exists()


def test_all_detectors_share_the_resolved_root():
    assert blocking_io_static.REPO_ROOT == REPO_ROOT
    assert blocking_io_changed.REPO_ROOT == REPO_ROOT
    assert thread_boundaries.REPO_ROOT == REPO_ROOT


def test_unmarked_location_raises_instead_of_scanning_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    start = (tmp_path / "moved" / "detectors" / "blocking_io_static.py").resolve()
    checked_markers: list[Path] = []

    def no_marker_exists(path: Path) -> bool:
        assert path.name == ".git"
        checked_markers.append(path)
        return False

    # A caller may put pytest's basetemp inside this checkout. Simulate the
    # missing-marker filesystem, never remove or rely on real ancestor markers.
    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", no_marker_exists)
        with pytest.raises(RuntimeError, match=r"\.git"):
            resolve_repo_root(start)

    assert checked_markers == [candidate / ".git" for candidate in (start, *start.parents)]


@pytest.mark.parametrize("marker_kind", ["directory", "file"])
def test_resolve_repo_root_finds_nearest_directory_or_worktree_marker(tmp_path: Path, marker_kind: str):
    outer = tmp_path / "outer-repo"
    outer.mkdir()
    (outer / ".git").mkdir()
    nested = outer / "nested" / "worktree"
    nested.mkdir(parents=True)
    marker = nested / ".git"
    if marker_kind == "directory":
        marker.mkdir()
    else:
        marker.write_text("gitdir: ../private-worktree-metadata\n", encoding="utf-8")

    start = nested / "arbitrary" / "relocated" / "depth" / "detector.py"
    assert resolve_repo_root(start) == nested.resolve()


def test_cli_shims_delegate_to_their_detectors(capsys: pytest.CaptureFixture[str]):
    # conftest puts scripts/ on sys.path; --help proves the shim resolves and
    # invokes the right detector main without running a scan.
    import detect_blocking_io_static
    import detect_thread_boundaries
    import scan_changed_blocking_io

    for shim, description_fragment in (
        (detect_blocking_io_static, "Statically inventory blocking IO calls"),
        (detect_thread_boundaries, "Inventory backend thread/executor/event-loop boundaries"),
        (scan_changed_blocking_io, "blocking-IO candidates this change introduces"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            shim.main(["--help"])
        assert excinfo.value.code == 0
        assert description_fragment in capsys.readouterr().out
