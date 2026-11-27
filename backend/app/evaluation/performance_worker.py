"""Explicit synthetic-only performance ledger worker; never opens network connections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass

from app.evaluation.performance_run_repository import ExecutionSnapshotInvalid, PerformanceRunRepository
from app.evaluation.repository import Conflict


@dataclass(frozen=True)
class SyntheticResponse:
    status_code: int
    body: bytes


class SyntheticPerformanceTransport:
    """Concrete in-process transport used only to exercise ledger and evidence flows."""

    def __init__(self, *, fail_at_ordinal: int | None = None, delay_ms: int = 0):
        if fail_at_ordinal is not None and (type(fail_at_ordinal) is not int or not 0 <= fail_at_ordinal < 11_000):
            raise ValueError("Invalid synthetic failure ordinal")
        if type(delay_ms) is not int or not 0 <= delay_ms <= 300_000:
            raise ValueError("Invalid synthetic delay")
        self.fail_at_ordinal = fail_at_ordinal
        self.delay_ms = delay_ms

    async def request(self, request_body: bytes, *, ordinal: int) -> SyntheticResponse:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        else:
            await asyncio.sleep(0)
        json.loads(request_body)
        if ordinal == self.fail_at_ordinal:
            raise OSError("Synthetic transport failure")
        digest = hashlib.sha256(request_body).hexdigest()
        return SyntheticResponse(200, json.dumps({"synthetic": True, "request_sha256": digest}, separators=(",", ":")).encode())


@dataclass(frozen=True)
class _Dispatch:
    ticket: dict
    started_ns: int
    request_bytes: int


class PerformanceWorker:
    """Explicit closed-loop synthetic worker with a single journal writer."""

    def __init__(self, repository: PerformanceRunRepository, *, transport: SyntheticPerformanceTransport):
        if type(transport) is not SyntheticPerformanceTransport:
            raise ValueError("Only the built-in synthetic performance transport is allowed")
        self.repository = repository
        self.transport = transport

    async def _send(self, body: bytes, ordinal: int, timeout_ms: int) -> tuple[int, SyntheticResponse | None]:
        try:
            response = await asyncio.wait_for(self.transport.request(body, ordinal=ordinal), timeout=timeout_ms / 1000)
        except Exception:
            # Any transport error after send_started is uncertain; let the coordinator
            # stop admission and drain peers before recording this fence as unknown.
            response = None
        return time.monotonic_ns(), response

    async def _observe(self, owner, project_id, dispatch, finished_ns, response, max_response_bytes):
        oversized = len(response.body) > max_response_bytes
        await self.repository.record_observation(
            owner,
            project_id,
            dispatch.ticket,
            state="failed" if oversized else "succeeded",
            finished_ns=finished_ns,
            elapsed_ms=(finished_ns - dispatch.started_ns) / 1_000_000,
            response_status=response.status_code,
            response_bytes=len(response.body),
            response_body=None if oversized else response.body,
            response_capture_status="policy_skipped" if oversized else "complete",
            response_content_type=None if oversized else "application/json",
            response_content_encoding=None if oversized else "identity",
        )
        if oversized:
            return "response_byte_budget"
        artifact = await self.repository.reconcile_response_artifact(owner, project_id, dispatch.ticket["run_id"], dispatch.ticket["ordinal"])
        return None if artifact["status"] in {"complete", "partial", "truncated"} else "evidence_write_failed"

    async def run_admitted(self, owner: str, project_id: str, run_id: str, *, worker_id: str) -> dict:
        start_wall_ns = time.monotonic_ns()
        try:
            snapshot = await self.repository.get_execution_snapshot(owner, project_id, run_id)
        except ExecutionSnapshotInvalid:
            interrupted = await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns(), reason="preflight_invalid")
            if not interrupted:
                raise
            return await self.repository.get_run(owner, project_id, run_id)
        await self.repository.mark_synthetic_execution(owner, project_id, run_id)
        profile = snapshot["profile"]
        manifest = snapshot["manifest"]
        requests = snapshot["requests"]
        for offset in range(0, len(manifest), 200):
            prior = await self.repository.list_dispatches(owner, project_id, run_id, offset=offset, limit=min(200, len(manifest) - offset))
            if any(row["state"] != "pending" for row in prior):
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns())
                return await self.repository.get_run(owner, project_id, run_id)

        wall_deadline = start_wall_ns + profile.wall_time_limit_seconds * 1_000_000_000
        drain_ns = profile.drain_limit_seconds * 1_000_000_000
        limit = min(profile.concurrency, profile.max_in_flight)
        measurement_start = duration_deadline = None
        stop_reason = stop_at = None
        reserved_bytes = 0
        active: dict[asyncio.Task, _Dispatch] = {}

        async def cancel_transport():
            for task in active:
                task.cancel()
            await asyncio.gather(*active, return_exceptions=True)
            active.clear()

        async def drain_transport_after_cancellation():
            if active:
                done, pending = await asyncio.wait(active, timeout=profile.drain_limit_seconds)
                for task in done:
                    dispatch = active.pop(task)
                    try:
                        finished_ns, response = task.result()
                    except (asyncio.CancelledError, Exception):
                        continue
                    if response is not None:
                        try:
                            await self._observe(owner, project_id, dispatch, finished_ns, response, profile.max_response_bytes)
                        except Exception:
                            # The durable run interruption below preserves unresolved
                            # dispatches as unknown if evidence could not be recorded.
                            pass
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                active.clear()
            await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns(), reason="cancelled")

        def admission_deadline():
            if duration_deadline is not None and duration_deadline < wall_deadline:
                return duration_deadline, "duration_limit"
            return wall_deadline, "wall_time_limit"

        def transport_failure_landed():
            return any(task.done() and (task.cancelled() or task.exception() is not None or task.result()[1] is None) for task in active)

        try:
            for phase in ("warmup", "measurement"):
                entries = [entry for entry in manifest if entry["phase"] == phase]
                index = 0
                phase_drains_at = None
                while active or (stop_reason is None and index < len(entries)):
                    deadline, deadline_reason = admission_deadline()
                    for task in tuple(active):
                        if not task.done():
                            continue
                        dispatch = active.pop(task)
                        finished_ns, response = task.result()
                        if response is None:
                            # The repository's unknown transition interrupts all peers.
                            # Leave this fence open until healthy peers are accounted for.
                            reason = "delivery_unknown"
                        else:
                            reserved_bytes -= max(0, profile.max_response_bytes - len(response.body))
                            reason = await self._observe(owner, project_id, dispatch, finished_ns, response, profile.max_response_bytes)
                        if stop_reason is None and finished_ns >= deadline:
                            stop_at, stop_reason = deadline, deadline_reason
                        elif reason and stop_reason is None:
                            stop_at = finished_ns
                            stop_reason = reason

                    now_ns = time.monotonic_ns()
                    if stop_reason is None and index < len(entries) and now_ns >= deadline:
                        stop_reason, stop_at = deadline_reason, deadline

                    if stop_reason is None and index < len(entries) and len(active) < limit:
                        entry = entries[index]
                        try:
                            body = requests[entry["case_id"]].body.encode("utf-8")
                        except (KeyError, UnicodeError):
                            raise Conflict from None
                        reservation = len(body) + profile.max_response_bytes
                        if len(body) > profile.max_request_bytes:
                            stop_reason, stop_at = "request_byte_budget", now_ns
                        elif reserved_bytes + reservation > profile.max_total_bytes:
                            # A peer may release unused response capacity; don't consume
                            # an ordinal or interrupt while reservations can still shrink.
                            if not active:
                                stop_reason, stop_at = "aggregate_byte_budget", now_ns
                        else:
                            lease = await self.repository.claim_dispatch(
                                owner,
                                project_id,
                                run_id,
                                entry["ordinal"],
                                worker_id=worker_id,
                                lease_expires_at_ms=int(time.time() * 1000) + profile.drain_limit_seconds * 1000 + profile.request_timeout_ms,
                            )
                            if transport_failure_landed():
                                continue
                            ticket = await self.repository.acknowledge_dispatch(
                                owner,
                                project_id,
                                run_id,
                                entry["ordinal"],
                                worker_id=worker_id,
                                lease_epoch=lease["lease_epoch"],
                                request_bytes=len(body),
                                request_hash=hashlib.sha256(body).hexdigest(),
                            )
                            started_ns = time.monotonic_ns()
                            if started_ns >= deadline:
                                stop_reason, stop_at = deadline_reason, deadline
                            elif transport_failure_landed():
                                # Observe the already-landed failure before opening another fence.
                                continue
                            else:
                                started = await self.repository.start_dispatch(owner, project_id, run_id, ticket, worker_id=worker_id, lease_epoch=lease["lease_epoch"], send_started_ns=started_ns)
                                if phase == "measurement" and measurement_start is None:
                                    measurement_start = started_ns
                                    if profile.duration_limit_seconds is not None:
                                        duration_deadline = started_ns + profile.duration_limit_seconds * 1_000_000_000
                                active[asyncio.create_task(self._send(body, entry["ordinal"], profile.request_timeout_ms))] = _Dispatch(started, started_ns, len(body))
                                reserved_bytes += reservation
                                index += 1
                                if index == len(entries):
                                    phase_drains_at = time.monotonic_ns() + drain_ns
                                continue

                    if active:
                        if stop_at is not None:
                            wake_at = min(stop_at, deadline) + drain_ns
                        elif phase_drains_at is not None:
                            wake_at = min(phase_drains_at, deadline + drain_ns)
                        else:
                            wake_at = deadline
                        done, _ = await asyncio.wait(active, timeout=max(0, (wake_at - time.monotonic_ns()) / 1_000_000_000), return_when=asyncio.FIRST_COMPLETED)
                        if not done and (stop_at is not None or phase_drains_at is not None):
                            if stop_reason is None:
                                stop_at = min(wake_at, deadline)
                                stop_reason = deadline_reason if deadline <= wake_at else "delivery_unknown"
                            await cancel_transport()
                if stop_reason is not None:
                    break
        except asyncio.CancelledError:
            await drain_transport_after_cancellation()
            raise
        except Exception:
            await cancel_transport()
            await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns())
            raise

        if stop_reason is not None:
            await self.repository.interrupt_run(owner, project_id, run_id, at_ns=stop_at, reason=stop_reason)
        else:
            if measurement_start is None:
                raise Conflict
            window_end_ns = max(time.monotonic_ns(), measurement_start + 1)
            await self.repository.close_measurement_window(owner, project_id, run_id, window_end_ns=window_end_ns)
        result = await self.repository.get_run(owner, project_id, run_id)
        if stop_reason is not None:
            result["stop_reason"] = stop_reason
        return result
