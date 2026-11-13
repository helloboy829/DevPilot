"""Read-only governance for incomplete local QA output directories.

An incomplete output is never authenticated, resumed, repaired, or resent.  A
small durable receipt records the frozen identity before a collector can create
the sensitive output file.  Expired cleanup is an explicit, one-shot unlink
with a same-ID read-only reconciliation path when the unlink or its receipt is
uncertain.
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .local_qa_output import (
    _ERROR,
    _FILE,
    _clock,
    _decode,
    _directory,
    _encode,
    _hash,
    _lock,
    _sync_directory,
    _write_exclusive,
)

_RECEIPT = "retention-receipt.json"
_LOCK = "retention.lock"
_REQUEST = "incomplete-output-disposal-request.json"
_COMPLETE = "incomplete-output-disposal-complete.json"
_SCOPE = "external_unverified_technical_only"
_MAX_FILE = 67 * 1024 * 1024


def _uuid(value: object) -> bool:
    return type(value) is str and str(UUID(value)) == value


def _integer(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _open_lock(directory: Path, *, exclusive: bool) -> int:
    descriptor = os.open(
        directory / _LOCK,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError
        _lock(descriptor, exclusive=exclusive)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_manifest(manifest) -> dict:
    try:
        values = {
            "input_count": manifest.input_count,
            "request_count": manifest.request_count,
            "max_response_bytes": manifest.max_response_bytes,
            "max_total_response_bytes": manifest.max_total_response_bytes,
            "max_total_request_bytes": manifest.max_total_request_bytes,
            "duration_ms": manifest.duration_ms,
        }
        if not all(type(value) is int and value >= 1 for value in values.values()):
            raise ValueError
        if values["input_count"] > min(500, values["request_count"]):
            raise ValueError
        if values["max_total_response_bytes"] < values["max_response_bytes"] + 1:
            raise ValueError
        return values
    except (AttributeError, TypeError, ValueError):
        raise ValueError(_ERROR) from None


def _receipt_payload(run_id: str, manifest, *, created_at_ms: int, retention_seconds: int) -> dict:
    if not _uuid(run_id) or not _integer(retention_seconds, 300, 2_592_000):
        raise ValueError(_ERROR)
    values = _validate_manifest(manifest)
    if not _hash(manifest.fingerprint):
        raise ValueError(_ERROR)
    if retention_seconds * 1000 < values["duration_ms"]:
        raise ValueError(_ERROR)
    if not _integer(created_at_ms, 1, 2**53 - 1):
        raise ValueError(_ERROR)
    return {
        "schema": "local-qa-output-retention.v1",
        "scope": _SCOPE,
        "run_id": run_id,
        "manifest_fingerprint": manifest.fingerprint,
        "created_at_ms": created_at_ms,
        "expires_at_ms": created_at_ms + retention_seconds * 1000,
        "retention_seconds": retention_seconds,
        "input_count": values["input_count"],
        "request_count": values["request_count"],
        "max_response_bytes": values["max_response_bytes"],
        "max_total_response_bytes": values["max_total_response_bytes"],
        "max_total_request_bytes": values["max_total_request_bytes"],
        "output_file": _FILE,
        "verdict": "NOT_EVALUATED",
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }


def _read_json_bytes(path: Path, limit: int) -> tuple[dict, bytes]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
                raise ValueError
            if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise ValueError
            chunks = []
            total = 0
            while total <= limit:
                chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b"".join(chunks)
        finally:
            os.close(descriptor)
        if len(raw) != info.st_size or len(raw) > limit:
            raise ValueError
        value = _decode(raw)
        if type(value) is not dict:
            raise ValueError
        return value, raw
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None


def _read_json(path: Path, limit: int) -> dict:
    return _read_json_bytes(path, limit)[0]


def _validate_receipt(value: dict, *, run_id: str, manifest_fingerprint: str) -> dict:
    names = {
        "schema", "scope", "run_id", "manifest_fingerprint", "created_at_ms",
        "expires_at_ms", "retention_seconds", "input_count", "request_count",
        "max_response_bytes", "max_total_response_bytes", "max_total_request_bytes",
        "output_file", "verdict", "platform_provenance_verified",
        "resend_permitted", "resume_permitted",
    }
    if (
        set(value) != names
        or value["schema"] != "local-qa-output-retention.v1"
        or value["scope"] != _SCOPE
        or value["run_id"] != run_id
        or value["manifest_fingerprint"] != manifest_fingerprint
        or value["output_file"] != _FILE
        or value["verdict"] != "NOT_EVALUATED"
        or any(value[name] is not False for name in ("platform_provenance_verified", "resend_permitted", "resume_permitted"))
        or not _uuid(run_id)
        or not _hash(manifest_fingerprint)
        or not _integer(value["created_at_ms"], 1, 2**53 - 1)
        or not _integer(value["retention_seconds"], 300, 2_592_000)
        or value["expires_at_ms"] != value["created_at_ms"] + value["retention_seconds"] * 1000
        or not _integer(value["expires_at_ms"], 1, 2**53 - 1)
        or not _integer(value["request_count"], 1, 10_000)
        or not _integer(value["input_count"], 1, min(500, value["request_count"]))
        or not _integer(value["max_response_bytes"], 1, 1_048_576)
        or not _integer(value["max_total_request_bytes"], 1, 67_108_864)
        or not _integer(value["max_total_response_bytes"], value["max_response_bytes"] + 1, 67_108_864)
    ):
        raise ValueError(_ERROR)
    return value


def _output_hash(directory: Path) -> tuple[bool, str | None, tuple[int, int, int, int] | None]:
    path = directory / _FILE
    if not os.path.lexists(path):
        return False, None, None
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > _MAX_FILE:
            raise ValueError
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE:
                raise ValueError
            digest.update(chunk)
        return True, digest.hexdigest(), (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    except (OSError, ValueError):
        raise ValueError(_ERROR) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _identity(directory: Path, expected_run_id: str, expected_manifest_fingerprint: str) -> tuple[dict, str]:
    if not _uuid(expected_run_id) or not _hash(expected_manifest_fingerprint):
        raise ValueError(_ERROR)
    receipt, receipt_bytes = _read_json_bytes(directory / _RECEIPT, 16 * 1024)
    receipt = _validate_receipt(receipt, run_id=expected_run_id, manifest_fingerprint=expected_manifest_fingerprint)
    return receipt, hashlib.sha256(receipt_bytes).hexdigest()


@dataclass(slots=True)
class RetentionLease:
    run_id: str
    receipt_sha256: str
    _descriptor: int

    def close(self) -> None:
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            os.close(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def create_retention_receipt(directory, run_id: str, manifest, *, retention_seconds: int, now_ms=None) -> RetentionLease:
    try:
        path = Path(directory).absolute()
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        _directory(path)
        created = _clock(now_ms)
        receipt = _receipt_payload(run_id, manifest, created_at_ms=created, retention_seconds=retention_seconds)
        descriptor = _open_lock(path, exclusive=True)
        try:
            encoded = _encode(receipt) + b"\n"
            _write_exclusive(path / _RECEIPT, encoded)
            return RetentionLease(run_id, hashlib.sha256(encoded).hexdigest(), descriptor)
        except BaseException:
            os.close(descriptor)
            raise
    except (OSError, ValueError, TypeError, AttributeError):
        raise ValueError(_ERROR) from None


def inspect_retention(directory, *, expected_run_id: str, expected_manifest_fingerprint: str, now_ms=None) -> dict:
    try:
        path = _directory(directory)
        descriptor = _open_lock(path, exclusive=False)
        try:
            receipt, receipt_hash = _identity(path, expected_run_id, expected_manifest_fingerprint)
            present, source_hash, _ = _output_hash(path)
            return {
                "schema": "local-qa-output-retention-inspection.v1",
                "scope": _SCOPE,
                "run_id": receipt["run_id"],
                "manifest_fingerprint": receipt["manifest_fingerprint"],
                "retention_receipt_sha256": receipt_hash,
                "source_ciphertext_sha256": source_hash,
                "output_present": present,
                "content_status": "not_inspected",
                "output_integrity_verified": False,
                "final_record_verified": False,
                "platform_provenance_verified": False,
                "verdict": "NOT_EVALUATED",
                "resend_permitted": False,
                "resume_permitted": False,
                "expired": _clock(now_ms) >= receipt["expires_at_ms"],
            }
        finally:
            os.close(descriptor)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None


def _validate_disposal(value: dict, *, run_id: str, manifest_fingerprint: str, disposal_id: str) -> dict:
    names = {
        "schema", "scope", "run_id", "manifest_fingerprint", "disposal_id",
        "retention_receipt_sha256", "source_ciphertext_sha256", "output_file",
        "verdict", "platform_provenance_verified", "resend_permitted", "resume_permitted",
        "secure_erasure_proven",
    }
    if (
        set(value) != names
        or value["schema"] != "local-qa-incomplete-output-disposal.v1"
        or value["scope"] != _SCOPE
        or value["run_id"] != run_id
        or value["manifest_fingerprint"] != manifest_fingerprint
        or value["disposal_id"] != disposal_id
        or value["output_file"] != _FILE
        or value["verdict"] != "NOT_EVALUATED"
        or not _hash(value["retention_receipt_sha256"])
        or not _hash(value["source_ciphertext_sha256"])
        or any(value[name] is not False for name in ("platform_provenance_verified", "resend_permitted", "resume_permitted", "secure_erasure_proven"))
    ):
        raise ValueError(_ERROR)
    return value


def dispose_incomplete_output(directory, *, expected_run_id: str, expected_manifest_fingerprint: str, source_ciphertext_sha256: str, retention_receipt_sha256: str, disposal_id: str, confirm_incomplete_output_disposal: bool, now_ms=None) -> dict:
    if confirm_incomplete_output_disposal is not True or not _uuid(disposal_id) or not _hash(source_ciphertext_sha256) or not _hash(retention_receipt_sha256):
        raise ValueError(_ERROR)
    try:
        path = _directory(directory)
        descriptor = _open_lock(path, exclusive=True)
        try:
            if os.path.lexists(path / _REQUEST) or os.path.lexists(path / _COMPLETE):
                raise ValueError
            receipt, receipt_hash = _identity(path, expected_run_id, expected_manifest_fingerprint)
            if receipt_hash != retention_receipt_sha256 or _clock(now_ms) < receipt["expires_at_ms"]:
                raise ValueError
            present, output_hash, original = _output_hash(path)
            if not present or output_hash != source_ciphertext_sha256:
                raise ValueError
            intent = {
                "schema": "local-qa-incomplete-output-disposal.v1",
                "scope": _SCOPE,
                "run_id": expected_run_id,
                "manifest_fingerprint": expected_manifest_fingerprint,
                "disposal_id": disposal_id,
                "retention_receipt_sha256": receipt_hash,
                "source_ciphertext_sha256": output_hash,
                "output_file": _FILE,
                "verdict": "NOT_EVALUATED",
                "platform_provenance_verified": False,
                "resend_permitted": False,
                "resume_permitted": False,
                "secure_erasure_proven": False,
            }
            _write_exclusive(path / _REQUEST, _encode(intent) + b"\n")
            present_after, output_hash_after, current = _output_hash(path)
            if not present_after or output_hash_after != output_hash or current != original:
                raise ValueError
            os.unlink(path / _FILE)
            _sync_directory(path)
            result = {**intent, "output_removed": True, "secure_erasure_proven": False}
            _write_exclusive(path / _COMPLETE, _encode(result) + b"\n")
            return result
        finally:
            os.close(descriptor)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None


def reconcile_incomplete_disposal(directory, *, expected_run_id: str, expected_manifest_fingerprint: str, disposal_id: str) -> dict:
    if not _uuid(disposal_id):
        raise ValueError(_ERROR)
    try:
        path = _directory(directory)
        descriptor = _open_lock(path, exclusive=False)
        try:
            request = _validate_disposal(_read_json(path / _REQUEST, 16 * 1024), run_id=expected_run_id, manifest_fingerprint=expected_manifest_fingerprint, disposal_id=disposal_id)
            completion_present = False
            if os.path.lexists(path / _COMPLETE):
                completion = _read_json(path / _COMPLETE, 16 * 1024)
                if completion != {**request, "output_removed": True, "secure_erasure_proven": False}:
                    raise ValueError(_ERROR)
                completion_present = True
            return {
                **request,
                "completion_receipt_present": completion_present,
                "output_absent": not os.path.lexists(path / _FILE),
                "read_only_reconciliation": True,
            }
        finally:
            os.close(descriptor)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None
