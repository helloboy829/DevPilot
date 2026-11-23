"""Owner-scoped durable performance dispatch ledger; contains no transport code."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import secrets
import time
from collections import Counter
from collections.abc import Mapping
from datetime import datetime
from uuid import uuid4

from sqlalchemy import case, func, insert, or_, select, update

from app.evaluation import tables as t
from app.evaluation.performance_metrics import summarize_performance_dispatches
from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceProfile, build_case_manifest
from app.evaluation.qa_artifact_store import ResponseArtifactStore
from app.evaluation.qa_evidence import EvidenceAccessCreate
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound, now
from app.evaluation.request_protection import RequestProtectionError

_TERMINAL = {"succeeded", "failed", "timeout", "unknown", "not_dispatched"}
_RUN_STATES = ("pending", "dispatched", "succeeded", "failed", "timeout", "unknown", "not_dispatched")


def _bounded_int(value, *, minimum=0, maximum=1_048_576):
    if type(value) is not int or not minimum <= value <= maximum:
        raise Conflict
    return value


def _hash_or_none(value):
    if value is None:
        return None
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise Conflict
    return value


class PerformanceRunRepository(EvaluationRepository):
    _MAX_RUN_POPULATION = 11_000
    _MAX_CAPTURED_RESPONSE_BYTES = 1_048_576
    _MAX_OBSERVED_RESPONSE_BYTES = 10_000_001

    def __init__(self, sf, *, response_artifact_store=None):
        super().__init__(sf)
        self.response_artifact_store = response_artifact_store

    def _response_artifact_store(self):
        return self.response_artifact_store if self.response_artifact_store is not None else ResponseArtifactStore.from_environment()

    @classmethod
    def _capture_response(cls, *, status, body, response_status, response_bytes, response_hash, content_type, content_encoding):
        body_was_provided = body is not None
        if body is None:
            body = b""
        if (
            type(body) is not bytes
            or len(body) > cls._MAX_CAPTURED_RESPONSE_BYTES
            or (status is not None and type(status) is not str)
            or (content_type is not None and (type(content_type) is not str or not 1 <= len(content_type) <= 127))
            or (content_encoding is not None and (type(content_encoding) is not str or content_encoding not in {"identity", "gzip", "deflate", "br", "zstd", "compress", "other"}))
        ):
            raise Conflict
        if status is None:
            status = "complete" if body_was_provided else ("policy_skipped" if response_status is not None or response_bytes not in (None, 0) or response_hash is not None else "not_received")
        if status in {"not_received", "policy_skipped"}:
            if body:
                raise Conflict
            observed = response_bytes or 0
            if type(observed) is not int or not 0 <= observed <= cls._MAX_OBSERVED_RESPONSE_BYTES:
                raise Conflict
            if status == "not_received" and (response_status is not None or response_hash is not None or observed != 0 or content_type is not None or content_encoding is not None):
                raise Conflict
            if status == "policy_skipped" and response_status is None:
                raise Conflict
            return status, body, "none", None, observed, content_type, content_encoding
        if status not in {"complete", "partial", "truncated"}:
            raise Conflict
        digest = hashlib.sha256(body).hexdigest()
        observed = len(body) if response_bytes is None else response_bytes
        scope = "full" if status == "complete" else "prefix"
        if (
            type(response_status) is not int
            or not 100 <= response_status <= 599
            or type(observed) is not int
            or not len(body) <= observed <= cls._MAX_OBSERVED_RESPONSE_BYTES
            or (status == "complete" and observed != len(body))
            or (status == "truncated" and observed <= len(body))
            or (status == "complete" and response_hash not in (None, digest))
        ):
            raise Conflict
        return status, body, scope, digest, observed, content_type, content_encoding

    async def create_run(self, owner, project_id, scenario_id, expected_scenario_hash, *, confirmed, run_id=None):
        if confirmed is not True or type(expected_scenario_hash) is not str or len(expected_scenario_hash) != 64:
            raise Conflict
        if run_id is None:
            run_id = uuid4().hex
        elif type(run_id) is not str or len(run_id) != 32 or any(char not in "0123456789abcdef" for char in run_id):
            raise Conflict
        created_at = now()
        async with self.sf.begin() as session:
            await self._project(session, owner, project_id)
            scenario_row = (
                (
                    await session.execute(
                        select(t.performance_scenarios).where(
                            t.performance_scenarios.c.project_id == project_id,
                            t.performance_scenarios.c.id == scenario_id,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if scenario_row is None:
                raise NotFound
            scenario = PerformanceScenarioRepository._public(dict(scenario_row))
            if not hmac.compare_digest(scenario["definition_hash"], expected_scenario_hash):
                raise Conflict
            definition = scenario["definition"]
            try:
                profile = PerformanceProfile.model_validate(definition["profile"])
                manifest = definition["manifest"]
                expected_manifest = build_case_manifest(
                    definition["case_order"],
                    warmup_count=profile.warmup_request_count,
                    measured_count=profile.measured_request_count,
                )
                if manifest != expected_manifest or not 1 <= len(manifest) <= self._MAX_RUN_POPULATION:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise Conflict from None
            profile_hash = fingerprint(profile.model_dump(mode="json"))
            manifest_hash = fingerprint(manifest)
            row = {
                "id": run_id,
                "project_id": project_id,
                "scenario_id": scenario_id,
                "owner_id": owner,
                "scenario_hash": scenario["definition_hash"],
                "profile_hash": profile_hash,
                "manifest_hash": manifest_hash,
                "population_count": len(manifest),
                "status": "created",
                "window_start_ns": None,
                "window_end_ns": None,
                "created_at": created_at,
                "finished_at": None,
            }
            await session.execute(insert(t.performance_runs).values(**row))
            dispatches = [
                {
                    "id": uuid4().hex,
                    "project_id": project_id,
                    "run_id": run_id,
                    **entry,
                    "dispatch_id": uuid4().hex,
                    "state": "pending",
                    "lease_worker_id": None,
                    "lease_epoch": 0,
                    "lease_expires_at_ms": None,
                    "created_at": created_at,
                }
                for entry in manifest
            ]
            await session.execute(insert(t.performance_dispatches), dispatches)
            await self._append_audit(
                session,
                project_id,
                run_id,
                owner,
                "run_created",
                {"scenario_hash": row["scenario_hash"], "manifest_hash": manifest_hash, "population_count": len(manifest)},
            )
        return await self.get_run(owner, project_id, run_id)

    async def _run(self, session, owner, project_id, run_id, *, lock=False):
        statement = select(t.performance_runs).where(
            t.performance_runs.c.project_id == project_id,
            t.performance_runs.c.id == run_id,
            t.performance_runs.c.owner_id == owner,
        )
        if lock:
            statement = statement.with_for_update()
        row = (await session.execute(statement)).mappings().first()
        if row is None:
            raise NotFound
        return dict(row)

    async def _append_audit(self, session, project_id, run_id, actor, action, details):
        sequence = (await session.execute(select(func.coalesce(func.max(t.performance_run_audit.c.sequence), 0) + 1).where(t.performance_run_audit.c.run_id == run_id))).scalar_one()
        await session.execute(
            insert(t.performance_run_audit).values(
                project_id=project_id,
                run_id=run_id,
                sequence=sequence,
                actor=actor,
                action=action,
                details=details,
                created_at=now(),
            )
        )

    @staticmethod
    def _worker_id(value):
        if type(value) is not str or not 1 <= len(value) <= 64:
            raise Conflict
        return value

    @staticmethod
    def _lease_epoch(value):
        if type(value) is not int or isinstance(value, bool) or not 1 <= value <= 2_147_483_647:
            raise Conflict
        return value

    async def claim_dispatch(self, owner, project_id, run_id, ordinal, *, worker_id, lease_expires_at_ms):
        """Atomically lease one pending ordinal; claiming never means transport started."""
        _bounded_int(ordinal, maximum=10_999)
        worker_id = self._worker_id(worker_id)
        _bounded_int(lease_expires_at_ms, minimum=1, maximum=2_534_023_007_99000)
        now_ms = int(time.time() * 1000)
        if lease_expires_at_ms <= now_ms:
            raise Conflict
        async with self.sf.begin() as session:
            # Do the conditional write before any read in this transaction.  This
            # is a real serialization point on PostgreSQL and on SQLite, where
            # SELECT ... FOR UPDATE is only advisory.  A concurrent claimant can
            # therefore never both observe epoch N and publish epoch N+1.
            eligible = or_(
                t.performance_dispatches.c.lease_worker_id.is_(None),
                t.performance_dispatches.c.lease_expires_at_ms.is_(None),
                t.performance_dispatches.c.lease_expires_at_ms <= now_ms,
                t.performance_dispatches.c.lease_worker_id == worker_id,
            )
            active_same_worker = (t.performance_dispatches.c.lease_worker_id == worker_id) & (t.performance_dispatches.c.lease_expires_at_ms > now_ms)
            changed = await session.execute(
                update(t.performance_dispatches)
                .where(
                    t.performance_dispatches.c.project_id == project_id,
                    t.performance_dispatches.c.run_id == run_id,
                    t.performance_dispatches.c.ordinal == ordinal,
                    t.performance_dispatches.c.state == "pending",
                    eligible,
                )
                .values(
                    lease_worker_id=worker_id,
                    lease_epoch=case(
                        (active_same_worker, t.performance_dispatches.c.lease_epoch),
                        else_=t.performance_dispatches.c.lease_epoch + 1,
                    ),
                    lease_expires_at_ms=lease_expires_at_ms,
                )
                .returning(*t.performance_dispatches.c),
            )
            dispatch = changed.mappings().first()
            if dispatch is None:
                raise Conflict
            run = await self._run(session, owner, project_id, run_id, lock=True)
            if run["status"] not in {"created", "running"}:
                raise Conflict
            # The returned row contains the database-computed epoch; do not
            # reconstruct it from the caller's snapshot.
            epoch = dispatch["lease_epoch"]
            await self._append_audit(
                session,
                project_id,
                run_id,
                owner,
                "dispatch_claimed",
                {"ordinal": ordinal, "worker_id": worker_id, "lease_epoch": epoch},
            )
            return {
                "run_id": run_id,
                "ordinal": ordinal,
                "dispatch_id": dispatch["dispatch_id"],
                "worker_id": worker_id,
                "lease_epoch": epoch,
                "lease_expires_at_ms": lease_expires_at_ms,
            }

    async def acknowledge_dispatch(self, owner, project_id, run_id, ordinal, *, send_started_ns=None, worker_id=None, lease_epoch=None, request_bytes=None, request_hash=None):
        """Reserve a stable ticket; transport starts only in ``start_dispatch``."""
        if send_started_ns is not None:
            if worker_id is not None or lease_epoch is not None:
                raise Conflict
            legacy_worker = ("legacy-" + owner)[:64]
            lease = await self.claim_dispatch(owner, project_id, run_id, ordinal, worker_id=legacy_worker, lease_expires_at_ms=int(time.time() * 1000) + 300_000)
            ticket = await self.acknowledge_dispatch(owner, project_id, run_id, ordinal, worker_id=legacy_worker, lease_epoch=lease["lease_epoch"], request_bytes=request_bytes, request_hash=request_hash)
            return await self.start_dispatch(owner, project_id, run_id, ticket, worker_id=legacy_worker, lease_epoch=lease["lease_epoch"], send_started_ns=send_started_ns)
        worker_id = self._worker_id(worker_id)
        lease_epoch = self._lease_epoch(lease_epoch)
        _bounded_int(ordinal, maximum=10_999)
        _bounded_int(request_bytes, maximum=1_048_576) if request_bytes is not None else None
        request_hash = _hash_or_none(request_hash)
        now_ms = int(time.time() * 1000)
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            dispatch = (
                (
                    await session.execute(
                        select(t.performance_dispatches).where(t.performance_dispatches.c.project_id == project_id, t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.ordinal == ordinal).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if run["status"] not in {"created", "running"} or dispatch is None or dispatch["state"] != "pending":
                raise Conflict
            if dispatch["lease_worker_id"] != worker_id or dispatch["lease_epoch"] != lease_epoch or dispatch["lease_expires_at_ms"] is None or dispatch["lease_expires_at_ms"] <= now_ms:
                raise Conflict
            artifact = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.project_id == project_id, t.performance_response_artifacts.c.run_id == run_id, t.performance_response_artifacts.c.ordinal == ordinal)
                    )
                )
                .mappings()
                .first()
            )
            if artifact is not None:
                if artifact["dispatch_id"] != dispatch["dispatch_id"] or dispatch["request_bytes"] != request_bytes or dispatch["request_hash"] != request_hash:
                    raise Conflict
                return {"run_id": run_id, "ordinal": ordinal, "dispatch_id": dispatch["dispatch_id"], "response_artifact_id": artifact["id"]}
            response_artifact_id = uuid4().hex
            at_ms = int(time.time() * 1000)
            await session.execute(
                insert(t.performance_response_artifacts).values(
                    id=response_artifact_id,
                    project_id=project_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    dispatch_id=dispatch["dispatch_id"],
                    status="pending",
                    hash_scope="none",
                    captured_bytes=0,
                    observed_bytes=0,
                    created_at_ms=at_ms,
                    updated_at_ms=at_ms,
                )
            )
            changed = await session.execute(
                update(t.performance_dispatches)
                .where(t.performance_dispatches.c.id == dispatch["id"], t.performance_dispatches.c.state == "pending", t.performance_dispatches.c.lease_worker_id == worker_id, t.performance_dispatches.c.lease_epoch == lease_epoch)
                .values(request_bytes=request_bytes, request_hash=request_hash)
            )
            if changed.rowcount != 1:
                raise Conflict
            await self._append_audit(session, project_id, run_id, owner, "dispatch_acknowledged", {"ordinal": ordinal, "phase": dispatch["phase"], "lease_epoch": lease_epoch})
            return {"run_id": run_id, "ordinal": ordinal, "dispatch_id": dispatch["dispatch_id"], "response_artifact_id": response_artifact_id}

    async def start_dispatch(self, owner, project_id, run_id, ticket, *, worker_id, lease_epoch, send_started_ns):
        """Cross the one-way transport boundary under the current lease fence."""
        if not isinstance(ticket, Mapping) or set(ticket) != {"run_id", "ordinal", "dispatch_id", "response_artifact_id"} or ticket["run_id"] != run_id:
            raise Conflict
        worker_id = self._worker_id(worker_id)
        lease_epoch = self._lease_epoch(lease_epoch)
        _bounded_int(ticket["ordinal"], maximum=10_999)
        _bounded_int(send_started_ns, maximum=9_223_372_036_854_775_807)
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            dispatch = (
                (
                    await session.execute(
                        select(t.performance_dispatches).where(t.performance_dispatches.c.project_id == project_id, t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.ordinal == ticket["ordinal"]).with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().first()
            if (
                run["status"] not in {"created", "running"}
                or dispatch is None
                or dispatch["dispatch_id"] != ticket["dispatch_id"]
                or dispatch["state"] != "pending"
                or artifact is None
                or artifact["dispatch_id"] != dispatch["dispatch_id"]
                or dispatch["lease_worker_id"] != worker_id
                or dispatch["lease_epoch"] != lease_epoch
                or dispatch["lease_expires_at_ms"] is None
                or dispatch["lease_expires_at_ms"] <= int(time.time() * 1000)
            ):
                raise Conflict
            if run["window_end_ns"] is not None and dispatch["phase"] == "measurement" and send_started_ns >= run["window_end_ns"]:
                raise Conflict
            if dispatch["phase"] == "measurement" and run["window_start_ns"] is not None and send_started_ns < run["window_start_ns"]:
                raise Conflict
            changed = await session.execute(
                update(t.performance_dispatches)
                .where(t.performance_dispatches.c.id == dispatch["id"], t.performance_dispatches.c.state == "pending", t.performance_dispatches.c.lease_epoch == lease_epoch)
                .values(state="dispatched", send_started_ns=send_started_ns)
            )
            if changed.rowcount != 1:
                raise Conflict
            values = {"status": "running"}
            if dispatch["phase"] == "measurement" and run["window_start_ns"] is None:
                values["window_start_ns"] = send_started_ns
            await session.execute(update(t.performance_runs).where(t.performance_runs.c.id == run_id).values(**values))
            await self._append_audit(
                session,
                project_id,
                run_id,
                owner,
                "dispatch_started",
                {"ordinal": ticket["ordinal"], "worker_id": worker_id, "lease_epoch": lease_epoch, "send_started_ns": send_started_ns},
            )
            return {
                "run_id": run_id,
                "ordinal": ticket["ordinal"],
                "dispatch_id": ticket["dispatch_id"],
                "response_artifact_id": ticket["response_artifact_id"],
                "worker_id": worker_id,
                "lease_epoch": lease_epoch,
            }

    async def close_measurement_window(self, owner, project_id, run_id, *, window_end_ns):
        _bounded_int(window_end_ns, maximum=9_223_372_036_854_775_807)
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            if run["status"] != "running" or run["window_start_ns"] is None or run["window_end_ns"] is not None or window_end_ns < run["window_start_ns"]:
                raise Conflict
            pending = (await session.execute(select(t.performance_dispatches.c.ordinal).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.state == "pending").limit(1))).first()
            late = (
                await session.execute(
                    select(t.performance_dispatches.c.ordinal)
                    .where(
                        t.performance_dispatches.c.run_id == run_id,
                        t.performance_dispatches.c.phase == "measurement",
                        t.performance_dispatches.c.send_started_ns >= window_end_ns,
                    )
                    .limit(1)
                )
            ).first()
            if pending is not None or late is not None:
                raise Conflict
            await session.execute(update(t.performance_runs).where(t.performance_runs.c.id == run_id).values(window_end_ns=window_end_ns))
            await self._append_audit(session, project_id, run_id, owner, "measurement_window_closed", {"window_end_ns": window_end_ns})

    async def record_observation(
        self,
        owner,
        project_id,
        ticket: Mapping,
        *,
        state,
        finished_ns,
        elapsed_ms,
        response_status=None,
        response_bytes=None,
        response_hash=None,
        response_body=None,
        response_capture_status=None,
        response_content_type=None,
        response_content_encoding=None,
        evidence_ref=None,
        output_tokens=None,
        token_source=None,
    ):
        if not isinstance(ticket, Mapping) or set(ticket) != {
            "run_id",
            "ordinal",
            "dispatch_id",
            "response_artifact_id",
            "worker_id",
            "lease_epoch",
        }:
            raise Conflict
        run_id, ordinal, dispatch_id = ticket["run_id"], ticket["ordinal"], ticket["dispatch_id"]
        worker_id = self._worker_id(ticket["worker_id"])
        lease_epoch = self._lease_epoch(ticket["lease_epoch"])
        _bounded_int(ordinal, maximum=10_999)
        _bounded_int(finished_ns, maximum=9_223_372_036_854_775_807)
        if state not in {"succeeded", "failed", "timeout", "unknown"}:
            raise Conflict
        if type(elapsed_ms) not in {int, float} or not math.isfinite(elapsed_ms) or elapsed_ms < 0:
            raise Conflict
        response_bytes = _bounded_int(response_bytes, maximum=self._MAX_OBSERVED_RESPONSE_BYTES) if response_bytes is not None else None
        response_status = _bounded_int(response_status, minimum=100, maximum=599) if response_status is not None else None
        response_hash = _hash_or_none(response_hash)
        capture_status, captured_body, hash_scope, body_hash, observed_bytes, content_type, content_encoding = self._capture_response(
            status=response_capture_status,
            body=response_body,
            response_status=response_status,
            response_bytes=response_bytes,
            response_hash=response_hash,
            content_type=response_content_type,
            content_encoding=response_content_encoding,
        )
        if state == "unknown" and capture_status not in {"not_received", "policy_skipped"}:
            raise Conflict
        if evidence_ref is not None and (type(evidence_ref) is not str or not 1 <= len(evidence_ref) <= 128):
            raise Conflict
        if output_tokens is not None:
            _bounded_int(output_tokens, maximum=2_147_483_647)
            if state != "succeeded" or token_source is None:
                raise Conflict
        if token_source is not None and (type(token_source) is not str or not 1 <= len(token_source) <= 40):
            raise Conflict
        artifact_id = None
        binding = None
        artifact_metadata = None
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            dispatch = (await session.execute(select(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.ordinal == ordinal).with_for_update())).mappings().first()
            if (
                run["status"] != "running"
                or dispatch is None
                or dispatch["dispatch_id"] != dispatch_id
                or dispatch["state"] != "dispatched"
                or dispatch["send_started_ns"] is None
                or finished_ns < dispatch["send_started_ns"]
                or dispatch["lease_worker_id"] != worker_id
                or dispatch["lease_epoch"] != lease_epoch
                or dispatch["lease_expires_at_ms"] is None
                or dispatch["lease_expires_at_ms"] <= int(time.time() * 1000)
            ):
                raise Conflict
            artifact = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts).where(
                            t.performance_response_artifacts.c.project_id == project_id,
                            t.performance_response_artifacts.c.run_id == run_id,
                            t.performance_response_artifacts.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .first()
            )
            if artifact is None or artifact["dispatch_id"] != dispatch_id or ("response_artifact_id" in ticket and artifact["id"] != ticket["response_artifact_id"]):
                raise Conflict
            values = {
                "state": state,
                "finished_ns": finished_ns,
                "elapsed_ms": float(elapsed_ms),
                "response_status": response_status,
                "response_bytes": response_bytes if response_bytes is not None else (observed_bytes if state != "unknown" else None),
                "response_hash": response_hash or (body_hash if hash_scope == "full" else None),
                "evidence_ref": evidence_ref,
                "output_tokens": output_tokens,
                "token_source": token_source,
            }
            await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.id == dispatch["id"]).values(**values))
            if state != "unknown":
                at_ms = int(time.time() * 1000)
                artifact_values = {
                    "status": capture_status if capture_status in {"not_received", "policy_skipped"} else "write_unknown",
                    "hash_scope": hash_scope,
                    "response_sha256": (response_hash or body_hash) if hash_scope == "full" else None,
                    "captured_prefix_sha256": body_hash if hash_scope == "prefix" else None,
                    "captured_bytes": len(captured_body),
                    "observed_bytes": observed_bytes,
                    "content_type": content_type,
                    "content_encoding": content_encoding,
                    "updated_at_ms": at_ms,
                }
                await session.execute(update(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == artifact["id"], t.performance_response_artifacts.c.status == "pending").values(**artifact_values))
                if capture_status in {"complete", "partial", "truncated"}:
                    artifact_id = artifact["id"]
                    binding = {
                        "owner_id": owner,
                        "project_id": project_id,
                        "run_id": run_id,
                        "ordinal": ordinal,
                        "dispatch_id": dispatch_id,
                        "scenario_hash": run["scenario_hash"],
                    }
                    artifact_metadata = {
                        "capture_status": capture_status,
                        "hash_scope": hash_scope,
                        "body_sha256": body_hash,
                        "observed_bytes": observed_bytes,
                        "http_status": response_status,
                        "content_type": content_type,
                        "content_encoding": content_encoding,
                    }
            await self._append_audit(session, project_id, run_id, owner, "observation_recorded", {"ordinal": ordinal, "state": state})
            if state == "unknown":
                await self._interrupt(session, run, owner, finished_ns)
            else:
                remaining = (
                    await session.execute(
                        select(func.count())
                        .select_from(t.performance_dispatches)
                        .where(
                            t.performance_dispatches.c.run_id == run_id,
                            t.performance_dispatches.c.state.in_(["pending", "dispatched"]),
                        )
                    )
                ).scalar_one()
                if remaining == 0 and run["window_end_ns"] is not None:
                    await session.execute(update(t.performance_runs).where(t.performance_runs.c.id == run_id).values(status="completed", finished_at=now()))
                    await self._append_audit(session, project_id, run_id, owner, "run_finished", {"population_count": run["population_count"]})

        if artifact_id is not None:
            try:
                receipt = await asyncio.to_thread(self._response_artifact_store().publish, artifact_id, captured_body, binding, artifact_metadata)
            except Exception:
                return
            async with self.sf.begin() as session:
                await self._run(session, owner, project_id, run_id, lock=True)
                current = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == artifact_id).with_for_update())).mappings().first()
                if current is None or current["status"] != "write_unknown":
                    raise Conflict
                await session.execute(
                    update(t.performance_response_artifacts)
                    .where(t.performance_response_artifacts.c.id == artifact_id, t.performance_response_artifacts.c.status == "write_unknown")
                    .values(
                        status=capture_status,
                        key_version=receipt["key_version"],
                        sealed_sha256=receipt["sealed_sha256"],
                        sealed_bytes=receipt["sealed_bytes"],
                        receipt_hash=fingerprint(receipt),
                        updated_at_ms=int(time.time() * 1000),
                    )
                )

    async def reconcile_response_artifact(self, owner, project_id, run_id, ordinal):
        _bounded_int(ordinal, maximum=10_999)
        async with self.sf() as session:
            run = await self._run(session, owner, project_id, run_id)
            artifact = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts).where(
                            t.performance_response_artifacts.c.project_id == project_id,
                            t.performance_response_artifacts.c.run_id == run_id,
                            t.performance_response_artifacts.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .first()
            )
            dispatch = (
                (
                    await session.execute(
                        select(t.performance_dispatches).where(
                            t.performance_dispatches.c.project_id == project_id,
                            t.performance_dispatches.c.run_id == run_id,
                            t.performance_dispatches.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if artifact is None or dispatch is None:
            raise Conflict
        if artifact["status"] != "write_unknown":
            return {"artifact_id": artifact["id"], "status": artifact["status"], "reconciled": False}
        binding = {
            "owner_id": owner,
            "project_id": project_id,
            "run_id": run_id,
            "ordinal": ordinal,
            "dispatch_id": dispatch["dispatch_id"],
            "scenario_hash": run["scenario_hash"],
        }
        receipt = await asyncio.to_thread(self._response_artifact_store().inspect, artifact["id"], binding)
        if receipt is not None:
            stored_hash = artifact["response_sha256"] if artifact["hash_scope"] == "full" else artifact["captured_prefix_sha256"]
            if (
                receipt["capture_status"] not in {"complete", "partial", "truncated"}
                or receipt["hash_scope"] != artifact["hash_scope"]
                or receipt["body_sha256"] != stored_hash
                or receipt["body_bytes"] != artifact["captured_bytes"]
                or receipt["observed_bytes"] != artifact["observed_bytes"]
                or receipt["http_status"] != dispatch["response_status"]
                or receipt["content_type"] != artifact["content_type"]
                or receipt["content_encoding"] != artifact["content_encoding"]
            ):
                raise Conflict
        async with self.sf.begin() as session:
            await self._run(session, owner, project_id, run_id, lock=True)
            current = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == artifact["id"]).with_for_update())).mappings().first()
            if current is None:
                raise Conflict
            if current["status"] != "write_unknown":
                return {"artifact_id": current["id"], "status": current["status"], "reconciled": False}
            at_ms = int(time.time() * 1000)
            if receipt is None:
                values = {
                    "status": "write_failed",
                    "hash_scope": "none",
                    "response_sha256": None,
                    "captured_prefix_sha256": None,
                    "captured_bytes": 0,
                    "observed_bytes": 0,
                    "content_type": None,
                    "content_encoding": None,
                    "key_version": None,
                    "sealed_sha256": None,
                    "sealed_bytes": None,
                    "receipt_hash": None,
                    "updated_at_ms": at_ms,
                }
                final_status = "write_failed"
            else:
                scope = receipt["hash_scope"]
                values = {
                    "status": receipt["capture_status"],
                    "hash_scope": scope,
                    "response_sha256": receipt["body_sha256"] if scope == "full" else None,
                    "captured_prefix_sha256": receipt["body_sha256"] if scope == "prefix" else None,
                    "captured_bytes": receipt["body_bytes"],
                    "observed_bytes": receipt["observed_bytes"],
                    "content_type": receipt["content_type"],
                    "content_encoding": receipt["content_encoding"],
                    "key_version": receipt["key_version"],
                    "sealed_sha256": receipt["sealed_sha256"],
                    "sealed_bytes": receipt["sealed_bytes"],
                    "receipt_hash": fingerprint(receipt),
                    "updated_at_ms": at_ms,
                }
                final_status = receipt["capture_status"]
            await session.execute(update(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == current["id"], t.performance_response_artifacts.c.status == "write_unknown").values(**values))
        return {"artifact_id": artifact["id"], "status": final_status, "reconciled": True}

    async def _interrupt(self, session, run, actor, at_ns):
        run_id = run["id"]
        await session.execute(
            update(t.performance_response_artifacts)
            .where(
                t.performance_response_artifacts.c.project_id == run["project_id"],
                t.performance_response_artifacts.c.run_id == run_id,
                t.performance_response_artifacts.c.status == "pending",
                t.performance_response_artifacts.c.ordinal.in_(
                    select(t.performance_dispatches.c.ordinal).where(
                        t.performance_dispatches.c.project_id == run["project_id"],
                        t.performance_dispatches.c.run_id == run_id,
                        t.performance_dispatches.c.state.in_(["dispatched", "unknown"]),
                    )
                ),
            )
            .values(status="write_unknown", updated_at_ms=int(time.time() * 1000))
        )
        await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.state == "pending").values(state="not_dispatched"))
        await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.state == "dispatched").values(state="unknown"))
        await session.execute(update(t.performance_runs).where(t.performance_runs.c.id == run_id).values(status="interrupted", window_end_ns=run["window_end_ns"] if run["window_end_ns"] is not None else at_ns, finished_at=now()))
        await self._append_audit(session, run["project_id"], run_id, actor, "run_interrupted", {"reason": "delivery_unknown", "at_ns": at_ns})

    async def interrupt_run(self, owner, project_id, run_id, *, at_ns):
        _bounded_int(at_ns, maximum=9_223_372_036_854_775_807)
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            if run["status"] not in {"created", "running"}:
                return False
            await self._interrupt(session, run, owner, at_ns)
        return True

    async def get_run(self, owner, project_id, run_id):
        async with self.sf() as session:
            run = await self._run(session, owner, project_id, run_id)
            grouped = await session.execute(
                select(t.performance_dispatches.c.state, func.count()).where(t.performance_dispatches.c.project_id == project_id, t.performance_dispatches.c.run_id == run_id).group_by(t.performance_dispatches.c.state)
            )
            counts = Counter({state: count for state, count in grouped})
            if sum(counts.values()) != run["population_count"]:
                raise Conflict
            result = {**run, "state_counts": {state: counts.get(state, 0) for state in _RUN_STATES}, "metrics": None}
            if run["window_start_ns"] is not None and run["window_end_ns"] is not None:
                dispatches = await session.execute(
                    select(
                        t.performance_dispatches.c.ordinal,
                        t.performance_dispatches.c.phase,
                        t.performance_dispatches.c.state,
                        t.performance_dispatches.c.send_started_ns,
                        t.performance_dispatches.c.finished_ns,
                        t.performance_dispatches.c.elapsed_ms,
                        t.performance_dispatches.c.output_tokens,
                        t.performance_dispatches.c.token_source,
                    )
                    .where(t.performance_dispatches.c.project_id == project_id, t.performance_dispatches.c.run_id == run_id)
                    .order_by(t.performance_dispatches.c.ordinal)
                )
                result["metrics"] = summarize_performance_dispatches(
                    [dict(row) for row in dispatches.mappings()],
                    window_start_ns=run["window_start_ns"],
                    window_end_ns=run["window_end_ns"],
                )
            return result

    @staticmethod
    def _decode_run_cursor(cursor):
        if type(cursor) is not str or not 1 <= len(cursor) <= 256:
            raise ValueError("Invalid performance run cursor")
        try:
            raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            values = json.loads(raw)
            if not isinstance(values, list) or len(values) != 2 or any(type(value) is not str for value in values) or not 1 <= len(values[0]) <= 40 or not 1 <= len(values[1]) <= 64 or datetime.fromisoformat(values[0]).tzinfo is None:
                raise ValueError
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Invalid performance run cursor") from None
        return values[0], values[1]

    @staticmethod
    def _encode_run_cursor(created_at, run_id):
        raw = json.dumps([created_at, run_id], separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    async def list_runs(self, owner, project_id, *, limit=50, cursor=None):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid performance run page")
        cursor_values = self._decode_run_cursor(cursor) if cursor is not None else None
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            filters = [
                t.performance_runs.c.project_id == project_id,
                t.performance_runs.c.owner_id == owner,
            ]
            total = await session.scalar(select(func.count()).select_from(t.performance_runs).where(*filters))
            statement = select(t.performance_runs).where(*filters)
            if cursor_values is not None:
                created_at, run_id = cursor_values
                statement = statement.where((t.performance_runs.c.created_at < created_at) | ((t.performance_runs.c.created_at == created_at) & (t.performance_runs.c.id < run_id)))
            rows = await session.execute(statement.order_by(t.performance_runs.c.created_at.desc(), t.performance_runs.c.id.desc()).limit(limit + 1))
            items = [dict(row) for row in rows.mappings()]
            has_more = len(items) > limit
            items = items[:limit]
            next_cursor = self._encode_run_cursor(items[-1]["created_at"], items[-1]["id"]) if has_more and items else None
            return {"items": items, "total": total, "next_cursor": next_cursor}

    async def list_dispatches(self, owner, project_id, run_id, *, offset=0, limit=100):
        if type(offset) is not int or not 0 <= offset < self._MAX_RUN_POPULATION:
            raise ValueError("Invalid performance dispatch page")
        _bounded_int(limit, minimum=1, maximum=200)
        async with self.sf() as session:
            run = await self._run(session, owner, project_id, run_id)
            rows = await session.execute(
                select(t.performance_dispatches).where(t.performance_dispatches.c.project_id == project_id, t.performance_dispatches.c.run_id == run_id).order_by(t.performance_dispatches.c.ordinal).offset(offset).limit(limit)
            )
            result = [dict(row) for row in rows.mappings()]
            if offset == 0 and len(result) < min(limit, run["population_count"]):
                raise Conflict
            return result

    async def run_audit(self, owner, project_id, run_id):
        async with self.sf() as session:
            await self._run(session, owner, project_id, run_id)
            rows = await session.execute(select(t.performance_run_audit).where(t.performance_run_audit.c.project_id == project_id, t.performance_run_audit.c.run_id == run_id).order_by(t.performance_run_audit.c.sequence))
            return [dict(row) for row in rows.mappings()]

    async def create_response_evidence_access(self, actor, project_id, run_id, ordinal, payload: EvidenceAccessCreate):
        payload = EvidenceAccessCreate.model_validate(payload.model_dump())
        if payload.kind != "response":
            raise Conflict
        _bounded_int(ordinal, maximum=10_999)
        async with self.sf() as session:
            run = await self._run(session, actor, project_id, run_id)
            dispatch = (
                (
                    await session.execute(
                        select(t.performance_dispatches).where(
                            t.performance_dispatches.c.project_id == project_id,
                            t.performance_dispatches.c.run_id == run_id,
                            t.performance_dispatches.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .first()
            )
            artifact = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts).where(
                            t.performance_response_artifacts.c.project_id == project_id,
                            t.performance_response_artifacts.c.run_id == run_id,
                            t.performance_response_artifacts.c.ordinal == ordinal,
                        )
                    )
                )
                .mappings()
                .first()
            )
        if dispatch is None or artifact is None or artifact["dispatch_id"] != dispatch["dispatch_id"]:
            raise NotFound
        if artifact["status"] != "complete" or artifact["hash_scope"] != "full" or artifact["response_sha256"] != payload.evidence_hash or artifact["sealed_sha256"] is None or artifact["receipt_hash"] is None:
            raise Conflict
        binding = {
            "owner_id": actor,
            "project_id": project_id,
            "run_id": run_id,
            "ordinal": ordinal,
            "dispatch_id": dispatch["dispatch_id"],
            "scenario_hash": run["scenario_hash"],
        }
        receipt = await asyncio.to_thread(self._response_artifact_store().inspect, artifact["id"], binding)
        if receipt is None or receipt["capture_status"] != "complete" or receipt["body_sha256"] != payload.evidence_hash or receipt["sealed_sha256"] != artifact["sealed_sha256"] or fingerprint(receipt) != artifact["receipt_hash"]:
            raise RequestProtectionError("Response artifact integrity check failed")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        at = int(time.time() * 1000)
        expires = at + 300_000
        async with self.sf.begin() as session:
            run = await self._run(session, actor, project_id, run_id, lock=True)
            current = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts)
                        .where(
                            t.performance_response_artifacts.c.id == artifact["id"],
                        )
                        .with_for_update()
                    )
                )
                .mappings()
                .first()
            )
            if current is None or any(current[key] != artifact[key] for key in ("status", "response_sha256", "sealed_sha256", "receipt_hash")):
                raise Conflict
            await session.execute(
                insert(t.performance_evidence_access_grants).values(
                    token_hash=token_hash,
                    project_id=project_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    dispatch_id=dispatch["dispatch_id"],
                    artifact_id=artifact["id"],
                    actor_id=actor,
                    evidence_hash=payload.evidence_hash,
                    created_at_ms=at,
                    expires_at_ms=expires,
                )
            )
            await self._append_audit(session, project_id, run_id, actor, "response_access_granted", {"ordinal": ordinal, "evidence_hash": payload.evidence_hash})
        return {"access_id": token, "expires_at_ms": expires, "evidence_kind": "response", "evidence_hash": payload.evidence_hash}

    async def read_response_evidence_access(self, actor, access_id, range_header=None, *, project_id=None):
        if type(access_id) is not str or not 32 <= len(access_id) <= 128 or not access_id.isascii() or any(not (character.isalnum() or character in "_-") for character in access_id):
            raise NotFound
        token_hash = hashlib.sha256(access_id.encode("ascii", errors="ignore")).hexdigest()
        at = int(time.time() * 1000)
        async with self.sf() as session:
            query = select(t.performance_evidence_access_grants).where(
                t.performance_evidence_access_grants.c.token_hash == token_hash,
                t.performance_evidence_access_grants.c.actor_id == actor,
                t.performance_evidence_access_grants.c.consumed_at_ms.is_(None),
                t.performance_evidence_access_grants.c.revoked_at_ms.is_(None),
                t.performance_evidence_access_grants.c.expires_at_ms > at,
            )
            grant = (await session.execute(query)).mappings().first()
            if grant is None or (project_id is not None and grant["project_id"] != project_id):
                raise NotFound
            project_id, run_id, ordinal = grant["project_id"], grant["run_id"], grant["ordinal"]
            run = await self._run(session, actor, project_id, run_id)
            dispatch = (
                (
                    await session.execute(
                        select(t.performance_dispatches).where(
                            t.performance_dispatches.c.project_id == project_id,
                            t.performance_dispatches.c.run_id == run_id,
                            t.performance_dispatches.c.ordinal == ordinal,
                            t.performance_dispatches.c.dispatch_id == grant["dispatch_id"],
                        )
                    )
                )
                .mappings()
                .first()
            )
            artifact = (
                (
                    await session.execute(
                        select(t.performance_response_artifacts).where(
                            t.performance_response_artifacts.c.id == grant["artifact_id"],
                            t.performance_response_artifacts.c.project_id == project_id,
                            t.performance_response_artifacts.c.run_id == run_id,
                            t.performance_response_artifacts.c.ordinal == ordinal,
                            t.performance_response_artifacts.c.dispatch_id == grant["dispatch_id"],
                        )
                    )
                )
                .mappings()
                .first()
            )
        if dispatch is None or artifact is None or artifact["status"] != "complete" or artifact["response_sha256"] != grant["evidence_hash"]:
            raise Conflict
        binding = {
            "owner_id": actor,
            "project_id": project_id,
            "run_id": run_id,
            "ordinal": ordinal,
            "dispatch_id": dispatch["dispatch_id"],
            "scenario_hash": run["scenario_hash"],
        }
        store = self._response_artifact_store()
        receipt = await asyncio.to_thread(store.inspect, artifact["id"], binding)
        if receipt is None or receipt["body_sha256"] != grant["evidence_hash"] or receipt["sealed_sha256"] != artifact["sealed_sha256"] or fingerprint(receipt) != artifact["receipt_hash"]:
            raise RequestProtectionError("Response artifact integrity check failed")
        metadata, body, content_range = await asyncio.to_thread(store.open_range, artifact["id"], binding, range_header)
        if metadata["capture_status"] != "complete":
            raise Conflict
        async with self.sf.begin() as session:
            await self._run(session, actor, project_id, run_id, lock=True)
            current = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == artifact["id"]))).mappings().first()
            if current is None or any(current[key] != artifact[key] for key in ("status", "response_sha256", "sealed_sha256", "receipt_hash")):
                raise Conflict
            consumed_at = int(time.time() * 1000)
            updated = await session.execute(
                update(t.performance_evidence_access_grants)
                .where(
                    t.performance_evidence_access_grants.c.token_hash == token_hash,
                    t.performance_evidence_access_grants.c.actor_id == actor,
                    t.performance_evidence_access_grants.c.consumed_at_ms.is_(None),
                    t.performance_evidence_access_grants.c.revoked_at_ms.is_(None),
                    t.performance_evidence_access_grants.c.expires_at_ms > consumed_at,
                )
                .values(consumed_at_ms=consumed_at)
            )
            if updated.rowcount != 1:
                raise NotFound
            await self._append_audit(session, project_id, run_id, actor, "response_access_read", {"ordinal": ordinal, "evidence_hash": grant["evidence_hash"]})
        return {"body": body, "content_type": "application/octet-stream", "status_code": 206 if content_range else 200, "content_range": content_range}
