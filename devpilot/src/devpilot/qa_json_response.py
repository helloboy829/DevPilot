"""Version-pinned, pure buffering/decoding for one frozen QA JSON response.

No transport, timers, environment, database, gold, grading or execution authority.
Only the caller can attest successful end-of-body by calling ``finish``. Partial
transport failures/cancellation must never be finalized into collected output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from devpilot.qa_json_binding import QAJSONBinding

_VERSION = "qa-json-response.v1"
ResponseKind = Literal["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output"]


@dataclass(frozen=True, slots=True)
class ResponseResult:
    """Sensitive internal result, not a public DTO, verdict or delivery receipt."""

    kind: ResponseKind
    body_bytes: int
    output: str | None = field(repr=False)


class QAJSONResponseBuffer:
    """Consume bounded yielded raw bytes, never compressed/streaming text.

    ``body_bytes`` counts at most max+1 bytes consumed from yielded raw chunks,
    not wire traffic, transport read-ahead or billing. Oversize chunks are sliced
    before copying. Declared length is only an early rejection, never permission
    to exceed the real byte budget. Raw bytes are discarded on finalization.

    This is a single-owner, synchronous state machine. ``feed`` runs between I/O
    awaits; the caller must offload ``finish`` when it may decode/extract. Do not
    feed concurrently with finalization or finalize after an interrupted stream.
    """

    __slots__ = ("_binding", "_body", "_body_bytes", "_maximum", "_result")

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
        self._maximum = max_response_bytes
        self._result: ResponseResult | None = None
        media = content_type.split(";", 1)[0].strip().lower()
        encoding = content_encoding.strip().lower()
        if not 200 <= http_status < 300:
            self._close("http_error")
        elif not re.fullmatch(r"application/(?:json|[a-z0-9!#$&^_.+-]+\+json)", media) or encoding != "identity":
            self._close("unsupported_response")
        elif content_length.isascii() and content_length.isdecimal() and (len(content_length) > 20 or int(content_length) > max_response_bytes):
            self._close("response_limit")

    @property
    def version(self) -> str:
        return _VERSION

    @property
    def body_bytes(self) -> int:
        return self._body_bytes

    @property
    def terminal(self) -> bool:
        return self._result is not None

    def __repr__(self) -> str:
        return f"QAJSONResponseBuffer(version={_VERSION!r}, body_bytes={self._body_bytes}, terminal={self.terminal})"

    def _close(self, kind: ResponseKind, output: str | None = None) -> ResponseResult:
        self._result = ResponseResult(kind, self._body_bytes, output)
        self._body.clear()
        return self._result

    def feed(self, chunk: bytes) -> None:
        if self.terminal:
            raise ValueError("Response buffer is closed")
        if type(chunk) is not bytes:
            raise ValueError("Invalid QA JSON response chunk")
        remaining = self._maximum + 1 - self._body_bytes
        self._body.extend(chunk[:remaining])
        self._body_bytes = len(self._body)
        if self._body_bytes > self._maximum:
            self._close("response_limit")

    def finish(self) -> ResponseResult:
        """Finalize ONLY after normal end-of-body, or return a prior rejection.

        Repeated calls return the same immutable result; late feeds are rejected.
        UTF-8 and existing strict pointer/JSON parsing reject whole documents,
        including duplicate keys, non-finite numbers and unusable empty output.
        """
        if self._result is not None:
            return self._result
        try:
            output = self._binding.extract(self._body.decode("utf-8", errors="strict"))
            if not output.strip():
                raise ValueError
        except (ValueError, UnicodeError):
            return self._close("invalid_output")
        return self._close("output_collected", output)
