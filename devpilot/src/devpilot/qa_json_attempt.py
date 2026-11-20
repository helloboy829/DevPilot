"""Versioned single-attempt JSON collector, with an explicit client capability.

A durable caller must separately admit the run (ownership, immutable versions,
consent, target policy, run-wide budgets), render INPUTS ONLY, record dispatch
before calling, and never automatically resend uncertain attempts. This module
has no expected-answer access, verdict, evidence persistence or run authority.
Outputs are sensitive internal values, not a log/public DTO.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from devpilot.pinned_http import EvaluationPolicyError
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.qa_json_request import QAJSONRequest
from devpilot.qa_json_response import QAJSONResponseBuffer
from devpilot.request_versions import FrozenRequest

_VERSION = "qa-json-attempt.v1"


class ClientFactory(Protocol):
    """Caller-owned client policy; no default client, DNS or authority lookup."""

    def __call__(self, url: str, *, timeout_seconds: float) -> AbstractAsyncContextManager[httpx.AsyncClient]: ...


AttemptKind = Literal["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"]
AttemptCaptureStatus = Literal["not_received", "partial", "complete", "truncated"]
ResponseBodyHashScope = Literal["none", "full", "prefix"]


@dataclass(frozen=True, slots=True)
class AttemptLimits:
    timeout_ms: int = 30_000
    max_response_bytes: int = 1_048_576

    def __post_init__(self):
        if type(self.timeout_ms) is not int or type(self.max_response_bytes) is not int or not 100 <= self.timeout_ms <= 300_000 or not 1 <= self.max_response_bytes <= 1_048_576:
            raise ValueError("Invalid attempt limits")


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    kind: AttemptKind
    http_status: int | None
    body_bytes: int
    elapsed_ms: float
    output: str | None = field(repr=False)
    request_body_sha256: str | None = field(default=None, repr=False)
    request_body_bytes: int = 0
    response_body: bytes = field(default=b"", repr=False)
    response_capture_status: AttemptCaptureStatus = "not_received"
    response_content_type: str | None = None
    response_content_encoding: str | None = None
    response_body_sha256: str | None = field(default=None, repr=False)
    response_body_hash_scope: ResponseBodyHashScope = "none"

    @property
    def response_body_bytes(self) -> int:
        """Explicit name for the observed raw response byte count."""
        return self.body_bytes


@dataclass(slots=True)
class AttemptCaptureState:
    """Caller-owned, bounded capture updated as one attempt progresses."""

    request_body_sha256: str | None = field(default=None, repr=False)
    request_body_bytes: int = 0
    http_status: int | None = None
    response_body: bytes = field(default=b"", repr=False)
    response_body_bytes: int = 0
    response_capture_status: AttemptCaptureStatus = "not_received"
    response_content_type: str | None = None
    response_content_encoding: str | None = None
    response_body_sha256: str | None = field(default=None, repr=False)
    response_body_hash_scope: ResponseBodyHashScope = "none"

    def __repr__(self) -> str:
        return f"AttemptCaptureState(request_body_bytes={self.request_body_bytes}, http_status={self.http_status}, response_body_bytes={self.response_body_bytes}, response_capture_status={self.response_capture_status!r})"

    def _set_request(self, content: bytes) -> None:
        self.request_body_sha256 = hashlib.sha256(content).hexdigest()
        self.request_body_bytes = len(content)

    def _set_head(self, status: int, response: QAJSONResponseBuffer) -> None:
        self.http_status = status
        self.response_capture_status = "partial"
        self.response_content_type = response.response_content_type
        self.response_content_encoding = response.response_content_encoding
        self._set_buffer(response)

    def _set_buffer(self, response: QAJSONResponseBuffer) -> None:
        self.response_body = response.captured_body
        self.response_body_bytes = response.body_bytes
        self.response_capture_status = response.capture_status
        self._set_response_hash(response.captured_body_sha256)

    def _set_result(self, response) -> None:
        self.response_body = response.captured_body
        self.response_body_bytes = response.body_bytes
        self.response_capture_status = response.capture_status
        self.response_content_type = response.response_content_type
        self.response_content_encoding = response.response_content_encoding
        self._set_response_hash(response.captured_body_sha256)

    def _set_response_hash(self, digest: str | None) -> None:
        if self.response_capture_status == "not_received":
            self.response_body_sha256 = None
            self.response_body_hash_scope = "none"
            return
        self.response_body_sha256 = digest if digest is not None else hashlib.sha256(self.response_body).hexdigest()
        self.response_body_hash_scope = "full" if self.response_capture_status == "complete" else "prefix"

    def _mark_complete(self) -> None:
        self.response_capture_status = "complete"
        self.response_body_hash_scope = "full"


async def _read(response, binding, maximum, capture):
    """Retain at most limit+1 yielded raw bytes; transport may read ahead."""
    buffer = QAJSONResponseBuffer(
        binding,
        http_status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        content_encoding=response.headers.get("content-encoding", "identity"),
        content_length=response.headers.get("content-length", ""),
        max_response_bytes=maximum,
    )
    capture._set_head(response.status_code, buffer)
    async for chunk in response.aiter_raw():
        buffer.feed(chunk)
        capture._set_buffer(buffer)
        if buffer.terminal:
            result = buffer.finish()
            capture._set_result(result)
            return result
    # Decode AND extract off-loop, only after normal end-of-body. Transport
    # failure/cancellation leaves the buffer unfinalized and cannot yield output.
    capture._mark_complete()
    result = await asyncio.to_thread(buffer.finish)
    capture._set_result(result)
    return result


async def collect_json_attempt(
    request: FrozenRequest,
    binding: QAJSONBinding,
    limits: AttemptLimits,
    *,
    client_factory: ClientFactory,
    version: str = _VERSION,
    capture_state: AttemptCaptureState | None = None,
    on_request_ready: Callable[[str, int, str], Awaitable[None]] | None = None,
) -> AttemptObservation:
    """Send at most once through an explicit caller-owned client; NEVER infer PASS.

    Cancellation propagates and response/client resources close. A timeout or
    transport failure does not prove the server did not process the request;
    delivery_unknown is never an instruction to retry. The factory must provide
    approved DNS pinning, TLS and no redirects/proxies; this function cannot
    certify a supplied capability. It performs no admission or dispatch journaling.
    body_bytes counts bytes retained from yielded raw chunks, not transport
    read-ahead, headers/wire
    traffic or provider billing.
    """
    if version != _VERSION or not callable(client_factory) or (on_request_ready is not None and not callable(on_request_ready)):
        raise ValueError("Invalid attempt collector")
    if not isinstance(request, FrozenRequest) or not isinstance(binding, QAJSONBinding) or not isinstance(limits, AttemptLimits) or (capture_state is not None and not isinstance(capture_state, AttemptCaptureState)):
        raise ValueError("Invalid attempt input")
    # Defensive validation happens before any client is created; no gold is accepted.
    spec = QAJSONRequest(request)
    checked = QAJSONBinding.from_dict(binding.to_dict())
    checked_limits = AttemptLimits(limits.timeout_ms, limits.max_response_bytes)
    started = time.perf_counter()
    output = None
    capture = capture_state if capture_state is not None else AttemptCaptureState()
    try:
        async with asyncio.timeout(checked_limits.timeout_ms / 1000):
            async with client_factory(spec.url, timeout_seconds=checked_limits.timeout_ms / 1000) as client:
                content = spec.content
                capture._set_request(content)
                if on_request_ready is not None:
                    await on_request_ready(capture.request_body_sha256, capture.request_body_bytes, spec.version)
                async with client.stream(spec.method, spec.url, headers=spec.headers, content=content) as response:
                    result = await _read(response, checked, checked_limits.max_response_bytes, capture)
                    kind, output = result.kind, result.output
    except EvaluationPolicyError:
        kind, output = "policy_rejected", None
    except (httpx.HTTPError, TimeoutError, ValueError):
        kind, output = "delivery_unknown", None
    return AttemptObservation(
        kind=kind,
        http_status=capture.http_status,
        body_bytes=capture.response_body_bytes,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        output=output,
        request_body_sha256=capture.request_body_sha256,
        request_body_bytes=capture.request_body_bytes,
        response_body=capture.response_body,
        response_capture_status=capture.response_capture_status,
        response_content_type=capture.response_content_type,
        response_content_encoding=capture.response_content_encoding,
        response_body_sha256=capture.response_body_sha256,
        response_body_hash_scope=capture.response_body_hash_scope,
    )
