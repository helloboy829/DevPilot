import hashlib
import io
import os
import stat

import pytest

from app.evaluation.material_artifact_store import MaterialArtifactConflict, MaterialArtifactStore


def test_store_streams_bytes_and_returns_exact_digest(tmp_path):
    body = b"synthetic material\n" * 20
    store = MaterialArtifactStore(tmp_path / "materials", max_file_size_bytes=4096)

    result = store.write("mat_" + "a" * 32, io.BytesIO(body))

    assert result == {"size_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    assert store._path("mat_" + "a" * 32).read_bytes() == body


def test_store_rejects_oversize_without_publishing_partial_file(tmp_path):
    store = MaterialArtifactStore(tmp_path / "materials", max_file_size_bytes=3)

    with pytest.raises(ValueError, match="too large"):
        store.write("mat_" + "b" * 32, io.BytesIO(b"four"))

    assert list((tmp_path / "materials").rglob("*.bin")) == []
    assert list((tmp_path / "materials").rglob("*.tmp")) == []


def test_store_allows_same_content_retry_but_rejects_different_content(tmp_path):
    store = MaterialArtifactStore(tmp_path / "materials", max_file_size_bytes=64)
    artifact_id = "mat_" + "c" * 32

    first = store.write(artifact_id, io.BytesIO(b"first"))
    retry = store.write(artifact_id, io.BytesIO(b"first"))
    assert retry == first

    with pytest.raises(MaterialArtifactConflict):
        store.write(artifact_id, io.BytesIO(b"other"))
    assert store._path(artifact_id).read_bytes() == b"first"


def test_store_reads_bounded_content_and_checks_recorded_digest(tmp_path):
    store = MaterialArtifactStore(tmp_path / "materials", max_file_size_bytes=64)
    artifact_id = "mat_" + "f" * 32
    receipt = store.write(artifact_id, io.BytesIO(b"private"))

    assert store.read(artifact_id, expected_sha256=receipt["sha256"], expected_size_bytes=receipt["size_bytes"]) == b"private"
    with pytest.raises(MaterialArtifactConflict):
        store.read(artifact_id, expected_sha256="0" * 64, expected_size_bytes=7)
    with pytest.raises(MaterialArtifactConflict):
        store.read(artifact_id, expected_sha256=receipt["sha256"], expected_size_bytes=8)


@pytest.mark.parametrize("artifact_id", ["../escape", "mat_../escape", "mat_" + "G" * 32, "mat_" + "d" * 31])
def test_store_rejects_invalid_ids_without_escaping_root(tmp_path, artifact_id):
    root = tmp_path / "materials"
    store = MaterialArtifactStore(root, max_file_size_bytes=64)

    with pytest.raises(ValueError):
        store.write(artifact_id, io.BytesIO(b"payload"))

    assert not (tmp_path / "escape").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not portable to Windows")
def test_store_restricts_artifact_permissions_on_posix(tmp_path):
    artifact_id = "mat_" + "e" * 32
    store = MaterialArtifactStore(tmp_path / "materials", max_file_size_bytes=64)
    store.write(artifact_id, io.BytesIO(b"private"))

    path = next((tmp_path / "materials").rglob("*.bin"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
