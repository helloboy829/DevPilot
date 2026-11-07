"""App-owned durable dispatch journal, not execution admission or a network worker.

A future independently authorized caller must commit record_dispatch BEFORE sending.
Reservation is not permission to send; ambiguous writes must never trigger a send or
an automatic resend. No method decrypts requests, reads gold or stores output text.
Expired leases terminalize the WHOLE run: they never reclaim a possibly live slot.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import DBAPIError

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.repository import Conflict, NotFound


class JournalWriteUnconfirmed(Exception):
    """The write was not confirmed. Read state; NEVER infer permission to send/retry."""


class JournalLimits(StrictDTO):
    max_response_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    max_total_response_bytes: int = Field(default=67_108_864, ge=2, le=67_108_864)
    lease_grace_ms: int = Field(default=5_000, ge=100, le=30_000)

    @model_validator(mode="after")
    def enough_for_one_reservation(self):
        if self.max_total_response_bytes < self.max_response_bytes + 1:
            raise ValueError("Invalid journal response reservation")
        return self


class TechnicalObservation(StrictDTO):
    kind: Literal["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"]
    http_status: int | None = Field(default=None, ge=100, le=599)
    body_bytes: int = Field(ge=0, le=1_048_577)
    elapsed_ms: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def consistent(self):
        success = self.http_status is not None and 200 <= self.http_status < 300
        if (
            (self.kind in {"output_collected", "unsupported_response", "response_limit", "invalid_output"} and not success)
            or (self.kind == "http_error" and (self.http_status is None or success))
            or (self.kind == "policy_rejected" and (self.http_status is not None or self.body_bytes))
            or (self.kind == "output_collected" and not self.body_bytes)
            or (self.kind in {"http_error", "unsupported_response"} and self.body_bytes != 0)
        ):
            raise ValueError("Invalid technical observation")
        return self


@dataclass(frozen=True, slots=True)
class DispatchTicket:
    run_id: str
    ordinal: int
    sample_id: str = field(repr=False)
    expires_at_ms: int
    token: str = field(repr=False)


def _positive_int(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("Invalid journal parameter")
    return value


class DispatchJournalRepository(PlanRepository):
    def __init__(self, sf, *, protection=None, clock_ms=None):
        super().__init__(sf, protection=protection)
        self.clock_ms = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000

    def _time(self):
        return _positive_int(self.clock_ms(), 9_007_199_250_000_000)

    @asynccontextmanager
    async def _transaction(self):
        try:
            async with self.sf.begin() as session:
                yield session
        except DBAPIError:
            raise JournalWriteUnconfirmed("Journal write could not be confirmed") from None

    @staticmethod
    async def _journal_event(session, run, action, at, *, ordinal=None):
        sequence = (await session.execute(select(func.max(t.dispatch_audit.c.sequence)).where(t.dispatch_audit.c.run_id == run["id"]))).scalar_one() or 0
        await session.execute(insert(t.dispatch_audit).values(id=uuid4().hex, project_id=run["project_id"], run_id=run["id"], sequence=sequence + 1, action=action, ordinal=ordinal, at_ms=at))

    async def _journal(self, session, owner, project_id, run_id, *, lock=False):
        await self._project(session, owner, project_id)
        condition = (t.dispatch_runs.c.project_id == project_id) & (t.dispatch_runs.c.id == run_id)
        # A DB row write serializes all mutations for this run, including across
        # processes. Never hold this transaction over network/crypto/model I/O.
        statement = update(t.dispatch_runs).where(condition).values(revision=t.dispatch_runs.c.revision).returning(t.dispatch_runs) if lock else select(t.dispatch_runs).where(condition)
        row = (await session.execute(statement)).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    async def record_run(self, owner, project_id, plan_id, expected_plan_hash, limits: JournalLimits):
        """Record internal metadata only; caller still needs independent run admission.

        Only metadata and frozen sample IDs are read. Actual request/content/gold
        integrity, target authorization and global quotas remain caller obligations.
        """
        limits = JournalLimits.model_validate(limits.model_dump())
        if not isinstance(expected_plan_hash, str) or len(expected_plan_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_plan_hash):
            raise ValueError("Invalid journal plan hash")
        async with self._transaction() as session:
            plan = await self._plan(session, owner, project_id, plan_id)
            if not hmac.compare_digest(plan["definition_hash"], expected_plan_hash):
                raise Conflict
            definition = plan["definition"]
            dataset = await self._dataset(session, owner, project_id, plan["dataset_id"])
            if dataset["status"] != "frozen" or dataset["revision"] != definition["dataset_revision"] or dataset["content_hash"] != definition["dataset_hash"]:
                raise Conflict
            sample_ids = sorted((await session.execute(select(t.samples.c.sample_id).where(t.samples.c.dataset_id == dataset["id"]).limit(501))).scalars())
            if len(sample_ids) != definition["preflight"]["sample_count"] or not sample_ids:
                raise Conflict
            at = self._time()
            configured = definition["limits"]
            row = {
                "id": uuid4().hex,
                "project_id": project_id,
                "plan_id": plan_id,
                "plan_hash": expected_plan_hash,
                "scope": "dispatch_journal_only",
                "status": "recording",
                "request_count": configured["request_count"],
                "concurrency": configured["concurrency"],
                "timeout_ms": configured["timeout_ms"],
                "max_total_body_bytes": configured["max_total_body_bytes"],
                "max_response_bytes": limits.max_response_bytes,
                "max_total_response_bytes": limits.max_total_response_bytes,
                "lease_grace_ms": limits.lease_grace_ms,
                "started_at_ms": at,
                "deadline_ms": at + configured["wall_time_ms"],
                "reserved_body_bytes": 0,
                "reserved_response_bytes": 0,
                "revision": 1,
                "finished_at_ms": None,
                "stop_reason": None,
            }
            await session.execute(insert(t.dispatch_runs).values(**row))
            # Stable ordinal/sample binding is persisted before any future dispatch.
            # At most 10,000 rows, with batches to avoid dialect bind limits.
            for begin in range(0, row["request_count"], 100):
                await session.execute(
                    insert(t.dispatches),
                    [{"project_id": project_id, "run_id": row["id"], "ordinal": index + 1, "sample_id": sample_ids[index % len(sample_ids)], "state": "pending"} for index in range(begin, min(begin + 100, row["request_count"]))],
                )
            await self._journal_event(session, row, "run_recorded", at)
        return row

    async def record_dispatch(self, owner, project_id, run_id, ordinal, *, body_bytes):
        """Commit the irreversible send marker and conservative reservations.

        Return is NOT execution permission. A failed/ambiguous commit must never
        be followed by send. No release/retry/requeue path exists for this ordinal.
        """
        _positive_int(ordinal, 10_000)
        _positive_int(body_bytes, 262_144)
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            at = self._time()
            active = (await session.execute(select(t.dispatches.c.lease_expires_at_ms).where(t.dispatches.c.run_id == run_id, t.dispatches.c.state == "dispatched"))).scalars().all()
            attempt = (await session.execute(select(t.dispatches.c.state, t.dispatches.c.sample_id).where(t.dispatches.c.run_id == run_id, t.dispatches.c.ordinal == ordinal))).mappings().first()
            reserve = run["max_response_bytes"] + 1
            if (
                run["status"] != "recording"
                or at >= run["deadline_ms"]
                or any(expiry <= at for expiry in active)
                or len(active) >= run["concurrency"]
                or attempt is None
                or attempt["state"] != "pending"
                or run["reserved_body_bytes"] + body_bytes > run["max_total_body_bytes"]
                or run["reserved_response_bytes"] + reserve > run["max_total_response_bytes"]
            ):
                raise Conflict
            token = uuid4().hex
            expiry = min(at + run["timeout_ms"] + run["lease_grace_ms"], run["deadline_ms"])
            ticket = DispatchTicket(run_id, ordinal, attempt["sample_id"], expiry, token)
            await session.execute(
                update(t.dispatches)
                .where(t.dispatches.c.run_id == run_id, t.dispatches.c.ordinal == ordinal)
                .values(state="dispatched", ticket_hash=hashlib.sha256(token.encode()).hexdigest(), dispatched_at_ms=at, lease_expires_at_ms=expiry)
            )
            await session.execute(
                update(t.dispatch_runs)
                .where(t.dispatch_runs.c.id == run_id)
                .values(reserved_body_bytes=run["reserved_body_bytes"] + body_bytes, reserved_response_bytes=run["reserved_response_bytes"] + reserve, revision=run["revision"] + 1)
            )
            await self._journal_event(session, run, "dispatch_recorded", at, ordinal=ordinal)
        return ticket

    @staticmethod
    async def _interrupt(session, run, at, reason):
        # A reservation could already have reached the target. NEVER reset it to
        # pending, and never make its slot available for continuing the same run.
        await session.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.state == "dispatched").values(state="delivery_unknown", kind="delivery_unknown"))
        await session.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.state == "pending").values(state="not_dispatched"))
        await session.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == run["id"]).values(status="interrupted", finished_at_ms=at, stop_reason=reason, revision=run["revision"] + 1))
        await DispatchJournalRepository._journal_event(session, run, "run_interrupted", at)

    async def record_observation(self, owner, project_id, run_id, ticket: DispatchTicket, observation: TechnicalObservation):
        """Append technical metadata once, fenced by the unexpired dispatch token.

        No Q/A/gold/raw response is accepted here. recording_finished means only
        metadata recording is done, NEVER quality PASS or complete evidence.
        """
        if not isinstance(ticket, DispatchTicket) or ticket.run_id != run_id or type(ticket.token) is not str:
            raise Conflict
        _positive_int(ticket.ordinal, 10_000)
        observation = TechnicalObservation.model_validate(observation.model_dump())
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            at = self._time()
            attempt = (await session.execute(select(t.dispatches).where(t.dispatches.c.run_id == run_id, t.dispatches.c.ordinal == ticket.ordinal))).mappings().first()
            if (
                run["status"] != "recording"
                or at >= run["deadline_ms"]
                or attempt is None
                or attempt["state"] != "dispatched"
                or at >= attempt["lease_expires_at_ms"]
                or ticket.expires_at_ms != attempt["lease_expires_at_ms"]
                or ticket.sample_id != attempt["sample_id"]
                or not hmac.compare_digest(hashlib.sha256(ticket.token.encode()).hexdigest(), attempt["ticket_hash"])
                or observation.body_bytes > run["max_response_bytes"] + (observation.kind in {"response_limit", "delivery_unknown"})
            ):
                raise Conflict
            unknown = observation.kind == "delivery_unknown"
            await session.execute(update(t.dispatches).where(t.dispatches.c.run_id == run_id, t.dispatches.c.ordinal == ticket.ordinal).values(state="delivery_unknown" if unknown else "observed", **observation.model_dump()))
            await session.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == run_id).values(revision=run["revision"] + 1))
            await self._journal_event(session, run, "observation_recorded", at, ordinal=ticket.ordinal)
            if unknown:
                await self._interrupt(session, run, at, "delivery_unknown")
            else:
                remaining = (await session.execute(select(func.count()).select_from(t.dispatches).where(t.dispatches.c.run_id == run_id, t.dispatches.c.state.in_(["pending", "dispatched"])))).scalar_one()
                if not remaining:
                    await session.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == run_id).values(status="recording_finished", finished_at_ms=at))
                    await self._journal_event(session, run, "run_recording_finished", at)

    async def interrupt_expired(self, owner, project_id, run_id):
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            at = self._time()
            if run["status"] != "recording":
                return False
            expired = (await session.execute(select(t.dispatches.c.ordinal).where(t.dispatches.c.run_id == run_id, t.dispatches.c.state == "dispatched", t.dispatches.c.lease_expires_at_ms <= at).limit(1))).first()
            if at < run["deadline_ms"] and expired is None:
                return False
            await self._interrupt(session, run, at, "deadline_expired" if at >= run["deadline_ms"] else "lease_expired")
        return True

    async def interrupt_journal(self, owner, project_id, run_id):
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            if run["status"] == "recording":
                await self._interrupt(session, run, self._time(), "cancelled")
        return await self.get_journal(owner, project_id, run_id)

    async def get_journal(self, owner, project_id, run_id):
        async with self.sf() as session:
            return await self._journal(session, owner, project_id, run_id)

    async def list_dispatches(self, owner, project_id, run_id, *, offset=0, limit=100):
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise ValueError("Invalid journal page")
        _positive_int(limit, 200)
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            columns = [column for column in t.dispatches.c if column.name != "ticket_hash"]
            rows = await session.execute(select(*columns).where(t.dispatches.c.run_id == run_id).order_by(t.dispatches.c.ordinal).offset(offset).limit(limit))
            return [dict(row) for row in rows.mappings()]

    async def journal_audit(self, owner, project_id, run_id):
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            rows = await session.execute(select(t.dispatch_audit).where(t.dispatch_audit.c.run_id == run_id).order_by(t.dispatch_audit.c.sequence))
            return [dict(row) for row in rows.mappings()]
