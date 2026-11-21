"""Private, immutable storage for uploaded evaluation source materials."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

_ARTIFACT_ID = re.compile(r"^mat_[0-9a-f]{32}$")
_MAX_CONFIGURED_SIZE = 100 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


class MaterialArtifactStorageError(Exception):
    """A non-content-bearing artifact storage failure."""


class MaterialArtifactConflict(Exception):
    """An artifact ID is already bound to different bytes."""


class MaterialArtifactTooLarge(ValueError):
    """The upload exceeds the configured byte limit."""


class MaterialArtifactStore:
    def __init__(self, root: Path | str, *, max_file_size_bytes: int = _MAX_CONFIGURED_SIZE):
        if type(max_file_size_bytes) is not int or not 1 <= max_file_size_bytes <= _MAX_CONFIGURED_SIZE:
            raise ValueError("Invalid material artifact size limit")
        self.root = Path(root).expanduser().absolute()
        self.max_file_size_bytes = max_file_size_bytes

    @classmethod
    def from_environment(cls) -> MaterialArtifactStore | None:
        raw_root = os.environ.get("DEVPILOT_MATERIAL_ARTIFACT_DIR")
        if not raw_root:
            return None
        raw_limit = os.environ.get("DEVPILOT_MATERIAL_MAX_FILE_SIZE_BYTES", str(_MAX_CONFIGURED_SIZE))
        try:
            limit = int(raw_limit)
        except ValueError:
            raise ValueError("Invalid material artifact size configuration") from None
        return cls(raw_root, max_file_size_bytes=limit)

    def _path(self, artifact_id: str) -> Path:
        if type(artifact_id) is not str or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise ValueError("Invalid material artifact identifier")
        return self.root / artifact_id[4:6] / f"{artifact_id}.bin"

    @staticmethod
    def _reject_symlink(path: Path) -> None:
        try:
            if path.is_symlink():
                raise MaterialArtifactStorageError("Material artifact storage path is invalid")
        except OSError:
            raise MaterialArtifactStorageError("Material artifact storage is unavailable") from None

    def _ensure_parent(self, parent: Path) -> None:
        current = parent
        missing = []
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for path in reversed(missing):
            self._reject_symlink(path.parent)
            try:
                path.mkdir()
            except FileExistsError:
                if not path.is_dir():
                    raise MaterialArtifactStorageError("Material artifact storage is unavailable") from None
            except OSError:
                raise MaterialArtifactStorageError("Material artifact storage is unavailable") from None
        check = parent
        while check != check.parent:
            self._reject_symlink(check)
            if check == self.root:
                break
            check = check.parent
        if not parent.is_dir():
            raise MaterialArtifactStorageError("Material artifact storage is unavailable")

    def _existing(self, path: Path) -> tuple[int, str]:
        check = path
        while True:
            self._reject_symlink(check)
            if check == self.root:
                break
            if check == check.parent:
                raise MaterialArtifactStorageError("Material artifact storage path is invalid")
            check = check.parent
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK_SIZE):
                    size += len(chunk)
                    digest.update(chunk)
        except OSError:
            raise MaterialArtifactStorageError("Material artifact is unavailable") from None
        return size, digest.hexdigest()

    def write(self, artifact_id: str, source: BinaryIO) -> dict[str, int | str]:
        path = self._path(artifact_id)
        self._ensure_parent(path.parent)
        if path.exists():
            size, digest = self._existing(path)
            incoming_size, incoming_digest = self._digest_source(source)
            if (size, digest) != (incoming_size, incoming_digest):
                raise MaterialArtifactConflict
            return {"size_bytes": size, "sha256": digest}

        fd = -1
        temporary = None
        size = 0
        digest = hashlib.sha256()
        try:
            fd, temporary = tempfile.mkstemp(prefix=f".{artifact_id}.", suffix=".tmp", dir=path.parent)
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output:
                fd = -1
                while chunk := source.read(_CHUNK_SIZE):
                    if not isinstance(chunk, bytes):
                        raise ValueError("Material upload must contain bytes")
                    size += len(chunk)
                    if size > self.max_file_size_bytes:
                        raise MaterialArtifactTooLarge("Material upload is too large")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            self._reject_symlink(path)
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing_size, existing_digest = self._existing(path)
                if (existing_size, existing_digest) != (size, digest.hexdigest()):
                    raise MaterialArtifactConflict
        except (MaterialArtifactConflict, ValueError):
            raise
        except OSError:
            raise MaterialArtifactStorageError("Material artifact could not be stored") from None
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                except OSError:
                    raise MaterialArtifactStorageError("Material upload staging cleanup failed") from None
        return {"size_bytes": size, "sha256": digest.hexdigest()}

    def _digest_source(self, source: BinaryIO) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(_CHUNK_SIZE):
            if not isinstance(chunk, bytes):
                raise ValueError("Material upload must contain bytes")
            size += len(chunk)
            if size > self.max_file_size_bytes:
                raise MaterialArtifactTooLarge("Material upload is too large")
            digest.update(chunk)
        return size, digest.hexdigest()

    def read(self, artifact_id: str, *, expected_sha256: str, expected_size_bytes: int) -> bytes:
        path = self._path(artifact_id)
        if type(expected_size_bytes) is not int or not 0 <= expected_size_bytes <= self.max_file_size_bytes:
            raise MaterialArtifactConflict
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise MaterialArtifactConflict
        self._reject_symlink(path)
        digest = hashlib.sha256()
        chunks = []
        size = 0
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK_SIZE):
                    size += len(chunk)
                    if size > expected_size_bytes or size > self.max_file_size_bytes:
                        raise MaterialArtifactConflict
                    digest.update(chunk)
                    chunks.append(chunk)
        except MaterialArtifactConflict:
            raise
        except OSError:
            raise MaterialArtifactStorageError("Material artifact is unavailable") from None
        if size != expected_size_bytes or digest.hexdigest() != expected_sha256:
            raise MaterialArtifactConflict
        return b"".join(chunks)
