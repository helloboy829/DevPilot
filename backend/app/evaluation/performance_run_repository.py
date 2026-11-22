"""Owner-scoped durable performance dispatch ledger; contains no transport code."""

from __future__ import annotations

import hmac
import math
from collections import Counter
from collections.abc import Mapping
from uuid import uuid4

from sqlalchemy import func, insert, select, update

from app.evaluation import tables as t
from app.evaluation.performance_metrics import summarize_performance_dispatches
from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceProfile, build_case_manifest
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound, now

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

    async def acknowledge_dispatch(self, owner, project_id, run_id, ordinal, *, send_started_ns, request_bytes=None, request_hash=None):
        _bounded_int(ordinal, maximum=10_999)
        _bounded_int(send_started_ns, maximum=9_223_372_036_854_775_807)
        _bounded_int(request_bytes, maximum=1_048_576) if request_bytes is not None else None
        request_hash = _hash_or_none(request_hash)
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
            if run["window_end_ns"] is not None and dispatch["phase"] == "measurement" and send_started_ns >= run["window_end_ns"]:
                raise Conflict
            if dispatch["phase"] == "measurement" and run["window_start_ns"] is not None and send_started_ns < run["window_start_ns"]:
                raise Conflict
            values = {"state": "dispatched", "send_started_ns": send_started_ns, "request_bytes": request_bytes, "request_hash": request_hash}
            changed = await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.ordinal == ordinal, t.performance_dispatches.c.state == "pending").values(**values))
            if changed.rowcount != 1:
                raise Conflict
            run_values = {"status": "running"}
            if dispatch["phase"] == "measurement" and run["window_start_ns"] is None:
                run_values["window_start_ns"] = send_started_ns
            await session.execute(update(t.performance_runs).where(t.performance_runs.c.id == run_id).values(**run_values))
            await self._append_audit(session, project_id, run_id, owner, "dispatch_acknowledged", {"ordinal": ordinal, "phase": dispatch["phase"]})
            ticket = {"run_id": run_id, "ordinal": ordinal, "dispatch_id": dispatch["dispatch_id"]}
        return ticket

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
        evidence_ref=None,
        output_tokens=None,
        token_source=None,
    ):
        if not isinstance(ticket, Mapping) or set(ticket) != {"run_id", "ordinal", "dispatch_id"}:
            raise Conflict
        run_id, ordinal, dispatch_id = ticket["run_id"], ticket["ordinal"], ticket["dispatch_id"]
        _bounded_int(ordinal, maximum=10_999)
        _bounded_int(finished_ns, maximum=9_223_372_036_854_775_807)
        if state not in {"succeeded", "failed", "timeout", "unknown"}:
            raise Conflict
        if type(elapsed_ms) not in {int, float} or not math.isfinite(elapsed_ms) or elapsed_ms < 0:
            raise Conflict
        response_bytes = _bounded_int(response_bytes) if response_bytes is not None else None
        response_status = _bounded_int(response_status, minimum=100, maximum=599) if response_status is not None else None
        response_hash = _hash_or_none(response_hash)
        if evidence_ref is not None and (type(evidence_ref) is not str or not 1 <= len(evidence_ref) <= 128):
            raise Conflict
        if output_tokens is not None:
            _bounded_int(output_tokens, maximum=2_147_483_647)
            if state != "succeeded" or token_source is None:
                raise Conflict
        if token_source is not None and (type(token_source) is not str or not 1 <= len(token_source) <= 40):
            raise Conflict
        async with self.sf.begin() as session:
            run = await self._run(session, owner, project_id, run_id, lock=True)
            dispatch = (await session.execute(select(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run_id, t.performance_dispatches.c.ordinal == ordinal).with_for_update())).mappings().first()
            if run["status"] != "running" or dispatch is None or dispatch["dispatch_id"] != dispatch_id or dispatch["state"] != "dispatched" or dispatch["send_started_ns"] is None or finished_ns < dispatch["send_started_ns"]:
                raise Conflict
            values = {
                "state": state,
                "finished_ns": finished_ns,
                "elapsed_ms": float(elapsed_ms),
                "response_status": response_status,
                "response_bytes": response_bytes,
                "response_hash": response_hash,
                "evidence_ref": evidence_ref,
                "output_tokens": output_tokens,
                "token_source": token_source,
            }
            await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.id == dispatch["id"]).values(**values))
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

    async def _interrupt(self, session, run, actor, at_ns):
        run_id = run["id"]
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
