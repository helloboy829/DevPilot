"""Bounded encrypted storage for raw QA response bodies."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable

_ARTIFACT_ID = re.compile(r"^[0-9a-f]{32}$")
_BINDING_FIELDS = {"artifact_id", "owner_id", "project_id", "run_id", "ordinal", "sample_id", "plan_hash"}
_MAGIC = b"devpilot-qa-response-artifact.v1\0"
_CAPTURE_STATUSES = {"complete", "partial", "truncated"}


def _checked_binding(artifact_id: str, binding: dict) -> dict:
    if (
        type(artifact_id) is not str
        or not _ARTIFACT_ID.fullmatch(artifact_id)
        or type(binding) is not dict
        or set(binding) != _BINDING_FIELDS - {"artifact_id"}
        or any(type(binding[name]) is not str or not 1 <= len(binding[name]) <= 80 for name in _BINDING_FIELDS - {"ordinal", "artifact_id"})
        or type(binding["ordinal"]) is not int
        or not 1 <= binding["ordinal"] <= 10_000
    ):
        raise RequestProtectionError("Invalid response artifact context")
    return {"artifact_id": artifact_id, **binding}


class ResponseArtifactStore:
    """Encrypt immutable response bytes and publish each generated ID once."""

    def __init__(self, root: Path | str, key: bytes, *, key_version: str | None = None):
        try:
            raw_key = base64.urlsafe_b64decode(key)
            if len(raw_key) != 32:
                raise ValueError
            self._cipher = AESGCM(raw_key)
        except (ValueError, TypeError):
            raise RequestProtectionUnavailable("Evidence protection key is missing or invalid; contact the operator") from None
        self.root = Path(root).expanduser().absolute()
        self.key_version = key_version or hashlib.sha256(raw_key).hexdigest()[:16]
        if type(self.key_version) is not str or not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", self.key_version):
            raise RequestProtectionUnavailable("Evidence protection key version is invalid; contact the operator")

    @classmethod
    def from_environment(cls, root: Path | str | None = None):
        root = root or os.environ.get("DEVPILOT_QA_ARTIFACT_DIR")
        if not root:
            raise RequestProtectionUnavailable("QA evidence storage is not configured; contact the operator")
        try:
            key = os.environ["DEVPILOT_REQUEST_ENCRYPTION_KEY"].encode("ascii")
        except (KeyError, UnicodeError):
            raise RequestProtectionUnavailable("Evidence protection key is missing or invalid; contact the operator") from None
        return cls(root, key)

    def _path(self, artifact_id: str) -> Path:
        if type(artifact_id) is not str or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise RequestProtectionError("Invalid response artifact identifier")
        if self.root.is_symlink():
            raise RequestProtectionError("Response artifact storage path is invalid")
        parent = self.root / artifact_id[:2]
        if parent.is_symlink():
            raise RequestProtectionError("Response artifact storage path is invalid")
        return parent / f"{artifact_id}.bin"

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name != "posix":
            raise RequestProtectionUnavailable("Durable response artifact storage is unavailable on this platform")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @classmethod
    def _ensure_directory(cls, path: Path) -> None:
        missing = []
        current = path
        while not current.exists():
            missing.append(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        for directory in reversed(missing):
            try:
                directory.mkdir()
            except FileExistsError:
                if not directory.is_dir():
                    raise
            else:
                cls._fsync_directory(directory.parent)
        cls._fsync_directory(path.parent)

    @staticmethod
    def _associated_data(artifact_id: str, binding: dict) -> bytes:
        checked = _checked_binding(artifact_id, binding)
        return _MAGIC + json.dumps(checked, sort_keys=True, separators=(",", ":")).encode("ascii")

    @staticmethod
    def _record(body: bytes, metadata: dict) -> tuple[dict, bytes]:
        fields = {"capture_status", "hash_scope", "body_sha256", "observed_bytes", "http_status", "content_type", "content_encoding"}
        if type(body) is not bytes or len(body) > 1_048_576 or type(metadata) is not dict or set(metadata) != fields:
            raise RequestProtectionError("Invalid response artifact")
        status, scope = metadata["capture_status"], metadata["hash_scope"]
        expected_hash = hashlib.sha256(body).hexdigest()
        if (
            type(status) is not str
            or status not in _CAPTURE_STATUSES
            or type(scope) is not str
            or scope != ("full" if status == "complete" else "prefix")
            or type(metadata["body_sha256"]) is not str
            or metadata["body_sha256"] != expected_hash
            or type(metadata["observed_bytes"]) is not int
            or not len(body) <= metadata["observed_bytes"] <= 1_048_577
            or type(metadata["http_status"]) is not int
            or not 100 <= metadata["http_status"] <= 599
            or (status == "complete" and metadata["observed_bytes"] != len(body))
            or (status == "truncated" and metadata["observed_bytes"] <= len(body))
            or any(metadata[name] is not None and (type(metadata[name]) is not str or len(metadata[name]) > 160) for name in ("content_type", "content_encoding"))
        ):
            raise RequestProtectionError("Invalid response artifact")
        header = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("ascii")
        return metadata, _MAGIC + len(header).to_bytes(4, "big") + header + body

    def _decode(self, artifact_id: str, sealed: bytes, binding: dict) -> tuple[dict, bytes]:
        try:
            if type(sealed) is not bytes or len(sealed) < 28:
                raise ValueError
            aad = self._associated_data(artifact_id, binding)
            plaintext = self._cipher.decrypt(sealed[:12], sealed[12:], aad)
            if not plaintext.startswith(_MAGIC) or len(plaintext) < len(_MAGIC) + 4:
                raise ValueError
            offset = len(_MAGIC)
            header_size = int.from_bytes(plaintext[offset : offset + 4], "big")
            start = offset + 4
            end = start + header_size
            if not 1 <= header_size <= 2048 or end > len(plaintext):
                raise ValueError
            metadata = json.loads(plaintext[start:end].decode("ascii"))
            body = plaintext[end:]
            checked, _ = self._record(body, metadata)
            return checked, body
        except (InvalidTag, ValueError, TypeError, KeyError):
            raise RequestProtectionError("Response artifact cannot be opened or failed integrity checks") from None

    def _publish(self, artifact_id: str, body: bytes, binding: dict, metadata: dict) -> dict:
        checked_metadata, plaintext = self._record(body, metadata)
        path = self._path(artifact_id)
        aad = self._associated_data(artifact_id, binding)
        nonce = os.urandom(12)
        sealed = nonce + self._cipher.encrypt(nonce, plaintext, aad)
        self._ensure_directory(self.root)
        self._ensure_directory(path.parent)
        if path.is_symlink() or path.parent.is_symlink():
            raise RequestProtectionError("Response artifact storage path is invalid")
        if path.exists():
            existing = path.read_bytes()
            existing_metadata, existing_body = self._decode(artifact_id, existing, binding)
            if existing_body != body or existing_metadata != checked_metadata:
                raise RequestProtectionError("Response artifact identifier is already occupied")
            self._fsync_directory(path.parent)
            return self._receipt(artifact_id, existing_metadata, existing_body, existing)

        fd, temporary = tempfile.mkstemp(prefix=f".{artifact_id}.", suffix=".tmp", dir=path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(sealed)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink():
                    raise RequestProtectionError("Response artifact storage path is invalid")
                existing = path.read_bytes()
                existing_metadata, existing_body = self._decode(artifact_id, existing, binding)
                if existing_body != body or existing_metadata != checked_metadata:
                    raise RequestProtectionError("Response artifact identifier is already occupied")
                sealed = existing
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        self._fsync_directory(path.parent)
        return self._receipt(artifact_id, checked_metadata, body, sealed)

    def _receipt(self, artifact_id: str, metadata: dict, body: bytes, sealed: bytes) -> dict:
        return {
            "artifact_id": artifact_id,
            "key_version": self.key_version,
            "capture_status": metadata["capture_status"],
            "hash_scope": metadata["hash_scope"],
            "body_sha256": metadata["body_sha256"],
            "body_bytes": len(body),
            "observed_bytes": metadata["observed_bytes"],
            "http_status": metadata["http_status"],
            "sealed_sha256": hashlib.sha256(sealed).hexdigest(),
            "sealed_bytes": len(sealed),
            "content_type": metadata["content_type"],
            "content_encoding": metadata["content_encoding"],
        }

    def publish(self, artifact_id: str, body: bytes, binding: dict, metadata: dict) -> dict:
        """Atomically publish ciphertext under a generated immutable identifier."""
        return self._publish(artifact_id, body, binding, metadata)

    def open(self, artifact_id: str, binding: dict) -> tuple[dict, bytes]:
        path = self._path(artifact_id)
        try:
            sealed = path.read_bytes()
        except OSError:
            raise RequestProtectionError("Response artifact is unavailable") from None
        return self._decode(artifact_id, sealed, binding)

    def open_range(self, artifact_id: str, binding: dict, range_header: str | None) -> tuple[dict, bytes, str | None]:
        metadata, body = self.open(artifact_id, binding)
        if range_header is None:
            return metadata, body, None
        if type(range_header) is not str or len(range_header) > 128:
            raise RequestProtectionError("Invalid response range")
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        if match is None or not body:
            raise RequestProtectionError("Invalid response range")
        first, last = match.groups()
        if not first and not last:
            raise RequestProtectionError("Invalid response range")
        if first:
            start = int(first)
            end = min(int(last), len(body) - 1) if last else len(body) - 1
            if start >= len(body) or end < start:
                raise RequestProtectionError("Invalid response range")
        else:
            suffix_length = int(last)
            if suffix_length <= 0:
                raise RequestProtectionError("Invalid response range")
            start = max(0, len(body) - suffix_length)
            end = len(body) - 1
        return metadata, body[start : end + 1], f"bytes {start}-{end}/{len(body)}"

    def inspect(self, artifact_id: str, binding: dict) -> dict | None:
        """Read-only receipt for reconciliation; never changes or recreates data."""
        path = self._path(artifact_id)
        try:
            sealed = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            raise RequestProtectionError("Response artifact is unavailable") from None
        metadata, body = self._decode(artifact_id, sealed, binding)
        return self._receipt(artifact_id, metadata, body, sealed)

    def ensure_available(self) -> None:
        """Fail before dispatch if the configured persistent root is not writable."""
        if self.root.is_symlink():
            raise RequestProtectionError("Response artifact storage path is invalid")
        self._ensure_directory(self.root)
        fd, temporary = tempfile.mkstemp(prefix=".qa-write-probe-", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(b"qa-artifact-storage-probe")
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        self._fsync_directory(self.root)
