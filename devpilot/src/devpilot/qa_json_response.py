"""Version-pinned, pure buffering/decoding for one frozen QA JSON response.

No transport, timers, environment, database, gold, grading or execution authority.
Only the caller can attest successful end-of-body by calling ``finish``. Partial
transport failures/cancellation must never be finalized into collected output.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from devpilot.qa_json_binding import QAJSONBinding

_VERSION = "qa-json-response.v1"
ResponseKind = Literal["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output"]
CaptureStatus = Literal["complete", "partial", "truncated"]

_MEDIA_TYPE = re.compile(r"application/[!#$%&'*+.^_`|~0-9a-z-]+", re.IGNORECASE)
_CONTENT_ENCODINGS = frozenset({"identity", "gzip", "deflate", "br", "zstd", "compress"})


@dataclass(frozen=True, slots=True)
class ResponseResult:
    """Sensitive internal result, not a public DTO, verdict or delivery receipt."""

    kind: ResponseKind
    body_bytes: int
    output: str | None = field(repr=False)
    captured_body: bytes = field(default=b"", repr=False, compare=False)
    capture_status: CaptureStatus = field(default="complete", compare=False)
    response_content_type: str | None = field(default=None, compare=False)
    response_content_encoding: str = field(default="identity", compare=False)
    captured_body_sha256: str | None = field(default=None, repr=False, compare=False)


class QAJSONResponseBuffer:
    """Consume bounded yielded raw bytes, never compressed/streaming text.

    ``body_bytes`` counts at most max+1 bytes consumed from yielded raw chunks,
    not wire traffic, transport read-ahead or billing. Oversize chunks are sliced
    before copying. The result retains at most max raw bytes; one additional
    observed byte marks truncation. Content-Length never bypasses body capture.

    This is a single-owner, synchronous state machine. ``feed`` runs between I/O
    awaits; the caller must offload ``finish`` when it may decode/extract. Do not
    feed concurrently with finalization or finalize after an interrupted stream.
    """

    __slots__ = ("_binding", "_body", "_body_bytes", "_maximum", "_result", "_kind", "_content_type", "_content_encoding", "_capture_status", "_capture_hash")

    def __init__(
        self,
        binding: QAJSONBinding,
        *,
        http_status: int,
        content_type: str = "",
        content_encoding: str = "identity",
        content_length: str = "",
        max_response_bytes: int = 1_048_576,
        version: str = _VERSION,
    ):
        try:
            if (
                version != _VERSION
                or type(http_status) is not int
                or not 100 <= http_status <= 999
                or type(max_response_bytes) is not int
                or not 1 <= max_response_bytes <= 1_048_576
                or not all(isinstance(value, str) for value in (content_type, content_encoding, content_length))
                or not isinstance(binding, QAJSONBinding)
            ):
                raise ValueError
            self._binding = QAJSONBinding.from_dict(binding.to_dict())
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid QA JSON response input") from None
        self._body = bytearray()
        self._body_bytes = 0
        self._capture_hash = hashlib.sha256()
        self._maximum = max_response_bytes
        self._result: ResponseResult | None = None
        self._content_type = _safe_content_type(content_type)
        self._content_encoding = _safe_content_encoding(content_encoding)
        self._capture_status: CaptureStatus = "partial"
        media = content_type.split(";", 1)[0].strip().lower()
        encoding = content_encoding.strip().lower()
        if not 200 <= http_status < 300:
            self._kind = "http_error"
        elif not re.fullmatch(r"application/(?:json|[a-z0-9!#$&^_.+-]+\+json)", media) or encoding != "identity":
            self._kind = "unsupported_response"
        else:
            self._kind = None

    @property
    def version(self) -> str:
        return _VERSION

    @property
    def body_bytes(self) -> int:
        return self._body_bytes

    @property
    def captured_body(self) -> bytes:
        return bytes(self._body)

    @property
    def captured_body_sha256(self) -> str:
        return self._capture_hash.hexdigest()

    @property
    def capture_status(self) -> CaptureStatus:
        return self._capture_status

    @property
    def response_content_type(self) -> str | None:
        return self._content_type

    @property
    def response_content_encoding(self) -> str:
        return self._content_encoding

    @property
    def terminal(self) -> bool:
        return self._result is not None

    def __repr__(self) -> str:
        return f"QAJSONResponseBuffer(version={_VERSION!r}, body_bytes={self._body_bytes}, terminal={self.terminal})"

    def _close(self, kind: ResponseKind, output: str | None = None, *, capture_status: CaptureStatus = "complete") -> ResponseResult:
        self._capture_status = capture_status
        self._result = ResponseResult(
            kind,
            self._body_bytes,
            output,
            bytes(self._body),
            capture_status,
            self._content_type,
            self._content_encoding,
            self._capture_hash.hexdigest(),
        )
        return self._result

    def feed(self, chunk: bytes) -> None:
        if self.terminal:
            raise ValueError("Response buffer is closed")
        if type(chunk) is not bytes:
            raise ValueError("Invalid QA JSON response chunk")
        remaining = self._maximum + 1 - self._body_bytes
        accepted = chunk[:remaining]
        self._body_bytes += len(accepted)
        captured = accepted[: self._maximum - len(self._body)]
        self._body.extend(captured)
        self._capture_hash.update(captured)
        if self._body_bytes > self._maximum:
            self._close(self._kind or "response_limit", capture_status="truncated")

    def finish(self) -> ResponseResult:
        """Finalize ONLY after normal end-of-body, or return a prior rejection.

        Repeated calls return the same immutable result; late feeds are rejected.
        UTF-8 and existing strict pointer/JSON parsing reject whole documents,
        including duplicate keys, non-finite numbers and unusable empty output.
        The bounded raw prefix remains available on the immutable result.
        """
        if self._result is not None:
            return self._result
        if self._kind is not None:
            return self._close(self._kind)
        try:
            output = self._binding.extract(self._body.decode("utf-8", errors="strict"))
            if not output.strip():
                raise ValueError
        except (ValueError, UnicodeError):
            return self._close("invalid_output")
        return self._close("output_collected", output)


def _safe_content_type(value: str) -> str | None:
    media = value.split(";", 1)[0].strip().lower()
    return media if len(media) <= 127 and _MEDIA_TYPE.fullmatch(media) else None


def _safe_content_encoding(value: str) -> str:
    encoding = value.strip().lower()
    return encoding if encoding in _CONTENT_ENCODINGS else "other"
