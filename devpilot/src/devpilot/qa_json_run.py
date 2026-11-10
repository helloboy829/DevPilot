"""Versioned bounded JSON run orchestration with explicit caller capabilities.

This is not execution admission, a durable journal, a verdict or an exporter.
The caller owns authorization, target policy, global/run-wide byte quotas and
cancellation-safe persistence. No default clock, client, credentials or DB.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from devpilot.qa_json_attempt import AttemptLimits, AttemptObservation
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest

_VERSION = "qa-json-run.v1"


@dataclass(frozen=True, slots=True)
class JSONRunLimits:
    request_count: int
    concurrency: int
    timeout_ms: int
    deadline_ms: int
    max_response_bytes: int

    def __post_init__(self):
        values = ((self.request_count, 1, 10_000), (self.concurrency, 1, 64), (self.timeout_ms, 100, 300_000), (self.max_response_bytes, 1, 1_048_576))
        if any(type(value) is not int or not lower <= value <= upper for value, lower, upper in values) or type(self.deadline_ms) is not int or self.deadline_ms <= 0:
            raise ValueError("Invalid JSON run limits")


class JSONRunStopped(Exception):
    """A run stopped without permission to resume or resend any ordinal."""


async def run_json_attempts[Ticket](
    request: FrozenRequest,
    binding: QAJSONBinding,
    inputs: tuple[str, ...],
    limits: JSONRunLimits,
    *,
    now_ms: Callable[[], int],
    reserve_attempt: Callable[[int, int], Awaitable[Ticket]],
    collect_attempt: Callable[[FrozenRequest, QAJSONBinding, AttemptLimits], Awaitable[AttemptObservation]],
    record_attempt: Callable[[Ticket, AttemptObservation], Awaitable[None]],
    check_active: Callable[[], Awaitable[bool]],
    version: str = _VERSION,
) -> None:
    """Run the complete finite attempt loop; successful return is NOT PASS.

    Each ordinal is sent at most once and only AFTER its reservation callback
    acknowledges durable dispatch. A callback is not proof of that durability
    or policy. The caller must drain its DB operations on cancellation before
    returning/raising, and finalize only after this coroutine has drained.
    The absolute deadline uses the caller's clock; it is not a new time budget.
    Render runs off-loop. Cancellation prevents its late result from dispatching
    but cannot terminate a render thread already in progress.
    """
    if version != _VERSION or not all(callable(value) for value in (now_ms, reserve_attempt, collect_attempt, record_attempt, check_active)):
        raise ValueError("Invalid JSON run capabilities")
    if not isinstance(request, FrozenRequest) or not isinstance(binding, QAJSONBinding) or not isinstance(limits, JSONRunLimits):
        raise ValueError("Invalid JSON run input")
    if type(inputs) is not tuple or not 1 <= len(inputs) <= 500 or any(not isinstance(text, str) for text in inputs) or limits.request_count < len(inputs):
        raise ValueError("Invalid JSON run input")

    ordinals = iter(range(1, limits.request_count + 1))
    stopped = asyncio.Event()
    tasks = []
    group = None

    async def consume():
        try:
            await consume_available()
        except BaseException:
            stopped.set()
            raise

    async def consume_available():
        for ordinal in ordinals:
            if stopped.is_set():
                raise JSONRunStopped
            spec = await asyncio.to_thread(binding.render, request, inputs[(ordinal - 1) % len(inputs)])
            ticket = await reserve_attempt(ordinal, len(spec.body.encode("utf-8")))
            remaining = min(limits.timeout_ms, limits.deadline_ms - now_ms())
            if remaining < 100 or stopped.is_set():
                raise JSONRunStopped
            observation = await collect_attempt(spec, binding, AttemptLimits(timeout_ms=remaining, max_response_bytes=limits.max_response_bytes))
            # Fence every other consumer BEFORE a potentially slow evidence write.
            # Already sent work still drains; unknown outcomes are never retried.
            if observation.kind == "delivery_unknown":
                stopped.set()
            await record_attempt(ticket, observation)
            if observation.kind == "delivery_unknown":
                raise JSONRunStopped

    async def monitor():
        while True:
            await asyncio.sleep(0.2)
            if not await check_active() or now_ms() >= limits.deadline_ms:
                raise JSONRunStopped

    try:
        async with asyncio.timeout(max(0.001, (limits.deadline_ms - now_ms()) / 1000)):
            tasks = [asyncio.create_task(consume()) for _ in range(limits.concurrency)]
            monitor_task = asyncio.create_task(monitor())
            tasks.append(monitor_task)
            group = asyncio.gather(*tasks[:-1])
            await asyncio.wait([group, monitor_task], return_when=asyncio.FIRST_COMPLETED)
            if monitor_task.done():
                monitor_task.result()
            await group
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if group is not None:
            await asyncio.gather(group, return_exceptions=True)
