"""Explicit synthetic-only performance ledger worker; never opens network connections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass

from app.evaluation.performance_run_repository import PerformanceRunRepository
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

    async def request(self, request_body: bytes) -> SyntheticResponse:
        if self.delay_ms:
            await asyncio.sleep(self.delay_ms / 1000)
        else:
            await asyncio.sleep(0)
        request = json.loads(request_body)
        if request.get("ordinal") == self.fail_at_ordinal:
            raise OSError("Synthetic transport failure")
        digest = hashlib.sha256(request_body).hexdigest()
        return SyntheticResponse(200, json.dumps({"synthetic": True, "request_sha256": digest}, separators=(",", ":")).encode())


class PerformanceWorker:
    """Explicitly consume an admitted run with bounded synthetic requests only.

    This is not a real load generator: it is intentionally serial and has no HTTP,
    DNS, socket, subprocess, retry, or background-polling path.
    """

    def __init__(self, repository: PerformanceRunRepository, *, transport: SyntheticPerformanceTransport):
        if type(transport) is not SyntheticPerformanceTransport:
            raise ValueError("Only the built-in synthetic performance transport is allowed")
        self.repository = repository
        self.transport = transport

    async def _result(self, owner, project_id, run_id, *, stop_reason=None):
        result = await self.repository.get_run(owner, project_id, run_id)
        if stop_reason is not None:
            result["stop_reason"] = stop_reason
        return result

    async def run_admitted(self, owner: str, project_id: str, run_id: str, *, worker_id: str) -> dict:
        start_wall_ns = time.monotonic_ns()
        snapshot = await self.repository.get_execution_snapshot(owner, project_id, run_id)
        await self.repository.mark_synthetic_execution(owner, project_id, run_id)
        profile = snapshot["profile"]
        total_bytes = 0
        measurement_start_ns = None
        prior = []
        for offset in range(0, len(snapshot["manifest"]), 200):
            page = await self.repository.list_dispatches(
                owner,
                project_id,
                run_id,
                offset=offset,
                limit=min(200, len(snapshot["manifest"]) - offset),
            )
            prior.extend(page)
        if any(row["state"] != "pending" for row in prior):
            # An earlier worker may have crossed the durable send fence. Reconcile
            # conservatively and never send that ordinal again.
            await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns())
            return await self._result(owner, project_id, run_id)

        for entry in snapshot["manifest"]:
            now_ns = time.monotonic_ns()
            if now_ns - start_wall_ns >= profile.wall_time_limit_seconds * 1_000_000_000:
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=now_ns, reason="wall_time_limit")
                return await self._result(owner, project_id, run_id, stop_reason="wall_time_limit")
            if entry["phase"] == "measurement" and measurement_start_ns is not None and profile.duration_limit_seconds is not None:
                if now_ns - measurement_start_ns >= profile.duration_limit_seconds * 1_000_000_000:
                    await self.repository.interrupt_run(owner, project_id, run_id, at_ns=now_ns, reason="duration_limit")
                    return await self._result(owner, project_id, run_id, stop_reason="duration_limit")

            request_body = json.dumps(
                {"synthetic": True, "ordinal": entry["ordinal"], "phase": entry["phase"], "case_id": entry["case_id"], "iteration": entry["iteration"]},
                separators=(",", ":"),
            ).encode()
            if len(request_body) > profile.max_request_bytes or total_bytes + len(request_body) + profile.max_response_bytes > profile.max_total_bytes:
                reason = "request_byte_budget" if len(request_body) > profile.max_request_bytes else "aggregate_byte_budget"
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=now_ns, reason=reason)
                return await self._result(owner, project_id, run_id, stop_reason=reason)

            lease = await self.repository.claim_dispatch(
                owner,
                project_id,
                run_id,
                entry["ordinal"],
                worker_id=worker_id,
                lease_expires_at_ms=int(time.time() * 1000) + profile.drain_limit_seconds * 1000 + profile.request_timeout_ms,
            )
            request_hash = hashlib.sha256(request_body).hexdigest()
            ticket = await self.repository.acknowledge_dispatch(
                owner,
                project_id,
                run_id,
                entry["ordinal"],
                worker_id=worker_id,
                lease_epoch=lease["lease_epoch"],
                request_bytes=len(request_body),
                request_hash=request_hash,
            )
            send_started_ns = time.monotonic_ns()
            if send_started_ns - start_wall_ns >= profile.wall_time_limit_seconds * 1_000_000_000 or (
                entry["phase"] == "measurement" and measurement_start_ns is not None and profile.duration_limit_seconds is not None and send_started_ns - measurement_start_ns >= profile.duration_limit_seconds * 1_000_000_000
            ):
                reason = "wall_time_limit" if send_started_ns - start_wall_ns >= profile.wall_time_limit_seconds * 1_000_000_000 else "duration_limit"
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=send_started_ns, reason=reason)
                return await self._result(owner, project_id, run_id, stop_reason=reason)
            started = await self.repository.start_dispatch(
                owner,
                project_id,
                run_id,
                ticket,
                worker_id=worker_id,
                lease_epoch=lease["lease_epoch"],
                send_started_ns=send_started_ns,
            )
            if entry["phase"] == "measurement" and measurement_start_ns is None:
                measurement_start_ns = send_started_ns

            try:
                deadline_ns = start_wall_ns + profile.wall_time_limit_seconds * 1_000_000_000
                if entry["phase"] == "measurement" and profile.duration_limit_seconds is not None:
                    duration_deadline_ns = measurement_start_ns + profile.duration_limit_seconds * 1_000_000_000
                    deadline_ns = min(deadline_ns, duration_deadline_ns)
                remaining_seconds = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
                if remaining_seconds <= 0:
                    raise TimeoutError("Synthetic execution deadline elapsed after durable start")
                response = await asyncio.wait_for(self.transport.request(request_body), timeout=min(profile.request_timeout_ms / 1000, remaining_seconds))
            except asyncio.CancelledError:
                finished_ns = time.monotonic_ns()
                await self.repository.record_observation(
                    owner,
                    project_id,
                    started,
                    state="unknown",
                    finished_ns=finished_ns,
                    elapsed_ms=(finished_ns - send_started_ns) / 1_000_000,
                    response_capture_status="not_received",
                )
                raise
            except Exception:
                finished_ns = time.monotonic_ns()
                await self.repository.record_observation(
                    owner,
                    project_id,
                    started,
                    state="unknown",
                    finished_ns=finished_ns,
                    elapsed_ms=(finished_ns - send_started_ns) / 1_000_000,
                    response_capture_status="not_received",
                )
                stop_reason = None
                if finished_ns - start_wall_ns >= profile.wall_time_limit_seconds * 1_000_000_000:
                    stop_reason = "wall_time_limit"
                elif entry["phase"] == "measurement" and profile.duration_limit_seconds is not None and measurement_start_ns is not None and finished_ns - measurement_start_ns >= profile.duration_limit_seconds * 1_000_000_000:
                    stop_reason = "duration_limit"
                return await self._result(owner, project_id, run_id, stop_reason=stop_reason)

            finished_ns = time.monotonic_ns()
            if len(response.body) > profile.max_response_bytes or total_bytes + len(request_body) + len(response.body) > profile.max_total_bytes:
                reason = "response_byte_budget" if len(response.body) > profile.max_response_bytes else "aggregate_byte_budget"
                await self.repository.record_observation(
                    owner,
                    project_id,
                    started,
                    state="failed",
                    finished_ns=finished_ns,
                    elapsed_ms=(finished_ns - send_started_ns) / 1_000_000,
                    response_status=response.status_code,
                    response_bytes=len(response.body),
                    response_capture_status="policy_skipped",
                )
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=finished_ns, reason=reason)
                return await self._result(owner, project_id, run_id, stop_reason=reason)
            total_bytes += len(request_body) + len(response.body)
            await self.repository.record_observation(
                owner,
                project_id,
                started,
                state="succeeded",
                finished_ns=finished_ns,
                elapsed_ms=(finished_ns - send_started_ns) / 1_000_000,
                response_status=response.status_code,
                response_bytes=len(response.body),
                response_body=response.body,
                response_capture_status="complete",
                response_content_type="application/json",
                response_content_encoding="identity",
            )
            artifact = await self.repository.reconcile_response_artifact(owner, project_id, run_id, started["ordinal"])
            if artifact["status"] not in {"complete", "partial", "truncated"}:
                await self.repository.interrupt_run(owner, project_id, run_id, at_ns=time.monotonic_ns(), reason="evidence_write_failed")
                return await self._result(owner, project_id, run_id, stop_reason="evidence_write_failed")

        if measurement_start_ns is None:
            raise Conflict
        window_end_ns = max(time.monotonic_ns(), measurement_start_ns + 1)
        await self.repository.close_measurement_window(owner, project_id, run_id, window_end_ns=window_end_ns)
        return await self._result(owner, project_id, run_id)
