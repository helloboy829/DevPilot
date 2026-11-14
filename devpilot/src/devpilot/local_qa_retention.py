"""Read-only governance for incomplete local QA output directories.

An incomplete output is never authenticated, resumed, repaired, or resent.  A
small durable receipt records the frozen identity before a collector can create
the sensitive output file.  Expired cleanup is an explicit, one-shot unlink
with a same-ID read-only reconciliation path when the unlink or its receipt is
uncertain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from contextlib import contextmanager
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
    _maximum,
    _sync_directory,
)

_RECEIPT = "retention-receipt.json"
_LOCK = "retention.lock"
_REQUEST = "incomplete-output-disposal-request.json"
_COMPLETE = "incomplete-output-disposal-complete.json"
_SCOPE = "external_unverified_technical_only"
_FROZEN = (
    "input_count",
    "request_count",
    "concurrency",
    "timeout_ms",
    "duration_ms",
    "max_response_bytes",
    "max_total_request_bytes",
    "max_total_response_bytes",
)


def _uuid(value: object) -> bool:
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


def _integer(value: object, lower: int, upper: int) -> bool:
    return type(value) is int and lower <= value <= upper


def _identity_tuple(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _regular(info, limit, *, empty=False):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not (0 if empty else 1) <= info.st_size <= limit:
        raise ValueError(_ERROR)
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError(_ERROR)


def _stable(path, descriptor, original):
    if _identity_tuple(os.fstat(descriptor)) != _identity_tuple(original) or _identity_tuple(os.lstat(path)) != _identity_tuple(original):
        raise ValueError(_ERROR)


def _open_regular(path, limit, *, empty=False, writable=False):
    original = os.lstat(path)
    _regular(original, limit, empty=empty)
    flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        _regular(info, limit, empty=empty)
        _stable(path, descriptor, original)
        return descriptor, info
    except BaseException:
        os.close(descriptor)
        raise


def _open_lock(directory: Path, *, exclusive: bool) -> int:
    # Read-only operations must never recreate a missing/corrupt lease marker.
    descriptor, _ = _open_regular(directory / _LOCK, 1, empty=True, writable=os.name == "nt")
    try:
        _lock(descriptor, exclusive=exclusive)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_exclusive(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.write(descriptor, data) != len(data):
            raise OSError(_ERROR)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync_directory(Path(path).parent)


def _validate_manifest(manifest) -> dict:
    try:
        from .local_qa_cli import LocalRunManifest

        if type(manifest) is not LocalRunManifest:
            raise ValueError
        LocalRunManifest.from_dict(manifest.to_dict())
        values = {name: getattr(manifest, name) for name in _FROZEN}
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
    if not _integer(created_at_ms, 1, 2**53 - 1 - retention_seconds * 1000):
        raise ValueError(_ERROR)
    return {
        "schema": "local-qa-output-retention.v1",
        "scope": _SCOPE,
        "run_id": run_id,
        "manifest_fingerprint": manifest.fingerprint,
        "created_at_ms": created_at_ms,
        "expires_at_ms": created_at_ms + retention_seconds * 1000,
        "retention_seconds": retention_seconds,
        **values,
        "output_file": _FILE,
        "verdict": "NOT_EVALUATED",
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }


def _read_json_bytes(path: Path, limit: int) -> tuple[dict, bytes]:
    try:
        descriptor, info = _open_regular(path, limit)
        try:
            chunks = []
            total = 0
            while total <= limit:
                chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            raw = b"".join(chunks)
            _stable(path, descriptor, info)
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
        "schema",
        "scope",
        "run_id",
        "manifest_fingerprint",
        "created_at_ms",
        "expires_at_ms",
        "retention_seconds",
        *_FROZEN,
        "output_file",
        "verdict",
        "platform_provenance_verified",
        "resend_permitted",
        "resume_permitted",
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
        or not _integer(value["concurrency"], 1, 64)
        or not _integer(value["timeout_ms"], 100, 300_000)
        or not _integer(value["duration_ms"], 1000, min(3_600_000, value["retention_seconds"] * 1000))
        or not _integer(value["input_count"], 1, min(500, value["request_count"]))
        or not _integer(value["max_response_bytes"], 1, 1_048_576)
        or not _integer(value["max_total_request_bytes"], 1, 67_108_864)
        or not _integer(value["max_total_response_bytes"], value["max_response_bytes"] + 1, 67_108_864)
    ):
        raise ValueError(_ERROR)
    return value


@contextmanager
def _output_descriptor(directory, limit, *, exclusive=False):
    path = directory / _FILE
    if not os.path.lexists(path):
        yield None, None
        return
    descriptor = None
    try:
        descriptor, info = _open_regular(path, limit, empty=True, writable=exclusive and os.name == "nt")
        _lock(descriptor, exclusive=exclusive)
        _stable(path, descriptor, info)
        yield descriptor, info
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _output_hash(directory, descriptor, info, limit):
    if descriptor is None:
        return None
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, limit + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ValueError(_ERROR)
        digest.update(chunk)
    _stable(directory / _FILE, descriptor, info)
    if total != info.st_size:
        raise ValueError(_ERROR)
    return digest.hexdigest()


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
        created = _clock(now_ms)
        receipt = _receipt_payload(run_id, manifest, created_at_ms=created, retention_seconds=retention_seconds)
        path = Path(directory).absolute()
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        _directory(path)
        _sync_directory(path.parent)
        _write_exclusive(path / _LOCK, b"0")
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
            limit = _maximum(receipt)
            with _output_descriptor(path, limit) as (source, info):
                source_hash = _output_hash(path, source, info, limit)
            return {
                "schema": "local-qa-output-retention-inspection.v1",
                "scope": _SCOPE,
                "run_id": receipt["run_id"],
                "manifest_fingerprint": receipt["manifest_fingerprint"],
                **{name: receipt[name] for name in _FROZEN},
                "created_at_ms": receipt["created_at_ms"],
                "expires_at_ms": receipt["expires_at_ms"],
                "retention_seconds": receipt["retention_seconds"],
                "retention_receipt_sha256": receipt_hash,
                "source_ciphertext_sha256": source_hash,
                "output_present": source is not None,
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
        "schema",
        "scope",
        "run_id",
        "manifest_fingerprint",
        "disposal_id",
        "retention_receipt_sha256",
        "source_ciphertext_sha256",
        "output_file",
        "verdict",
        "platform_provenance_verified",
        "resend_permitted",
        "resume_permitted",
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


def dispose_incomplete_output(
    directory,
    *,
    expected_run_id: str,
    expected_manifest_fingerprint: str,
    source_ciphertext_sha256: str,
    retention_receipt_sha256: str,
    disposal_id: str,
    confirm_incomplete_output_disposal: bool,
    now_ms=None,
) -> dict:
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
            limit = _maximum(receipt)
            # Retain the SAME output descriptor and exclusive lock through both
            # hash passes, intent durability, exact unlink and completion.
            with _output_descriptor(path, limit, exclusive=True) as (source, original):
                output_hash = _output_hash(path, source, original, limit)
                if source is None or output_hash != source_ciphertext_sha256:
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
                if _output_hash(path, source, original, limit) != output_hash:
                    raise ValueError
                _, current_hash = _identity(path, expected_run_id, expected_manifest_fingerprint)
                if current_hash != receipt_hash or _clock(now_ms) < receipt["expires_at_ms"]:
                    raise ValueError
                _stable(path / _FILE, source, original)
                os.unlink(path / _FILE)
                _sync_directory(path)
                result = {**intent, "output_removed": True}
                _write_exclusive(path / _COMPLETE, _encode(result) + b"\n")
                return result
        finally:
            os.close(descriptor)
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None


def reconcile_incomplete_disposal(directory, *, expected_run_id: str, expected_manifest_fingerprint: str, disposal_id: str) -> dict:
    if not _uuid(disposal_id) or not _uuid(expected_run_id) or not _hash(expected_manifest_fingerprint):
        raise ValueError(_ERROR)
    try:
        path = _directory(directory)
        descriptor = _open_lock(path, exclusive=False)
        try:
            _, receipt_hash = _identity(path, expected_run_id, expected_manifest_fingerprint)
            request = _validate_disposal(_read_json(path / _REQUEST, 16 * 1024), run_id=expected_run_id, manifest_fingerprint=expected_manifest_fingerprint, disposal_id=disposal_id)
            if request["retention_receipt_sha256"] != receipt_hash:
                raise ValueError
            completion_present = False
            if os.path.lexists(path / _COMPLETE):
                completion = _read_json(path / _COMPLETE, 16 * 1024)
                completion_body = {name: value for name, value in completion.items() if name != "output_removed"}
                _validate_disposal(completion_body, run_id=expected_run_id, manifest_fingerprint=expected_manifest_fingerprint, disposal_id=disposal_id)
                if completion.get("output_removed") is not True or completion_body != request:
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


def main(argv=None):
    """Explicit original-ID operations; never discover, execute, decrypt or retry."""

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(_ERROR)

    parser = Parser(
        description="Explicit local retention inspection/disposal/reconciliation. Content remains unverified / NOT_EVALUATED; expiry is not secure erasure.",
        allow_abbrev=False,
    )
    operations = parser.add_subparsers(dest="operation", required=True)
    for operation in ("inspect", "dispose-expired", "reconcile-disposal"):
        command = operations.add_parser(operation, allow_abbrev=False)
        command.add_argument("--directory", required=True)
        command.add_argument("--run-id", required=True)
        command.add_argument("--manifest-fingerprint", required=True)
        if operation != "inspect":
            command.add_argument("--disposal-id", required=True)
        if operation == "dispose-expired":
            command.add_argument("--confirm-retention-receipt-sha256", required=True)
            command.add_argument("--confirm-ciphertext-sha256", required=True)
            command.add_argument("--confirm-incomplete-output-disposal", action="store_true", required=True)
    try:
        args = parser.parse_args(argv)
        common = {"expected_run_id": args.run_id, "expected_manifest_fingerprint": args.manifest_fingerprint}
        if args.operation == "inspect":
            result = inspect_retention(args.directory, **common)
        elif args.operation == "reconcile-disposal":
            result = reconcile_incomplete_disposal(args.directory, **common, disposal_id=args.disposal_id)
        else:
            result = dispose_incomplete_output(
                args.directory,
                **common,
                disposal_id=args.disposal_id,
                source_ciphertext_sha256=args.confirm_ciphertext_sha256,
                retention_receipt_sha256=args.confirm_retention_receipt_sha256,
                confirm_incomplete_output_disposal=args.confirm_incomplete_output_disposal,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        print(_ERROR, file=sys.stderr)
        return 130
    except Exception:
        print(_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
