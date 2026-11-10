"""App policy adapter for the shared single-attempt JSON collector.

The durable Worker retains admission, dispatch-before-I/O, budgets, evidence and
unknown-delivery/no-resend authority. This is not an HTTP execution API.
"""

from __future__ import annotations

from devpilot.qa_json_attempt import AttemptKind, AttemptLimits, AttemptObservation
from devpilot.qa_json_attempt import collect_json_attempt as _collect_json_attempt
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest

from app.evaluation.http import evaluation_client

__all__ = ["AttemptKind", "AttemptLimits", "AttemptObservation", "collect_json_attempt"]


async def collect_json_attempt(request: FrozenRequest, binding: QAJSONBinding, config, limits: AttemptLimits) -> AttemptObservation:
    """Keep the existing App interface and its live outbound client policy."""

    def client_factory(url: str, *, timeout_seconds: float):
        return evaluation_client(config, url, timeout_seconds=timeout_seconds)

    return await _collect_json_attempt(request, binding, limits, client_factory=client_factory)
