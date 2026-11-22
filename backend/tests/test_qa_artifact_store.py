import hashlib
import os
import stat

import pytest
from cryptography.fernet import Fernet

import app.evaluation.qa_artifact_store as artifact_store_module
from app.evaluation.qa_artifact_store import ResponseArtifactStore
from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable


def _binding(**changes):
    value = {
        "owner_id": "owner-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "ordinal": 3,
        "sample_id": "sample-3",
        "plan_hash": "a" * 64,
    }
    return {**value, **changes}


def _performance_binding(**changes):
    value = {
        "owner_id": "owner-1",
        "project_id": "project-1",
        "run_id": "run-1",
        "ordinal": 0,
        "dispatch_id": "dispatch-1",
        "scenario_hash": "b" * 64,
    }
    return {**value, **changes}


def _metadata(body, **changes):
    value = {
        "capture_status": "complete",
        "hash_scope": "full",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "observed_bytes": len(body),
        "http_status": 200,
        "content_type": "application/json",
        "content_encoding": "identity",
    }
    return {**value, **changes}


@pytest.fixture
def artifact_store(tmp_path):
    return ResponseArtifactStore(tmp_path / "response-evidence", Fernet.generate_key())


@pytest.fixture
def range_artifact_store(tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    return ResponseArtifactStore(tmp_path / "response-evidence", Fernet.generate_key())


def test_publish_encrypts_raw_bytes_and_returns_a_verifiable_receipt(artifact_store):
    artifact_id = "1" * 32
    body = b"\x00native response\xff"

    metadata = _metadata(body)
    receipt = artifact_store.publish(artifact_id, body, _binding(), metadata)
    stored = artifact_store._path(artifact_id).read_bytes()

    assert stored != body
    assert body not in stored
    assert len(stored) > len(body) + 28
    assert receipt == {
        "artifact_id": artifact_id,
        "key_version": artifact_store.key_version,
        "capture_status": "complete",
        "hash_scope": "full",
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "body_bytes": len(body),
        "observed_bytes": len(body),
        "http_status": 200,
        "sealed_sha256": hashlib.sha256(stored).hexdigest(),
        "sealed_bytes": len(stored),
        "content_type": "application/json",
        "content_encoding": "identity",
    }
    assert artifact_store.open(artifact_id, _binding()) == (metadata, body)


@pytest.mark.parametrize("ordinal", [0, 10_999])
def test_performance_binding_allows_profile_observed_bytes_without_loosening_qa_limit(range_artifact_store, ordinal):
    body = b"x" * 1_048_576
    metadata = _metadata(body, capture_status="truncated", hash_scope="prefix", observed_bytes=10_000_000)
    artifact_id = f"{ordinal + 1:032x}"

    binding = _performance_binding(ordinal=ordinal)
    receipt = range_artifact_store.publish(artifact_id, body, binding, metadata)

    assert receipt["observed_bytes"] == 10_000_000
    assert range_artifact_store.open(artifact_id, binding) == (metadata, body)
    with pytest.raises(RequestProtectionError, match="Invalid response artifact"):
        range_artifact_store.publish("b" * 32, body, _binding(), metadata)


@pytest.mark.parametrize("ordinal", [0, 10_999])
def test_performance_binding_supports_full_ordinal_range_and_read_only_inspection(range_artifact_store, ordinal):
    artifact_id = f"{ordinal + 1:032x}"
    binding = _performance_binding(ordinal=ordinal)
    body = f"response-{ordinal}".encode()

    receipt = range_artifact_store.publish(artifact_id, body, binding, _metadata(body))

    assert range_artifact_store.inspect(artifact_id, binding) == receipt
    with pytest.raises(RequestProtectionError):
        range_artifact_store.inspect(artifact_id, _performance_binding(ordinal=ordinal, dispatch_id="other"))


@pytest.mark.skipif(os.name != "posix", reason="directory fsync durability is validated on POSIX")
def test_publish_syncs_directory_after_atomic_link(artifact_store, monkeypatch):
    artifact_store.root.mkdir(parents=True)
    (artifact_store.root / "77").mkdir()
    events = []
    original_fsync = os.fsync
    original_link = os.link

    def track_fsync(fd):
        events.append("directory_fsync" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file_fsync")
        return original_fsync(fd)

    def track_link(source, destination):
        result = original_link(source, destination)
        events.append("link")
        return result

    monkeypatch.setattr(artifact_store_module.os, "fsync", track_fsync)
    monkeypatch.setattr(artifact_store_module.os, "link", track_link)

    body = b"durable response"
    artifact_store.publish("7" * 32, body, _binding(), _metadata(body))

    assert events[-3:] == ["file_fsync", "link", "directory_fsync"]


@pytest.mark.skipif(os.name != "posix", reason="directory fsync durability is validated on POSIX")
def test_publish_does_not_return_receipt_when_directory_sync_fails(artifact_store, monkeypatch):
    original_fsync = os.fsync
    original_link = os.link
    linked = False

    artifact_store.root.mkdir(parents=True)
    (artifact_store.root / "88").mkdir()

    def mark_link(source, destination):
        nonlocal linked
        result = original_link(source, destination)
        linked = True
        return result

    def fail_directory_fsync(fd):
        if linked and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("synthetic directory sync failure")
        return original_fsync(fd)

    monkeypatch.setattr(artifact_store_module.os, "fsync", fail_directory_fsync)
    monkeypatch.setattr(artifact_store_module.os, "link", mark_link)
    body = b"durability is unknown"

    with pytest.raises(OSError, match="synthetic directory sync failure"):
        artifact_store.publish("8" * 32, body, _binding(), _metadata(body))


@pytest.mark.parametrize("operation", ["preflight", "publish"])
def test_non_posix_directory_durability_fails_closed(artifact_store, monkeypatch, operation):
    artifact_store.root.mkdir(parents=True)
    monkeypatch.setattr(artifact_store_module.os, "name", "nt")

    with pytest.raises(RequestProtectionUnavailable, match="(?i)durable"):
        if operation == "preflight":
            artifact_store.ensure_available()
        else:
            body = b"non-durable response"
            artifact_store.publish("9" * 32, body, _binding(), _metadata(body))

    assert not artifact_store._path("9" * 32).exists()


@pytest.mark.parametrize(
    ("status", "scope", "body", "observed_bytes"),
    [("partial", "prefix", b"prefix", 9), ("truncated", "prefix", b"limit", 6)],
)
def test_partial_and_truncated_artifacts_keep_only_prefix_hash_scope(artifact_store, status, scope, body, observed_bytes):
    artifact_id = "6" * 32
    metadata = _metadata(body, capture_status=status, hash_scope=scope, observed_bytes=observed_bytes)

    receipt = artifact_store.publish(artifact_id, body, _binding(), metadata)

    assert receipt["capture_status"] == status
    assert receipt["hash_scope"] == "prefix"
    assert receipt["body_sha256"] == hashlib.sha256(body).hexdigest()
    assert artifact_store.open(artifact_id, _binding()) == (metadata, body)


def test_publish_is_idempotent_for_the_same_id_and_cannot_replace_its_body(artifact_store):
    artifact_id = "2" * 32
    binding = _binding()
    body = b"first response"

    first = artifact_store.publish(artifact_id, body, binding, _metadata(body))
    second = artifact_store.publish(artifact_id, body, binding, _metadata(body))

    assert second == first
    with pytest.raises(RequestProtectionError):
        other = b"different response"
        artifact_store.publish(artifact_id, other, binding, _metadata(other))
    assert artifact_store.open(artifact_id, binding)[1] == body


def test_artifact_context_prevents_cross_run_reads(artifact_store):
    artifact_id = "3" * 32
    body = b"private response"
    artifact_store.publish(artifact_id, body, _binding(), _metadata(body))

    with pytest.raises(RequestProtectionError):
        artifact_store.open(artifact_id, _binding(project_id="other-project"))


def test_open_range_returns_only_requested_inclusive_bytes(range_artifact_store):
    artifact_id = "a" * 32
    body = b"0123456789"
    range_artifact_store.publish(artifact_id, body, _binding(), _metadata(body))

    metadata, ranged, content_range = range_artifact_store.open_range(artifact_id, _binding(), "bytes=2-5")

    assert metadata == _metadata(body)
    assert ranged == b"2345"
    assert content_range == "bytes 2-5/10"


@pytest.mark.parametrize("range_header", ["bytes=5-2", "bytes=10-", "bytes=0-1,4-5", "items=0-1", "bytes=-0"])
def test_open_range_rejects_invalid_or_unsatisfiable_ranges(range_artifact_store, range_header):
    artifact_id = "b" * 32
    body = b"0123456789"
    range_artifact_store.publish(artifact_id, body, _binding(), _metadata(body))

    with pytest.raises(RequestProtectionError, match="range"):
        range_artifact_store.open_range(artifact_id, _binding(), range_header)


def test_open_range_caps_large_end_at_frozen_body_length(range_artifact_store):
    artifact_id = "c" * 32
    body = b"0123456789"
    range_artifact_store.publish(artifact_id, body, _binding(), _metadata(body))

    _, ranged, content_range = range_artifact_store.open_range(artifact_id, _binding(), "bytes=7-999999")

    assert ranged == b"789"
    assert content_range == "bytes 7-9/10"


def test_inspect_is_read_only_and_reports_only_sealed_object_metadata(artifact_store):
    artifact_id = "4" * 32

    binding = _binding()
    assert artifact_store.inspect(artifact_id, binding) is None
    assert not artifact_store.root.exists()

    body = b"private response"
    receipt = artifact_store.publish(artifact_id, body, binding, _metadata(body))
    inspected = artifact_store.inspect(artifact_id, binding)

    assert inspected == receipt


@pytest.mark.parametrize("artifact_id", ["../escape", "A" * 32, "a" * 31, "a" * 33])
def test_artifact_id_cannot_select_a_path(artifact_store, artifact_id):
    with pytest.raises(RequestProtectionError):
        artifact_store.inspect(artifact_id, _binding())


def test_corrupt_ciphertext_is_rejected(artifact_store):
    artifact_id = "5" * 32
    body = b"private response"
    artifact_store.publish(artifact_id, body, _binding(), _metadata(body))
    artifact_store._path(artifact_id).write_bytes(b"x" * 44)

    with pytest.raises(RequestProtectionError):
        artifact_store.open(artifact_id, _binding())
