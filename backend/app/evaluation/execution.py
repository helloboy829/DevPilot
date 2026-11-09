"""Explicitly admitted, bounded QA JSON execution. No retries or model judging.

A DB-confirmed dispatch marker precedes each application-level send, not a claim
of network exactly-once. Lost/expired workers are NEVER reclaimed; held global
reservations survive their deadline until the original worker has drained.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_versions import FrozenRequest
from pydantic import Field, field_validator
from sqlalchemy import func, insert, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.dispatch_journal import JournalLimits, _positive_int
from app.evaluation.plan_repository import _preflight, _verified_inputs
from app.evaluation.plans import PlanCreate
from app.evaluation.qa_attempts import AttemptLimits, collect_json_attempt
from app.evaluation.qa_evidence import EvidenceRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


class ExecutionPolicy(StrictDTO):
    enabled: bool = False
    max_active_runs: int = Field(default=2, ge=1, le=32)
    max_reserved_concurrency: int = Field(default=8, ge=1, le=64)
    max_response_bytes: int = Field(default=65_536, ge=1, le=1_048_576)
    max_reserved_body_bytes: int = Field(default=67_108_864, ge=1, le=67_108_864)
    max_reserved_response_bytes: int = Field(default=67_108_864, ge=2, le=67_108_864)


class ExecutionCreate(StrictDTO):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]
    target_authorized: Literal[True]

    @field_validator("confirmed", "target_authorized", mode="before")
    @classmethod
    def human_consent(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


@dataclass(frozen=True, slots=True)
class ExecutionClaim:
    execution_id: str
    owner: str
    project_id: str
    token: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Prepared:
    plan: dict
    snapshot: tuple = field(repr=False)
    version: dict = field(repr=False)
    request: FrozenRequest = field(repr=False)
    inputs: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _Work:
    plan: dict
    request: FrozenRequest = field(repr=False)
    inputs: tuple[str, ...] = field(repr=False)


class ExecutionRepository(EvidenceRepository):
    _metadata = tuple(c for c in t.executions.c if c.name not in {"claim_hash"})

    def __init__(self, sf, *, policy=None, config_getter=None, **kwargs):
        super().__init__(sf, **kwargs)
        self.policy = ExecutionPolicy.model_validate((policy or ExecutionPolicy()).model_dump())
        self.config_getter = config_getter

    async def initialize(self):
        # Idempotent across Gateway processes, no select-then-insert race.
        async with self._transaction() as session:
            dialect = session.bind.dialect.name
            if dialect == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            elif dialect == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            else:
                raise Conflict
            await session.execute(dialect_insert(t.execution_guard).values(id=1).on_conflict_do_nothing(index_elements=["id"]))

    async def _guard(self, session, *, check_policy=True):
        row = (await session.execute(update(t.execution_guard).where(t.execution_guard.c.id == 1).values(id=1).returning(t.execution_guard))).mappings().first()
        if row is None:
            raise Conflict
        if not check_policy:
            return
        expected = fingerprint(self.policy.model_dump())
        if row["policy_hash"] != expected:
            held = (await session.execute(select(func.count()).select_from(t.executions).where(t.executions.c.reservation_held.is_(True)))).scalar_one()
            if held:
                raise Conflict
            await session.execute(update(t.execution_guard).where(t.execution_guard.c.id == 1).values(policy_hash=expected))

    async def _row(self, session, owner, project, key):
        await self._project(session, owner, project)
        row = (await session.execute(select(t.executions).where(t.executions.c.id == key, t.executions.c.project_id == project, t.executions.c.owner_id == owner))).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    @staticmethod
    def _execution_public(row):
        return {key: value for key, value in row.items() if key != "claim_hash"}

    async def _execution_snapshot(self, session, owner, project, plan_id):
        plan = await self._plan(session, owner, project, plan_id)
        dataset = await self._dataset(session, owner, project, plan["dataset_id"])
        version = await self._request_version(session, owner, project, plan["request_version_id"], protected=True)
        rows = (
            (
                await session.execute(
                    select(t.samples.c.sample_id, t.samples.c.input, t.samples.c.source_ref, t.samples.c.slice_tag, t.references.c.expected)
                    .outerjoin(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                    .where(t.samples.c.dataset_id == dataset["id"])
                    .order_by(t.samples.c.sample_id)
                    .limit(501)
                )
            )
            .mappings()
            .all()
        )
        return plan, dataset, version, [dict(row) for row in rows]

    async def _prepare(self, owner, project, plan_id):
        # Reads end BEFORE crypto/preflight. No global/run lock held over I/O or crypto.
        async with self.sf() as session:
            snapshot = await self._execution_snapshot(session, owner, project, plan_id)
        plan, dataset, version, rows = snapshot
        definition = plan["definition"]
        if dataset["status"] != "frozen" or dataset["revision"] != definition["dataset_revision"] or dataset["content_hash"] != definition["dataset_hash"] or version["protected_hash"] != definition["request_protected_hash"]:
            raise Conflict
        inputs = await asyncio.to_thread(_verified_inputs, dataset, rows)

        def open_request():
            if hashlib.sha256(version["encrypted_payload"].encode()).hexdigest() != version["protected_hash"]:
                raise RequestProtectionError("Protected request integrity check failed")
            frozen = self._protection().open(version["encrypted_payload"], self._binding(owner, version))
            if frozen.template.to_dict() != version["request_template"] or frozen.template.fingerprint != definition["request_template_fingerprint"] or version["scope"] != "request_definition_only":
                raise Conflict
            # Ensure evidence storage is available BEFORE any admitted dispatch.
            self._evidence_protection()
            return frozen

        frozen = await asyncio.to_thread(open_request)
        settings = PlanCreate.model_validate({**{k: definition[k] for k in PlanCreate.model_fields if k != "confirmed"}, "confirmed": True})
        if await asyncio.to_thread(_preflight, frozen, inputs, settings) != definition["preflight"]:
            raise Conflict
        config = self.config_getter() if self.config_getter else None
        if urlsplit(frozen.url).hostname.lower() not in getattr(config, "evaluation_http", {}).get("allowed_hosts", []):
            raise Conflict
        return _Prepared(plan, snapshot, version, frozen, inputs)

    async def _recheck(self, session, owner, project, prepared):
        current = await self._execution_snapshot(session, owner, project, prepared.plan["id"])
        if current != prepared.snapshot:
            raise Conflict
        await self._request_event(session, owner, prepared.version, "request_version_opened")

    async def admit(self, owner, project, key, payload):
        payload = ExecutionCreate.model_validate(payload.model_dump())
        if not isinstance(key, str) or len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Invalid execution identifier")
        # Existing receipts remain readable even when new execution is disabled.
        async with self.sf() as session:
            await self._project(session, owner, project)
            existing = (await session.execute(select(t.executions).where(t.executions.c.id == key))).mappings().first()
            if existing is not None:
                return await self._existing(session, existing, owner, project, payload)
        if not self.policy.enabled:
            raise Conflict
        prepared = await self._prepare(owner, project, payload.plan_id)
        if not hmac.compare_digest(payload.plan_hash, prepared.plan["definition_hash"]):
            raise Conflict
        limits = prepared.plan["definition"]["limits"]
        reserved = {
            "reserved_concurrency": limits["concurrency"],
            "reserved_body_bytes": prepared.plan["definition"]["preflight"]["total_body_bytes"],
            "reserved_response_bytes": limits["request_count"] * (self.policy.max_response_bytes + 1),
        }
        async with self._transaction() as session:
            await self._guard(session)
            existing = (await session.execute(select(t.executions).where(t.executions.c.id == key))).mappings().first()
            if existing is not None:
                return await self._existing(session, existing, owner, project, payload)
            await self._recheck(session, owner, project, prepared)
            held = (await session.execute(select(t.executions).where(t.executions.c.reservation_held.is_(True)))).mappings().all()
            if len(held) >= self.policy.max_active_runs or any(sum(row[name] for row in held) + value > getattr(self.policy, "max_" + name) for name, value in reserved.items()):
                raise Conflict
            journal = await self._record_run(session, owner, project, payload.plan_id, payload.plan_hash, JournalLimits(max_response_bytes=self.policy.max_response_bytes, max_total_response_bytes=reserved["reserved_response_bytes"]))
            row = {
                "id": key,
                "owner_id": owner,
                "project_id": project,
                "run_id": journal["id"],
                "plan_hash": payload.plan_hash,
                "scope": "admitted_qa_json",
                "state": "queued",
                "reservation_held": True,
                "claim_hash": None,
                **reserved,
                "created_at_ms": journal["started_at_ms"],
                "deadline_ms": journal["deadline_ms"],
                "finished_at_ms": None,
            }
            await session.execute(insert(t.executions).values(**row))
            await self._journal_event(session, journal, "execution_admitted", self._time())
        return self._execution_public(row)

    async def _existing(self, session, row, owner, project, payload):
        if row["owner_id"] != owner or row["project_id"] != project:
            raise Conflict
        journal = await self._journal(session, owner, project, row["run_id"])
        if journal["plan_id"] != payload.plan_id or row["plan_hash"] != payload.plan_hash:
            raise Conflict
        return self._execution_public(row)

    async def list_executions(self, owner, project):
        async with self.sf() as session:
            await self._project(session, owner, project)
            rows = await session.execute(select(*self._metadata).where(t.executions.c.owner_id == owner, t.executions.c.project_id == project).order_by(t.executions.c.created_at_ms.desc(), t.executions.c.id).limit(200))
            return [dict(row) for row in rows.mappings()]

    async def get_execution(self, owner, project, key):
        async with self.sf() as session:
            # Metadata read must not fetch a claim secret/hash.
            await self._project(session, owner, project)
            row = (await session.execute(select(*self._metadata).where(t.executions.c.id == key, t.executions.c.owner_id == owner, t.executions.c.project_id == project))).mappings().first()
            if row is None:
                raise NotFound
            return dict(row)

    async def claim(self):
        if not self.policy.enabled:
            return None
        await self.expire()
        claim = None
        async with self._transaction() as session:
            await self._guard(session)
            row = (
                (
                    await session.execute(
                        select(t.executions).where(t.executions.c.state == "queued", t.executions.c.reservation_held.is_(True), t.executions.c.deadline_ms > self._time()).order_by(t.executions.c.created_at_ms, t.executions.c.id).limit(1)
                    )
                )
                .mappings()
                .first()
            )
            if row is not None:
                token = uuid4().hex + uuid4().hex
                await session.execute(update(t.executions).where(t.executions.c.id == row["id"]).values(state="running", claim_hash=hashlib.sha256(token.encode()).hexdigest()))
                run = await self._journal(session, row["owner_id"], row["project_id"], row["run_id"], lock=True)
                await self._journal_event(session, run, "execution_claimed", self._time())
                claim = ExecutionClaim(row["id"], row["owner_id"], row["project_id"], token)
        return claim

    async def _fenced(self, session, claim, *, active=True):
        if not isinstance(claim, ExecutionClaim):
            raise Conflict
        row = await self._row(session, claim.owner, claim.project_id, claim.execution_id)
        if not row["claim_hash"] or not hmac.compare_digest(row["claim_hash"], hashlib.sha256(claim.token.encode()).hexdigest()) or not row["reservation_held"]:
            raise Conflict
        if active and (row["state"] != "running" or self._time() >= row["deadline_ms"]):
            raise Conflict
        return row

    async def load_claim(self, claim):
        row = await self.get_execution(claim.owner, claim.project_id, claim.execution_id)
        run = await self.get_journal(claim.owner, claim.project_id, row["run_id"])
        prepared = await self._prepare(claim.owner, claim.project_id, run["plan_id"])
        if prepared.plan["definition_hash"] != row["plan_hash"]:
            raise Conflict
        async with self._transaction() as session:
            await self._guard(session)
            await self._fenced(session, claim)
            await self._recheck(session, claim.owner, claim.project_id, prepared)
        return _Work(prepared.plan, prepared.request, prepared.inputs), run

    async def reserve_attempt(self, claim, ordinal, *, body_bytes):
        _positive_int(ordinal, 10_000)
        _positive_int(body_bytes, 262_144)
        async with self._transaction() as session:
            await self._guard(session)
            row = await self._fenced(session, claim)
            ticket = await self._record_dispatch(session, claim.owner, claim.project_id, row["run_id"], ordinal, body_bytes=body_bytes)
        return ticket

    async def cancel(self, owner, project, key):
        async with self._transaction() as session:
            await self._guard(session, check_policy=False)
            row = await self._row(session, owner, project, key)
            if row["state"] in {"queued", "running"}:
                queued = row["state"] == "queued"
                run = await self._journal(session, owner, project, row["run_id"], lock=True)
                await self._interrupt(session, run, self._time(), "execution_cancelled")
                await session.execute(update(t.executions).where(t.executions.c.id == key).values(state="interrupted" if queued else "cancel_requested", reservation_held=not queued, finished_at_ms=self._time() if queued else None))
                await self._journal_event(session, run, "execution_cancelled", self._time())
        return await self.get_execution(owner, project, key)

    async def expire(self):
        async with self._transaction() as session:
            await self._guard(session, check_policy=False)
            rows = (await session.execute(select(t.executions).where(t.executions.c.deadline_ms <= self._time(), t.executions.c.state.in_(["queued", "running", "cancel_requested"])))).mappings().all()
            for row in rows:
                run = await self._journal(session, row["owner_id"], row["project_id"], row["run_id"], lock=True)
                await self._interrupt(session, run, self._time(), "execution_expired")
                await session.execute(update(t.executions).where(t.executions.c.id == row["id"]).values(state="interrupted", reservation_held=row["state"] != "queued", finished_at_ms=self._time()))
                await self._journal_event(session, run, "execution_expired", self._time())

    async def finish(self, claim, *, completed):
        # Called ONLY by the original worker AFTER all its network tasks drain.
        async with self._transaction() as session:
            await self._guard(session, check_policy=False)
            row = await self._fenced(session, claim, active=False)
            run = await self._journal(session, claim.owner, claim.project_id, row["run_id"], lock=True)
            good = completed and row["state"] == "running" and run["status"] == "recording_finished" and self._time() < row["deadline_ms"]
            if not good and run["status"] == "recording":
                await self._interrupt(session, run, self._time(), "worker_stopped")
            await session.execute(update(t.executions).where(t.executions.c.id == row["id"]).values(state="collected" if good else "interrupted", reservation_held=False, finished_at_ms=self._time()))
            await self._journal_event(session, run, "execution_drained", self._time())


class _RunStopped(Exception):
    pass


async def _drained_database(awaitable):
    """Drain database reads and writes before cancellation or finalization.

    Cancellation still prevents the caller's next send. First drain the private
    operation task, even if its acknowledgement is uncertain. A cancelled read
    can also leave an aiosqlite cursor holding a pooled connection's lock.
    """
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        await asyncio.gather(task, return_exceptions=True)
        raise


class QAExecutionWorker:
    def __init__(self, repository, config_getter):
        self.repo, self.config_getter = repository, config_getter

    async def run_once(self):
        claim = None
        tasks = []
        group = None
        completed = False

        async def claim_and_remember():
            nonlocal claim
            claim = await self.repo.claim()

        try:
            await _drained_database(claim_and_remember())
            if claim is None:
                return False
            prepared, run = await _drained_database(self.repo.load_claim(claim))
            binding = QAJSONBinding.from_dict(prepared.plan["definition"]["binding"])
            ordinals = iter(range(1, run["request_count"] + 1))
            stopped = asyncio.Event()

            async def consume():
                try:
                    await consume_available()
                except BaseException:
                    stopped.set()
                    raise

            async def consume_available():
                for ordinal in ordinals:
                    if stopped.is_set():
                        raise _RunStopped
                    spec = await asyncio.to_thread(binding.render, prepared.request, prepared.inputs[(ordinal - 1) % len(prepared.inputs)])
                    ticket = await _drained_database(self.repo.reserve_attempt(claim, ordinal, body_bytes=len(spec.body.encode("utf-8"))))
                    remaining = min(run["timeout_ms"], run["deadline_ms"] - self.repo._time())
                    if remaining < 100 or stopped.is_set():
                        raise _RunStopped
                    observation = await collect_json_attempt(spec, binding, self.config_getter(), AttemptLimits(timeout_ms=remaining, max_response_bytes=run["max_response_bytes"]))
                    # Fence new sends immediately, not after the unknown-delivery
                    # observation's durable write finishes. Already sent tasks
                    # still drain; their unknown outcomes are never retried.
                    if observation.kind == "delivery_unknown":
                        stopped.set()
                    await _drained_database(self.repo.record_attempt(claim.owner, claim.project_id, run["id"], ticket, observation))
                    if observation.kind == "delivery_unknown":
                        raise _RunStopped

            async def monitor():
                while True:
                    await asyncio.sleep(0.2)
                    row = await _drained_database(self.repo.get_execution(claim.owner, claim.project_id, claim.execution_id))
                    if row["state"] != "running" or self.repo._time() >= row["deadline_ms"]:
                        raise _RunStopped

            async with asyncio.timeout(max(0.001, (run["deadline_ms"] - self.repo._time()) / 1000)):
                tasks = [asyncio.create_task(consume()) for _ in range(run["concurrency"])]
                monitor_task = asyncio.create_task(monitor())
                tasks.append(monitor_task)
                group = asyncio.gather(*tasks[:-1])
                await asyncio.wait([group, monitor_task], return_when=asyncio.FIRST_COMPLETED)
                if monitor_task.done():
                    monitor_task.result()
                await group
                completed = True
        except asyncio.CancelledError:
            raise
        except Exception:
            # No request text, target URL, output, gold or exception payload in logs.
            completed = False
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            if group is not None:
                await asyncio.gather(group, return_exceptions=True)
            if claim is not None:
                await _drained_database(self.repo.finish(claim, completed=completed))
        return True

    async def serve(self):
        import logging

        logger = logging.getLogger(__name__)
        while True:
            try:
                if not await self.run_once():
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("QA execution worker stopped a cycle; details suppressed, no retry of claimed executions")
                await asyncio.sleep(1)
