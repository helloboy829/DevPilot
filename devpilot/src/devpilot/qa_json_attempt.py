"""Versioned single-attempt JSON collector, with an explicit client capability.

A durable caller must separately admit the run (ownership, immutable versions,
consent, target policy, run-wide budgets), render INPUTS ONLY, record dispatch
before calling, and never automatically resend uncertain attempts. This module
has no expected-answer access, verdict, evidence persistence or run authority.
Outputs are sensitive internal values, not a log/public DTO.
"""

from __future__ import annotations

import asyncio
import time
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


@dataclass(slots=True)
class _Progress:
    body_bytes: int = 0


async def _read(response, binding, maximum, progress):
    """Retain at most limit+1 yielded raw bytes; transport may read ahead."""
    buffer = QAJSONResponseBuffer(
        binding,
        http_status=response.status_code,
        content_type=response.headers.get("content-type", ""),
        content_encoding=response.headers.get("content-encoding", "identity"),
        content_length=response.headers.get("content-length", ""),
        max_response_bytes=maximum,
    )
    if buffer.terminal:
        result = buffer.finish()
        return result.kind, result.body_bytes, result.output
    async for chunk in response.aiter_raw(chunk_size=min(16_384, maximum + 1)):
        buffer.feed(chunk)
        progress.body_bytes = buffer.body_bytes
        if buffer.terminal:
            result = buffer.finish()
            return result.kind, result.body_bytes, result.output
    # Decode AND extract off-loop, only after normal end-of-body. Transport
    # failure/cancellation leaves the buffer unfinalized and cannot yield output.
    result = await asyncio.to_thread(buffer.finish)
    return result.kind, result.body_bytes, result.output


async def collect_json_attempt(request: FrozenRequest, binding: QAJSONBinding, limits: AttemptLimits, *, client_factory: ClientFactory, version: str = _VERSION) -> AttemptObservation:
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
    if version != _VERSION or not callable(client_factory):
        raise ValueError("Invalid attempt collector")
    if not isinstance(request, FrozenRequest) or not isinstance(binding, QAJSONBinding) or not isinstance(limits, AttemptLimits):
        raise ValueError("Invalid attempt input")
    # Defensive validation happens before any client is created; no gold is accepted.
    spec = QAJSONRequest(request)
    checked = QAJSONBinding.from_dict(binding.to_dict())
    checked_limits = AttemptLimits(limits.timeout_ms, limits.max_response_bytes)
    started = time.perf_counter()
    status, output = None, None
    progress = _Progress()
    try:
        async with asyncio.timeout(checked_limits.timeout_ms / 1000):
            async with client_factory(spec.url, timeout_seconds=checked_limits.timeout_ms / 1000) as client:
                async with client.stream(spec.method, spec.url, headers=spec.headers, content=spec.content) as response:
                    status = response.status_code
                    kind, _, output = await _read(response, checked, checked_limits.max_response_bytes, progress)
    except EvaluationPolicyError:
        kind, output = "policy_rejected", None
    except (httpx.HTTPError, TimeoutError, ValueError):
        kind, output = "delivery_unknown", None
    return AttemptObservation(kind=kind, http_status=status, body_bytes=progress.body_bytes, elapsed_ms=(time.perf_counter() - started) * 1000, output=output)
