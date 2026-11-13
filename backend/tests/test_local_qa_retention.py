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


@pytest.mark.parametrize("output", [b"", b'{\"schema\":', b"garbled-token", b"not-a-valid-chain\\n"])
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
        if failure == "before_unlink":
            raise OSError("synthetic unknown unlink")
        result = real_unlink(path)
        unlink_calls.append(Path(path).name)
        return result

    def sync(path):
        sync_calls.append(Path(path).name)
        if failure == "after_unlink_sync" and "observations.encrypted.jsonl" not in sync_calls:
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
    assert unlink_calls == ([] if failure == "before_unlink" else ["observations.encrypted.jsonl"])
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
    assert unlink_calls == ([] if failure == "before_unlink" else ["observations.encrypted.jsonl"])
