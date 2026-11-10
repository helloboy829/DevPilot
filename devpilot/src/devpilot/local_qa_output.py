"""Authenticated, bounded local output with explicit keys and retention.

Not platform provenance, evidence admission or approval. Never generates keys,
uses environment credentials, repairs files or resumes execution. The operator
must trust parent directories, local account, clock and filesystem. Retention is
an enforced read gate plus explicit cleanup, not secure erasure or a daemon.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import stat
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

_ERROR = "Local output rejected or operation unconfirmed; retain the same IDs and files for read-only reconciliation"
_FILE = "observations.encrypted.jsonl"
_SCOPE = "external_unverified_technical_only"
_MAX_LINE = 8 * 1048576 + 65536
_KINDS = {"output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"}


def _integer(value, lower, upper):
    return type(value) is int and lower <= value <= upper


def _uuid(value):
    return type(value) is str and str(UUID(value)) == value


def _hash(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _encode(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")


def _unique(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(_ERROR)
        result[name] = value
    return result


def _decode(data):
    return json.loads(data.decode("ascii"), object_pairs_hook=_unique, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(_ERROR)))


def _directory(value):
    path = Path(value).absolute()
    if path.is_symlink() or not path.is_dir():
        raise ValueError(_ERROR)
    info = path.stat()
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError(_ERROR)
    return path


def _regular(descriptor, limit):
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= limit:
        raise ValueError(_ERROR)
    if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise ValueError(_ERROR)
    return info


def _open_read(path, limit):
    if Path(path).is_symlink():
        raise ValueError(_ERROR)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        info = _regular(descriptor, limit)
        return descriptor, info
    except BaseException:
        os.close(descriptor)
        raise


def _lock(descriptor, *, exclusive):
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    elif os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK if exclusive else msvcrt.LK_NBRLCK, 1)
    else:
        raise ValueError(_ERROR)


def _sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_exclusive(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.write(descriptor, value) != len(value):
            raise OSError(_ERROR)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _sync_directory(Path(path).parent)


def _clock(now_ms):
    value = now_ms() if now_ms is not None else time.time_ns() // 1000000
    if not _integer(value, 1, 2**53 - 1):
        raise ValueError(_ERROR)
    return value


class LocalOutputProtection:
    """Explicit operator key; repr never exposes key/path or derived key hash."""

    __slots__ = ("_cipher", "retention_seconds")

    def __init__(self, key, *, retention_seconds):
        try:
            if not _integer(retention_seconds, 300, 2592000) or type(key) is not bytes or len(key) != 44:
                raise ValueError
            if base64.urlsafe_b64encode(base64.b64decode(key, altchars=b"-_", validate=True)) != key:
                raise ValueError
            self._cipher = Fernet(key)
            self.retention_seconds = retention_seconds
        except (ValueError, TypeError):
            raise ValueError(_ERROR) from None

    @classmethod
    def from_key_file(cls, key_file, *, retention_seconds):
        try:
            descriptor, info = _open_read(key_file, 44)
            with os.fdopen(descriptor, "rb") as stream:
                key = stream.read(45)
            if info.st_size != 44 or len(key) != 44:
                raise ValueError
            return cls(key, retention_seconds=retention_seconds)
        except (OSError, ValueError, TypeError):
            raise ValueError(_ERROR) from None

    def __repr__(self):
        return "<LocalOutputProtection explicit-key>"


def _binding(value, run_id, manifest_hash):
    names = {"run_id", "manifest_fingerprint", "created_at_ms", "expires_at_ms", "retention_seconds", "input_count", "request_count", "max_response_bytes", "max_total_response_bytes", "max_total_request_bytes"}
    if type(value) is not dict or set(value) != names or value["run_id"] != run_id or value["manifest_fingerprint"] != manifest_hash or not _uuid(run_id) or not _hash(manifest_hash):
        raise ValueError(_ERROR)
    if (
        not _integer(value["retention_seconds"], 300, 2592000)
        or not _integer(value["created_at_ms"], 1, 2**53 - 1)
        or not _integer(value["expires_at_ms"], 1, 2**53 - 1)
        or value["expires_at_ms"] != value["created_at_ms"] + value["retention_seconds"] * 1000
    ):
        raise ValueError(_ERROR)
    if not _integer(value["request_count"], 1, 10000) or not _integer(value["input_count"], 1, min(value["request_count"], 500)) or not _integer(value["max_response_bytes"], 1, 1048576):
        raise ValueError(_ERROR)
    if not _integer(value["max_total_response_bytes"], value["max_response_bytes"] + 1, 67108864) or not _integer(value["max_total_request_bytes"], 1, 67108864):
        raise ValueError(_ERROR)
    return value


def _maximum(binding):
    return binding["max_total_response_bytes"] * 8 + binding["request_count"] * 2048 + 65536


def _attempt(record, binding, ordinals):
    names = {"ordinal", "sample_index", "kind", "http_status", "body_bytes", "elapsed_ms", "output"}
    if type(record) is not dict or set(record) != names or not _integer(record["ordinal"], 1, binding["request_count"]) or record["ordinal"] in ordinals:
        raise ValueError(_ERROR)
    if type(record["sample_index"]) is not int or record["sample_index"] != (record["ordinal"] - 1) % binding["input_count"] or type(record["kind"]) is not str or record["kind"] not in _KINDS:
        raise ValueError(_ERROR)
    if record["http_status"] is not None and not _integer(record["http_status"], 100, 599):
        raise ValueError(_ERROR)
    if not _integer(record["body_bytes"], 0, binding["max_response_bytes"] + 1) or type(record["elapsed_ms"]) not in (int, float) or not math.isfinite(record["elapsed_ms"]) or record["elapsed_ms"] < 0:
        raise ValueError(_ERROR)
    if record["kind"] == "output_collected":
        if type(record["output"]) is not str or len(record["output"].encode("utf-8", "surrogatepass")) > binding["max_response_bytes"] * 3:
            raise ValueError(_ERROR)
    elif record["output"] is not None:
        raise ValueError(_ERROR)
    ordinals.add(record["ordinal"])


def _final(record, binding, ordinals):
    if type(record) is not dict or set(record) != {"state", "reserved_request_bytes", "reserved_response_bytes"} or record["state"] not in {"collected", "interrupted"}:
        raise ValueError(_ERROR)
    if not _integer(record["reserved_request_bytes"], 0, binding["max_total_request_bytes"]) or not _integer(record["reserved_response_bytes"], 0, binding["max_total_response_bytes"]):
        raise ValueError(_ERROR)
    reservation = binding["max_response_bytes"] + 1
    if (
        record["reserved_response_bytes"] % reservation
        or not len(ordinals) <= record["reserved_response_bytes"] // reservation <= binding["request_count"]
        or (record["state"] == "collected" and (len(ordinals) != binding["request_count"] or record["reserved_response_bytes"] != binding["request_count"] * reservation))
    ):
        raise ValueError(_ERROR)


class EncryptedOutputStore:
    """Exclusive descriptor, authenticated sequence/chain, no write retry."""

    def __init__(self, directory, run_id, manifest, protection):
        if type(protection) is not LocalOutputProtection:
            raise ValueError(_ERROR)
        self.lock = threading.Lock()
        self.descriptor = None
        self.sequence = 0
        self.previous = "0" * 64
        self.size = 0
        self.ordinals = set()
        self.finished = False
        self.failed = False
        self.cipher = protection._cipher
        created = _clock(None)
        self.binding = {
            "run_id": run_id,
            "manifest_fingerprint": manifest.fingerprint,
            "created_at_ms": created,
            "expires_at_ms": created + protection.retention_seconds * 1000,
            "retention_seconds": protection.retention_seconds,
            **{name: getattr(manifest, name) for name in ("input_count", "request_count", "max_response_bytes", "max_total_response_bytes", "max_total_request_bytes")},
        }
        _binding(self.binding, run_id, manifest.fingerprint)
        path = Path(directory).absolute()
        path.mkdir(mode=0o700)
        _directory(path)
        self.descriptor = os.open(path / _FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            _lock(self.descriptor, exclusive=True)
            self._append("header", {})
            _sync_directory(path)
        except BaseException:
            self.close()
            raise

    def _append(self, kind, record):
        envelope = {"schema": "local-qa-protected-record.v1", "binding": self.binding, "sequence": self.sequence, "previous_ciphertext_sha256": self.previous, "kind": kind, "payload": record}
        token = self.cipher.encrypt(_encode(envelope))
        line = _encode({"schema": "local-qa-encrypted-output.v1", "binding": self.binding, "token": token.decode("ascii")}) + b"\n" if self.sequence == 0 else token + b"\n"
        if self.size + len(line) > _maximum(self.binding) or len(line) > _MAX_LINE or self.descriptor is None:
            raise ValueError(_ERROR)
        if os.write(self.descriptor, line) != len(line):
            raise OSError(_ERROR)
        os.fsync(self.descriptor)
        self.previous = hashlib.sha256(token).hexdigest()
        self.sequence += 1
        self.size += len(line)

    def append(self, record):
        with self.lock:
            if self.failed or self.finished or _clock(None) >= self.binding["expires_at_ms"]:
                raise ValueError(_ERROR)
            try:
                if "ordinal" in record:
                    _attempt(record, self.binding, self.ordinals)
                    self._append("attempt", record)
                else:
                    _final(record, self.binding, self.ordinals)
                    self._append("final", record)
                    self.finished = True
            except BaseException:
                self.failed = True
                raise

    def close(self):
        with self.lock:
            if self.descriptor is not None:
                descriptor, self.descriptor = self.descriptor, None
                os.close(descriptor)


@contextmanager
def _verified(directory, key_file, run_id, manifest_hash, *, now_ms=None, allow_expired=False, exclusive=False):
    descriptor = None
    try:
        directory = _directory(directory)
        protection = LocalOutputProtection.from_key_file(key_file, retention_seconds=300)
        descriptor, original = _open_read(directory / _FILE, 67108864 * 8 + 10000 * 2048 + 65536)
        _lock(descriptor, exclusive=exclusive)
        stream = os.fdopen(descriptor, "rb")
        descriptor = None
        with stream:
            header_line = stream.readline(16385)
            if len(header_line) > 16384 or not header_line.endswith(b"\n"):
                raise ValueError
            header = _decode(header_line)
            if type(header) is not dict or set(header) != {"schema", "binding", "token"} or header["schema"] != "local-qa-encrypted-output.v1" or type(header["token"]) is not str:
                raise ValueError
            binding = _binding(header["binding"], run_id, manifest_hash)
            if original.st_size > _maximum(binding):
                raise ValueError
            state = {"complete": False, "count": 0, "binding": binding, "file_info": original, "stream": stream}

            def records():
                # Both passes use the SAME locked descriptor. Never release the
                # verified source between authentication and plaintext creation.
                stream.seek(len(header_line))
                digest = hashlib.sha256(header_line)
                ordinals = set()
                state.update(complete=False, count=0)
                previous = "0" * 64
                sequence = 0
                token = header["token"].encode("ascii")
                while True:
                    current = _clock(now_ms)
                    if current < binding["created_at_ms"] or (not allow_expired and current >= binding["expires_at_ms"]):
                        raise ValueError(_ERROR)
                    if sequence > binding["request_count"] + 1:
                        raise ValueError(_ERROR)
                    raw = protection._cipher.decrypt(token)
                    if len(raw) > _MAX_LINE:
                        raise ValueError(_ERROR)
                    envelope = _decode(raw)
                    if (
                        type(envelope) is not dict
                        or set(envelope) != {"schema", "binding", "sequence", "previous_ciphertext_sha256", "kind", "payload"}
                        or envelope["schema"] != "local-qa-protected-record.v1"
                        or envelope["binding"] != binding
                        or type(envelope["sequence"]) is not int
                        or envelope["sequence"] != sequence
                        or envelope["previous_ciphertext_sha256"] != previous
                    ):
                        raise ValueError(_ERROR)
                    kind, payload = envelope["kind"], envelope["payload"]
                    if sequence == 0:
                        if kind != "header" or payload != {}:
                            raise ValueError(_ERROR)
                    elif kind == "attempt":
                        _attempt(payload, binding, ordinals)
                        state["count"] += 1
                        yield {"scope": _SCOPE, "verdict": "NOT_EVALUATED", "run_id": run_id, **payload}
                    elif kind == "final":
                        _final(payload, binding, ordinals)
                        if stream.read(1):
                            raise ValueError(_ERROR)
                        after = os.fstat(stream.fileno())
                        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns):
                            raise ValueError(_ERROR)
                        state.update(complete=True, ciphertext_sha256=digest.hexdigest(), final_state=payload["state"])
                        yield {"scope": _SCOPE, "verdict": "NOT_EVALUATED", "run_id": run_id, **payload}
                        return
                    else:
                        raise ValueError(_ERROR)
                    previous = hashlib.sha256(token).hexdigest()
                    sequence += 1
                    line = stream.readline(_MAX_LINE + 1)
                    if not line.endswith(b"\n") or len(line) > _MAX_LINE:
                        raise ValueError(_ERROR)
                    digest.update(line)
                    token = line[:-1]

            yield state, records
    except (ValueError, TypeError, OSError, KeyError, OverflowError, UnicodeError, RecursionError, InvalidToken):
        raise ValueError(_ERROR) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _metadata(state):
    binding = state["binding"]
    return {
        "schema": "local-qa-protected-output-inspection.v1",
        "scope": _SCOPE,
        "verdict": "NOT_EVALUATED",
        "run_id": binding["run_id"],
        "manifest_fingerprint": binding["manifest_fingerprint"],
        "created_at_ms": binding["created_at_ms"],
        "expires_at_ms": binding["expires_at_ms"],
        "ciphertext_sha256": state["ciphertext_sha256"],
        "recorded_attempt_count": state["count"],
        "frozen_input_count": binding["input_count"],
        "frozen_request_count": binding["request_count"],
        "final_state": state["final_state"],
        "output_integrity_verified": True,
        "final_record_verified": True,
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }


def inspect_output(directory, *, key_file, expected_run_id, expected_manifest_fingerprint, now_ms=None):
    with _verified(directory, key_file, expected_run_id, expected_manifest_fingerprint, now_ms=now_ms, allow_expired=True) as (state, records):
        for _ in records():
            pass
        return {**_metadata(state), "expired": _clock(now_ms) >= state["binding"]["expires_at_ms"]}


def open_output(directory, *, key_file, expected_run_id, expected_manifest_fingerprint, destination, confirm_sensitive_open, now_ms=None):
    if confirm_sensitive_open is not True:
        raise ValueError(_ERROR)
    try:
        # Authenticate the COMPLETE chain before creating any plaintext file.
        with _verified(directory, key_file, expected_run_id, expected_manifest_fingerprint, now_ms=now_ms) as (state, records):
            for _ in records():
                pass
            receipt = _metadata(state)
            destination = Path(destination).absolute()
            destination.mkdir(mode=0o700)
            _directory(destination)
            descriptor = os.open(destination / "observations.jsonl", os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                for record in records():
                    line = _encode(record) + b"\n"
                    if os.write(descriptor, line) != len(line):
                        raise OSError
                if state["ciphertext_sha256"] != receipt["ciphertext_sha256"] or _clock(now_ms) >= state["binding"]["expires_at_ms"]:
                    raise ValueError
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            _sync_directory(destination)
        return {**receipt, "sensitive_plaintext_created": True, "plaintext_retention_managed": False}
    except (ValueError, TypeError, OSError):
        raise ValueError(_ERROR) from None


def purge_output(directory, *, key_file, expected_run_id, expected_manifest_fingerprint, confirm_ciphertext_sha256, now_ms=None):
    try:
        directory = _directory(directory)
        # Keep a no-wait exclusive lock across verification, intent and unlink.
        with _verified(directory, key_file, expected_run_id, expected_manifest_fingerprint, now_ms=now_ms, allow_expired=True, exclusive=True) as (state, records):
            for _ in records():
                pass
            receipt = _metadata(state)
            if _clock(now_ms) < state["binding"]["expires_at_ms"] or not _hash(confirm_ciphertext_sha256) or confirm_ciphertext_sha256 != receipt["ciphertext_sha256"]:
                raise ValueError
            if Path(key_file).resolve().is_relative_to(directory.resolve()):
                raise ValueError
            intent = {
                "schema": "local-qa-output-purge.v1",
                "run_id": expected_run_id,
                "manifest_fingerprint": expected_manifest_fingerprint,
                "ciphertext_sha256": receipt["ciphertext_sha256"],
                "expires_at_ms": receipt["expires_at_ms"],
                "scope": _SCOPE,
                "verdict": "NOT_EVALUATED",
                "resend_permitted": False,
                "resume_permitted": False,
                "platform_provenance_verified": False,
                "secure_erasure_proven": False,
            }
            _write_exclusive(directory / "output-purge-request.json", _encode(intent) + b"\n")
            info = os.lstat(directory / _FILE)
            original = state["file_info"]
            if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns):
                raise ValueError
            # One exact unlink. Failure is unknown; never resend or remove other files.
            os.unlink(directory / _FILE)
            _sync_directory(directory)
            result = {**intent, "encrypted_file_removed": True}
            _write_exclusive(directory / "output-purge-complete.json", _encode(result) + b"\n")
            return result
    except (ValueError, TypeError, OSError):
        raise ValueError(_ERROR) from None


def reconcile_purge(directory, *, expected_run_id, expected_manifest_fingerprint):
    try:
        directory = _directory(directory)
        if not _uuid(expected_run_id) or not _hash(expected_manifest_fingerprint):
            raise ValueError
        descriptor, _ = _open_read(directory / "output-purge-request.json", 4096)
        with os.fdopen(descriptor, "rb") as stream:
            intent = _decode(stream.read(4097))
        names = {"schema", "run_id", "manifest_fingerprint", "ciphertext_sha256", "expires_at_ms", "scope", "verdict", "resend_permitted", "resume_permitted", "platform_provenance_verified", "secure_erasure_proven"}
        if (
            type(intent) is not dict
            or set(intent) != names
            or intent["schema"] != "local-qa-output-purge.v1"
            or intent["run_id"] != expected_run_id
            or intent["manifest_fingerprint"] != expected_manifest_fingerprint
            or not _hash(intent["ciphertext_sha256"])
            or not _integer(intent["expires_at_ms"], 1, 2**53 - 1)
            or intent["scope"] != _SCOPE
            or intent["verdict"] != "NOT_EVALUATED"
            or any(intent[n] is not False for n in ("resend_permitted", "resume_permitted", "platform_provenance_verified", "secure_erasure_proven"))
        ):
            raise ValueError
        complete_path = directory / "output-purge-complete.json"
        completed = False
        if os.path.lexists(complete_path):
            descriptor, _ = _open_read(complete_path, 4096)
            with os.fdopen(descriptor, "rb") as stream:
                completion = _decode(stream.read(4097))
            if completion != {**intent, "encrypted_file_removed": True}:
                raise ValueError
            completed = True
        return {**intent, "encrypted_file_absent": not os.path.lexists(directory / _FILE), "completion_receipt_present": completed, "read_only_reconciliation": True}
    except (ValueError, TypeError, OSError, UnicodeError, RecursionError):
        raise ValueError(_ERROR) from None


def main(argv=None):
    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(_ERROR)

    parser = Parser(description="Explicit local encrypted-output inspection/open/expired purge; never execution or evidence admission")
    parser.add_argument("operation", choices=("inspect", "open", "purge-expired", "reconcile-purge"))
    parser.add_argument("--directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--manifest-fingerprint", required=True)
    parser.add_argument("--key-file")
    parser.add_argument("--destination")
    parser.add_argument("--confirm-sensitive-open", action="store_true")
    parser.add_argument("--confirm-ciphertext-sha256")
    try:
        args = parser.parse_args(argv)
        common = {"expected_run_id": args.run_id, "expected_manifest_fingerprint": args.manifest_fingerprint}
        if args.operation == "reconcile-purge":
            if args.key_file or args.destination or args.confirm_sensitive_open or args.confirm_ciphertext_sha256:
                raise ValueError
            result = reconcile_purge(args.directory, **common)
        else:
            if not args.key_file:
                raise ValueError
            common["key_file"] = args.key_file
            if args.operation == "inspect":
                if args.destination or args.confirm_sensitive_open or args.confirm_ciphertext_sha256:
                    raise ValueError
                result = inspect_output(args.directory, **common)
            elif args.operation == "open":
                if not args.destination or args.confirm_ciphertext_sha256:
                    raise ValueError
                result = open_output(args.directory, destination=args.destination, confirm_sensitive_open=args.confirm_sensitive_open, **common)
            else:
                if args.destination or args.confirm_sensitive_open or not args.confirm_ciphertext_sha256:
                    raise ValueError
                result = purge_output(args.directory, confirm_ciphertext_sha256=args.confirm_ciphertext_sha256, **common)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(_ERROR, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
