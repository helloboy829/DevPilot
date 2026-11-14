"""Synthetic incomplete-output retention tests; no decryption, wire or private data."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from devpilot.local_qa_cli import LocalRunManifest
from devpilot.local_qa_retention import (
    create_retention_receipt,
    dispose_incomplete_output,
    inspect_retention,
    reconcile_incomplete_disposal,
)
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate


@pytest.fixture
def manifest():
    return LocalRunManifest(
        RequestTemplate("POST", "https://example.test:443", ("Authorization",)),
        QAJSONBinding("/q", "/a"),
        2,
        5,
        2,
        1000,
        10000,
        128,
        4096,
        645,
    )


def prepare(tmp_path, manifest, *, now=1000, output=b""):
    directory = tmp_path / "retention"
    lease = create_retention_receipt(
        directory,
        str(uuid4()),
        manifest,
        retention_seconds=300,
        now_ms=lambda: now,
    )
    receipt = json.loads((directory / "retention-receipt.json").read_text())
    lease.close()
    if output is not None:
        (directory / "observations.encrypted.jsonl").write_bytes(output)
        if os.name == "posix":
            (directory / "observations.encrypted.jsonl").chmod(0o600)
    return directory, receipt


def test_receipt_is_durable_before_any_output_header(manifest, tmp_path):
    directory = tmp_path / "retention"
    lease = create_retention_receipt(directory, str(uuid4()), manifest, retention_seconds=300, now_ms=lambda: 1000)
    try:
        assert (directory / "retention-receipt.json").is_file()
        assert not (directory / "observations.encrypted.jsonl").exists()
        payload = json.loads((directory / "retention-receipt.json").read_text())
        assert payload["schema"] == "local-qa-output-retention.v1"
        assert payload["output_file"] == "observations.encrypted.jsonl"
        encoded = (directory / "retention-receipt.json").read_bytes()
        assert hashlib.sha256(encoded).hexdigest() == lease.receipt_sha256
        assert "key" not in json.dumps(payload).lower()
    finally:
        lease.close()


@pytest.mark.parametrize("output", [b"", b'{"schema":', b"garbled-token", b"not-a-valid-chain\\n"])
def test_retention_inspection_never_authenticates_partial_content(manifest, tmp_path, output):
    directory, receipt = prepare(tmp_path, manifest, output=output)
    result = inspect_retention(
        directory,
        expected_run_id=receipt["run_id"],
        expected_manifest_fingerprint=manifest.fingerprint,
        now_ms=lambda: 1001,
    )
    assert result["content_status"] == "not_inspected"
    assert not result["output_integrity_verified"]
    assert not result["final_record_verified"]
    assert result["verdict"] == "NOT_EVALUATED"
    assert not result["resend_permitted"] and not result["resume_permitted"]
    assert not result["platform_provenance_verified"]
    assert result["source_ciphertext_sha256"] == hashlib.sha256(output).hexdigest()
    assert result["retention_receipt_sha256"] == hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest()
    for field in ("input_count", "request_count", "concurrency", "timeout_ms", "duration_ms", "max_response_bytes", "max_total_request_bytes", "max_total_response_bytes"):
        assert result[field] == getattr(manifest, field)


def test_retention_inspection_allows_receipt_without_output(manifest, tmp_path):
    directory, receipt = prepare(tmp_path, manifest, output=None)
    result = inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint)
    assert not result["output_present"]
    assert result["source_ciphertext_sha256"] is None
    assert result["content_status"] == "not_inspected"


@pytest.mark.parametrize("field,value", [("run_id", str(uuid4())), ("manifest_fingerprint", "0" * 64)])
def test_retention_wrong_identity_is_generic_and_read_only(manifest, tmp_path, field, value):
    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    expected_run_id = receipt["run_id"] if field != "run_id" else value
    expected_manifest = manifest.fingerprint if field != "manifest_fingerprint" else value
    with pytest.raises(ValueError, match="Local output"):
        inspect_retention(directory, expected_run_id=expected_run_id, expected_manifest_fingerprint=expected_manifest)
    assert not (directory / "incomplete-output-disposal-request.json").exists()


def test_missing_or_duplicate_receipt_is_rejected_without_repair(manifest, tmp_path):
    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    path = directory / "retention-receipt.json"
    original = path.read_bytes()
    path.write_bytes(original.replace(b'"schema":', b'"schema":"duplicate", "schema":', 1))
    with pytest.raises(ValueError, match="Local output"):
        inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint)
    path.write_bytes(original)
    path.unlink()
    with pytest.raises(ValueError, match="Local output"):
        inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint)
    assert not path.exists()


def test_live_retention_writer_lock_blocks_inspection(manifest, tmp_path):
    directory = tmp_path / "retention"
    lease = create_retention_receipt(directory, str(uuid4()), manifest, retention_seconds=300, now_ms=lambda: 1000)
    try:
        with pytest.raises(ValueError, match="Local output"):
            inspect_retention(directory, expected_run_id=lease.run_id, expected_manifest_fingerprint=manifest.fingerprint)
    finally:
        lease.close()
    result = inspect_retention(directory, expected_run_id=lease.run_id, expected_manifest_fingerprint=manifest.fingerprint)
    assert result["content_status"] == "not_inspected"


def test_expired_incomplete_output_requires_explicit_consent_and_deletes_once(manifest, tmp_path):
    directory, receipt = prepare(tmp_path, manifest, now=1000, output=b"partial")
    source_hash = hashlib.sha256(b"partial").hexdigest()
    with pytest.raises(ValueError, match="Local output"):
        dispose_incomplete_output(
            directory,
            expected_run_id=receipt["run_id"],
            expected_manifest_fingerprint=manifest.fingerprint,
            source_ciphertext_sha256=source_hash,
            retention_receipt_sha256=hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest(),
            disposal_id=str(uuid4()),
            confirm_incomplete_output_disposal=False,
            now_ms=lambda: receipt["expires_at_ms"],
        )
    disposal_id = str(uuid4())
    result = dispose_incomplete_output(
        directory,
        expected_run_id=receipt["run_id"],
        expected_manifest_fingerprint=manifest.fingerprint,
        source_ciphertext_sha256=source_hash,
        retention_receipt_sha256=hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest(),
        disposal_id=disposal_id,
        confirm_incomplete_output_disposal=True,
        now_ms=lambda: receipt["expires_at_ms"],
    )
    assert result["disposal_id"] == disposal_id
    assert result["output_removed"] and not (directory / "observations.encrypted.jsonl").exists()
    assert result["secure_erasure_proven"] is False
    with pytest.raises(ValueError, match="Local output"):
        dispose_incomplete_output(
            directory,
            expected_run_id=receipt["run_id"],
            expected_manifest_fingerprint=manifest.fingerprint,
            source_ciphertext_sha256=source_hash,
            retention_receipt_sha256=result["retention_receipt_sha256"],
            disposal_id=str(uuid4()),
            confirm_incomplete_output_disposal=True,
            now_ms=lambda: receipt["expires_at_ms"],
        )
    reconciled = reconcile_incomplete_disposal(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint, disposal_id=disposal_id)
    assert reconciled["completion_receipt_present"] and reconciled["output_absent"]


@pytest.mark.parametrize("failure", ["before_unlink", "after_unlink_sync", "completion_write"])
def test_unknown_disposal_is_same_id_read_only_and_never_unlinks_again(manifest, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_retention as retention

    directory, receipt = prepare(tmp_path, manifest, now=1000, output=b"partial")
    source_hash = hashlib.sha256(b"partial").hexdigest()
    receipt_hash = hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest()
    disposal_id = str(uuid4())
    unlink_calls = []
    real_unlink = retention.os.unlink
    real_sync = retention._sync_directory
    real_write = retention._write_exclusive
    sync_calls = []

    def unlink(path):
        unlink_calls.append(Path(path).name)
        if failure == "before_unlink":
            raise OSError("synthetic unknown unlink")
        return real_unlink(path)

    def sync(path):
        sync_calls.append(Path(path).name)
        if failure == "after_unlink_sync" and unlink_calls:
            raise OSError("synthetic unknown directory sync")
        return real_sync(path)

    def write(path, data):
        if failure == "completion_write" and Path(path).name == "incomplete-output-disposal-complete.json":
            raise OSError("synthetic unknown completion")
        return real_write(path, data)

    monkeypatch.setattr(retention.os, "unlink", unlink)
    monkeypatch.setattr(retention, "_sync_directory", sync)
    monkeypatch.setattr(retention, "_write_exclusive", write)
    with pytest.raises(ValueError, match="Local output"):
        retention.dispose_incomplete_output(
            directory,
            expected_run_id=receipt["run_id"],
            expected_manifest_fingerprint=manifest.fingerprint,
            source_ciphertext_sha256=source_hash,
            retention_receipt_sha256=receipt_hash,
            disposal_id=disposal_id,
            confirm_incomplete_output_disposal=True,
            now_ms=lambda: receipt["expires_at_ms"],
        )
    assert unlink_calls == ["observations.encrypted.jsonl"]
    reconciled = retention.reconcile_incomplete_disposal(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint, disposal_id=disposal_id)
    assert reconciled["disposal_id"] == disposal_id
    assert not reconciled["resend_permitted"] and not reconciled["resume_permitted"]
    assert reconciled["output_absent"] is (failure != "before_unlink")
    with pytest.raises(ValueError, match="Local output"):
        retention.dispose_incomplete_output(
            directory,
            expected_run_id=receipt["run_id"],
            expected_manifest_fingerprint=manifest.fingerprint,
            source_ciphertext_sha256=source_hash,
            retention_receipt_sha256=receipt_hash,
            disposal_id=str(uuid4()),
            confirm_incomplete_output_disposal=True,
            now_ms=lambda: receipt["expires_at_ms"],
        )
    assert unlink_calls == ["observations.encrypted.jsonl"]


@pytest.mark.parametrize("operation", ["inspect", "reconcile"])
def test_read_only_operations_never_create_missing_lock(manifest, tmp_path, operation):
    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    (directory / "retention.lock").unlink()
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValueError, match="Local output"):
        if operation == "inspect":
            inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint)
        else:
            reconcile_incomplete_disposal(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint, disposal_id=str(uuid4()))
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.parametrize("field,value", [("expires_at_ms", True), ("input_count", True), ("request_count", 0), ("max_total_request_bytes", 0), ("scope", "approved")])
def test_invalid_receipt_is_rejected_without_mutation(manifest, tmp_path, field, value):
    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    receipt[field] = value
    path = directory / "retention-receipt.json"
    path.write_text(json.dumps(receipt))
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValueError, match="Local output"):
        inspect_retention(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def disposal_arguments(directory, receipt, manifest):
    return dict(
        expected_run_id=receipt["run_id"],
        expected_manifest_fingerprint=manifest.fingerprint,
        source_ciphertext_sha256=hashlib.sha256((directory / "observations.encrypted.jsonl").read_bytes()).hexdigest(),
        retention_receipt_sha256=hashlib.sha256((directory / "retention-receipt.json").read_bytes()).hexdigest(),
        disposal_id=str(uuid4()),
        confirm_incomplete_output_disposal=True,
        now_ms=lambda: receipt["expires_at_ms"],
    )


def test_active_output_descriptor_blocks_disposal(manifest, tmp_path):
    from devpilot.local_qa_output import _lock

    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    args = disposal_arguments(directory, receipt, manifest)
    with (directory / "observations.encrypted.jsonl").open("rb") as source:
        _lock(source.fileno(), exclusive=True)
        with pytest.raises(ValueError, match="Local output"):
            dispose_incomplete_output(directory, **args)
    assert not (directory / "incomplete-output-disposal-request.json").exists()
    assert (directory / "observations.encrypted.jsonl").read_bytes() == b"partial"


def test_disposal_keeps_original_output_locked_through_unlink(manifest, tmp_path, monkeypatch):
    import devpilot.local_qa_retention as retention
    from devpilot.local_qa_output import _lock

    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    args = disposal_arguments(directory, receipt, manifest)
    real_unlink = os.unlink
    checked = []

    def unlink(path):
        with Path(path).open("rb") as competing:
            with pytest.raises(OSError):
                _lock(competing.fileno(), exclusive=True)
        checked.append(True)
        return real_unlink(path)

    monkeypatch.setattr(retention.os, "unlink", unlink)
    dispose_incomplete_output(directory, **args)
    assert checked == [True]


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_nonregular_receipts_rejected_before_open(manifest, tmp_path, kind):
    if os.name != "posix":
        pytest.skip("POSIX link/FIFO fixture")
    directory, receipt = prepare(tmp_path, manifest)
    source = directory / "retention-receipt.json"
    original = tmp_path / "original-receipt"
    source.rename(original)
    if kind == "fifo":
        os.mkfifo(source)
    elif kind == "symlink":
        source.symlink_to(original)
    else:
        os.link(original, source)
    # A FIFO must be rejected without an indefinitely blocking open.
    import subprocess
    import sys

    script = "from devpilot.local_qa_retention import inspect_retention; import sys; inspect_retention(sys.argv[1], expected_run_id=sys.argv[2], expected_manifest_fingerprint=sys.argv[3])"
    result = subprocess.run([sys.executable, "-c", script, str(directory), receipt["run_id"], manifest.fingerprint], capture_output=True, timeout=5)
    assert result.returncode != 0 and b"Local output" in result.stderr


def test_invalid_identity_rejected_before_creating_directory(manifest, tmp_path):
    directory = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="Local output"):
        create_retention_receipt(directory, "invalid", manifest, retention_seconds=300)
    assert not directory.exists()


def test_new_directory_parent_is_synced_before_receipt_creation(manifest, tmp_path, monkeypatch):
    import devpilot.local_qa_retention as retention

    synced = []
    real_sync = retention._sync_directory

    def sync(path):
        synced.append(Path(path))
        return real_sync(path)

    monkeypatch.setattr(retention, "_sync_directory", sync)
    directory = tmp_path / "retention"
    with create_retention_receipt(directory, str(uuid4()), manifest, retention_seconds=300):
        assert synced == [tmp_path, directory, directory]


def test_uncertain_parent_sync_never_creates_output_or_repairs_directory(manifest, tmp_path, monkeypatch):
    import devpilot.local_qa_retention as retention

    calls = []

    def sync(path):
        calls.append(path)
        raise OSError("synthetic parent sync failure")

    monkeypatch.setattr(retention, "_sync_directory", sync)
    directory = tmp_path / "retention"
    with pytest.raises(ValueError, match="Local output"):
        create_retention_receipt(directory, str(uuid4()), manifest, retention_seconds=300)
    assert directory.is_dir() and not list(directory.iterdir())
    with pytest.raises(ValueError, match="Local output"):
        create_retention_receipt(directory, str(uuid4()), manifest, retention_seconds=300)
    assert calls == [tmp_path]


def test_allowlisted_distribution_can_read_actual_sources():
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("retention_distribution", root / "scripts/build_local_qa_distribution.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    sources = builder.source_members(root)
    assert sources["devpilot/local_qa_retention.py"] == (root / "devpilot/src/devpilot/local_qa_retention.py").read_bytes()


@pytest.mark.parametrize("field,value", [("output_removed", 1), ("secure_erasure_proven", 0), ("resend_permitted", 0)])
def test_reconciliation_rejects_coercible_completion_flags(manifest, tmp_path, field, value):
    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    args = disposal_arguments(directory, receipt, manifest)
    dispose_incomplete_output(directory, **args)
    path = directory / "incomplete-output-disposal-complete.json"
    completion = json.loads(path.read_bytes())
    completion[field] = value
    path.write_text(json.dumps(completion))
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValueError, match="Local output"):
        reconcile_incomplete_disposal(directory, expected_run_id=receipt["run_id"], expected_manifest_fingerprint=manifest.fingerprint, disposal_id=args["disposal_id"])
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.parametrize("failure", ["short_write", "fsync", "close", "directory_sync"])
def test_uncertain_intent_durability_never_reaches_unlink(manifest, tmp_path, monkeypatch, failure):
    import devpilot.local_qa_retention as retention

    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    args = disposal_arguments(directory, receipt, manifest)
    real_write = retention._write_exclusive
    real_close = os.close
    attempts = []
    unlink_calls = []

    def fail(*_args):
        raise OSError("synthetic durability failure")

    def close(descriptor):
        real_close(descriptor)
        raise OSError("synthetic lost close acknowledgement")

    def unlink(path):
        unlink_calls.append(path)
        raise OSError("unexpected unlink")

    def write(path, data):
        assert Path(path).name == "incomplete-output-disposal-request.json"
        attempts.append(Path(path).name)
        with monkeypatch.context() as patch:
            if failure == "short_write":
                real_os_write = os.write
                patch.setattr(retention.os, "write", lambda fd, payload: real_os_write(fd, payload[:1]))
            elif failure == "fsync":
                patch.setattr(retention.os, "fsync", fail)
            elif failure == "close":
                patch.setattr(retention.os, "close", close)
            else:
                patch.setattr(retention, "_sync_directory", fail)
            return real_write(path, data)

    monkeypatch.setattr(retention, "_write_exclusive", write)
    monkeypatch.setattr(retention.os, "unlink", unlink)
    with pytest.raises(ValueError, match="Local output"):
        dispose_incomplete_output(directory, **args)
    assert attempts == ["incomplete-output-disposal-request.json"]
    assert not unlink_calls
    assert (directory / "observations.encrypted.jsonl").read_bytes() == b"partial"
    assert not (directory / "incomplete-output-disposal-complete.json").exists()
    with pytest.raises(ValueError, match="Local output"):
        dispose_incomplete_output(directory, **{**args, "disposal_id": str(uuid4())})
    assert attempts == ["incomplete-output-disposal-request.json"]
    assert not unlink_calls


@pytest.mark.parametrize("change", ["output", "receipt", "clock"])
def test_post_intent_rechecks_reject_changes_without_delete(manifest, tmp_path, monkeypatch, change):
    import devpilot.local_qa_retention as retention

    directory, receipt = prepare(tmp_path, manifest, output=b"partial")
    args = disposal_arguments(directory, receipt, manifest)
    real_write = retention._write_exclusive
    times = iter([receipt["expires_at_ms"], receipt["created_at_ms"]])
    if change == "clock":
        args["now_ms"] = lambda: next(times)

    def write(path, data):
        real_write(path, data)
        if change == "output":
            (directory / "observations.encrypted.jsonl").write_bytes(b"changed")
        elif change == "receipt":
            receipt["expires_at_ms"] += 1000
            (directory / "retention-receipt.json").write_text(json.dumps(receipt))

    monkeypatch.setattr(retention, "_write_exclusive", write)
    with pytest.raises(ValueError, match="Local output"):
        dispose_incomplete_output(directory, **args)
    assert (directory / "incomplete-output-disposal-request.json").exists()
    assert (directory / "observations.encrypted.jsonl").exists()
    assert not (directory / "incomplete-output-disposal-complete.json").exists()
