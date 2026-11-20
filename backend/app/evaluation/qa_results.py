"""Owner-scoped, metadata-only effectiveness result queries."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import and_, func, select
from sqlalchemy import case as sql_case

from app.evaluation import tables as t
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.qa_result_cursor import InvalidResultCursor, StaleResultCursor, decode_cursor, encode_cursor
from app.evaluation.repository import Conflict, NotFound

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_CASE_FILTERS = frozenset({"integrity_status", "dispatch_state", "kind", "http_status", "reference_status"})
_RUN_FILTERS = frozenset({"component_id", "dataset_id", "plan_id", "status"})


class ResultRepository(PlanRepository):
    def __init__(self, sf, *, cursor_secret: str | None = None):
        super().__init__(sf)
        if cursor_secret is None:
            from app.gateway.auth.config import get_auth_config

            cursor_secret = get_auth_config().jwt_secret
        if type(cursor_secret) is not str or not cursor_secret:
            raise ValueError("Result cursor signing is unavailable")
        self._cursor_secret = cursor_secret

    @staticmethod
    def _limit(value):
        if type(value) is not int or not 1 <= value <= _MAX_LIMIT:
            raise ValueError("Invalid result page limit")
        return value

    @staticmethod
    def _filters(filters):
        if filters is None:
            return {}
        if type(filters) is not dict or set(filters) - _CASE_FILTERS:
            raise ValueError("Unsupported result filter")
        normalized = {}
        for name, value in filters.items():
            if value is None:
                continue
            if name == "http_status":
                if type(value) is not int or not 100 <= value <= 599:
                    raise ValueError("Invalid result filter")
            elif type(value) is not str or not 1 <= len(value) <= 40:
                raise ValueError("Invalid result filter")
            normalized[name] = value
        return normalized

    @staticmethod
    def _run_filters(filters):
        if filters is None:
            return {}
        if type(filters) is not dict or set(filters) - _RUN_FILTERS:
            raise ValueError("Unsupported run filter")
        normalized = {}
        for name, value in filters.items():
            if value is None:
                continue
            if type(value) is not str or not 1 <= len(value) <= 80:
                raise ValueError("Invalid run filter")
            normalized[name] = value
        return normalized

    @staticmethod
    def _digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()

    async def _run_context(self, session, owner, project_id, run_id):
        await self._project(session, owner, project_id)
        run = (await session.execute(select(t.dispatch_runs).where(t.dispatch_runs.c.project_id == project_id, t.dispatch_runs.c.id == run_id))).mappings().first()
        if run is None:
            raise NotFound
        run = dict(run)
        plan = await self._plan(session, owner, project_id, run["plan_id"])
        definition = plan["definition"]
        if definition["limits"]["mode"] != "effectiveness" or run["plan_hash"] != plan["definition_hash"]:
            raise NotFound
        dataset = await self._dataset(session, owner, project_id, plan["dataset_id"])
        if dataset["status"] != "frozen" or dataset["revision"] != definition["dataset_revision"] or dataset["content_hash"] != definition["dataset_hash"]:
            raise Conflict
        sample_count = await session.scalar(select(func.count()).select_from(t.samples).where(t.samples.c.dataset_id == dataset["id"]))
        if not sample_count or sample_count != dataset["sample_count"]:
            raise Conflict
        if definition["limits"]["request_count"] != sample_count:
            raise Conflict
        snapshot_hash = self._digest(
            {
                "schema": "effectiveness-run-snapshot.v1",
                "project_id": project_id,
                "run_id": run_id,
                "plan_id": plan["id"],
                "plan_hash": plan["definition_hash"],
                "dataset_id": dataset["id"],
                "dataset_revision": dataset["revision"],
                "dataset_hash": dataset["content_hash"],
                "sample_count": sample_count,
            }
        )
        return run, plan, dataset, sample_count, snapshot_hash

    @staticmethod
    def _case_source(dataset_id):
        """Expose frozen sample identity and deterministic ordinal without reading payloads."""
        return (
            select(
                t.samples.c.sample_id.label("case_id"),
                func.row_number().over(order_by=t.samples.c.sample_id).label("ordinal"),
                t.references.c.sample_id.label("reference_sample_id"),
            )
            .select_from(
                t.samples.outerjoin(
                    t.references,
                    and_(t.references.c.dataset_id == t.samples.c.dataset_id, t.references.c.sample_id == t.samples.c.sample_id),
                )
            )
            .where(t.samples.c.dataset_id == dataset_id)
            .subquery("frozen_cases")
        )

    @classmethod
    def _case_filters(cls, source, run_id, filters):
        dispatch = t.dispatches.alias("case_dispatch")
        integrity = func.coalesce(dispatch.c.sample_id == source.c.case_id, False)
        conditions = [dispatch.c.run_id == run_id, dispatch.c.ordinal == source.c.ordinal]
        dispatch_state = sql_case((integrity, dispatch.c.state), else_=None)
        kind = sql_case((integrity, dispatch.c.kind), else_=None)
        http_status = sql_case((integrity, dispatch.c.http_status), else_=None)
        integrity_status = sql_case((dispatch.c.ordinal.is_(None), "missing_dispatch"), (integrity, "complete"), else_="sample_mismatch")
        references_status = sql_case((source.c.reference_sample_id.is_(None), "absent"), else_="provided")
        expressions = {
            "integrity_status": integrity_status,
            "dispatch_state": dispatch_state,
            "kind": kind,
            "http_status": http_status,
            "reference_status": references_status,
        }
        from_clause = source.outerjoin(dispatch, and_(*conditions))
        criteria = [expressions[name] == value for name, value in filters.items()]
        return from_clause, criteria

    async def _case_result_version(self, session, run_id, snapshot_hash):
        revision = await session.scalar(select(t.dispatch_runs.c.revision).where(t.dispatch_runs.c.id == run_id))
        if revision is None:
            raise NotFound
        return self._digest({"snapshot_hash": snapshot_hash, "run_revision": revision})

    async def _case_projection(self, session, run, dataset, case_rows, snapshot_hash):
        expected_sample_by_ordinal = dict(case_rows)
        ordinals = tuple(expected_sample_by_ordinal)
        sample_ids = tuple(expected_sample_by_ordinal.values())
        references = set(
            (
                await session.execute(
                    select(t.references.c.sample_id).where(
                        t.references.c.dataset_id == dataset["id"],
                        t.references.c.sample_id.in_(sample_ids),
                    )
                )
            ).scalars()
        )
        dispatch_rows = (
            (
                await session.execute(
                    select(
                        t.dispatches.c.ordinal,
                        t.dispatches.c.sample_id,
                        t.dispatches.c.state,
                        t.dispatches.c.kind,
                        t.dispatches.c.http_status,
                        t.dispatches.c.body_bytes,
                        t.dispatches.c.elapsed_ms,
                        t.output_evidence.c.ordinal.label("output_present"),
                        t.response_artifacts.c.status.label("response_status"),
                        t.response_artifacts.c.hash_scope.label("response_hash_scope"),
                        t.response_artifacts.c.response_sha256,
                        t.response_artifacts.c.captured_prefix_sha256,
                        t.response_artifacts.c.captured_bytes,
                        t.response_artifacts.c.observed_bytes,
                        t.response_artifacts.c.content_type,
                    )
                    .select_from(
                        t.dispatches.outerjoin(
                            t.output_evidence,
                            and_(t.output_evidence.c.run_id == t.dispatches.c.run_id, t.output_evidence.c.ordinal == t.dispatches.c.ordinal),
                        ).outerjoin(
                            t.response_artifacts,
                            and_(t.response_artifacts.c.run_id == t.dispatches.c.run_id, t.response_artifacts.c.ordinal == t.dispatches.c.ordinal),
                        )
                    )
                    .where(t.dispatches.c.run_id == run["id"], t.dispatches.c.ordinal.in_(ordinals))
                )
            )
            .mappings()
            .all()
        )
        by_ordinal = {row["ordinal"]: dict(row) for row in dispatch_rows}
        items = []
        for ordinal, sample_id in expected_sample_by_ordinal.items():
            row = by_ordinal.get(ordinal)
            integrity = "missing_dispatch" if row is None else "sample_mismatch" if row["sample_id"] != sample_id else "complete"
            valid = integrity == "complete"
            item = {
                "case_id": sample_id,
                "ordinal": ordinal,
                "integrity_status": integrity,
                "reference_status": "provided" if sample_id in references else "absent",
                "dispatch_state": row["state"] if valid else None,
                "kind": row["kind"] if valid else None,
                "http_status": row["http_status"] if valid else None,
                "latency_ms": row["elapsed_ms"] if valid else None,
                "response_bytes": row["body_bytes"] if valid else None,
                "output_evidence": {"available": True} if valid and row["output_present"] is not None else None,
                "response_evidence": (
                    {
                        "status": row["response_status"],
                        "hash_scope": row["response_hash_scope"],
                        "sha256": row["response_sha256"] or row["captured_prefix_sha256"],
                        "captured_bytes": row["captured_bytes"],
                        "observed_bytes": row["observed_bytes"],
                        "content_type": row["content_type"],
                    }
                    if valid and row["response_status"] is not None
                    else None
                ),
            }
            items.append(item)
        version = self._digest({"snapshot_hash": snapshot_hash, "run_revision": run["revision"]})
        return items, version

    async def _run_projection(self, session, owner, project_id, run_id):
        run, plan, dataset, sample_count, snapshot_hash = await self._run_context(session, owner, project_id, run_id)
        sample_ids = list((await session.execute(select(t.samples.c.sample_id).where(t.samples.c.dataset_id == dataset["id"]).order_by(t.samples.c.sample_id))).scalars())
        cases, case_version = await self._case_projection(session, run, dataset, tuple(enumerate(sample_ids, start=1)), snapshot_hash)
        technical_counts = {}
        blockers = set()
        for case in cases:
            state = case["integrity_status"] if case["integrity_status"] != "complete" else case["dispatch_state"] or "unknown"
            technical_counts[state] = technical_counts.get(state, 0) + 1
            if case["integrity_status"] != "complete":
                blockers.add("dispatch_integrity_incomplete")
            if state == "delivery_unknown":
                blockers.add("delivery_unknown")
            elif state in {"pending", "dispatched", "not_dispatched", "unknown"}:
                blockers.add("dispatch_incomplete")

        if run["status"] == "recording":
            blockers.add("collection_not_finished")
        elif run["status"] == "interrupted":
            blockers.add("run_interrupted")

        result = {
            "scope": "effectiveness_run_detail.v1",
            "run_id": run["id"],
            "project_id": project_id,
            "plan_id": plan["id"],
            "plan_hash": plan["definition_hash"],
            "component_id": plan["component_id"],
            "request_version_id": plan["request_version_id"],
            "dataset_id": dataset["id"],
            "dataset_revision": dataset["revision"],
            "dataset_hash": dataset["content_hash"],
            "status": run["status"],
            "started_at_ms": run["started_at_ms"],
            "finished_at_ms": run["finished_at_ms"],
            "stop_reason": run["stop_reason"],
            "request_count": run["request_count"],
            "concurrency": run["concurrency"],
            "total": sample_count,
            "snapshot_hash": snapshot_hash,
            "result_version": self._digest({"run_revision": run["revision"], "case_version": case_version}),
            "technical_counts": dict(sorted(technical_counts.items())),
            "assessment_status": "NOT_EVALUATED",
            "verdict": "BLOCKED" if blockers else "NOT_EVALUATED",
            "blockers": sorted(blockers),
        }
        return result

    async def _run_summary_projection(self, session, owner, project_id, run, plan):
        run_context, _, dataset, sample_count, snapshot_hash = await self._run_context(session, owner, project_id, run["id"])
        source = self._case_source(dataset["id"])
        dispatch = t.dispatches.alias("summary_dispatch")
        valid_dispatch = dispatch.c.sample_id == source.c.case_id
        state = sql_case(
            (dispatch.c.ordinal.is_(None), "missing_dispatch"),
            (valid_dispatch, dispatch.c.state),
            else_="sample_mismatch",
        )
        counts = (
            await session.execute(
                select(state.label("state"), func.count().label("count"))
                .select_from(
                    source.outerjoin(
                        dispatch,
                        and_(dispatch.c.run_id == run["id"], dispatch.c.ordinal == source.c.ordinal),
                    )
                )
                .group_by(state)
            )
        ).all()
        technical_counts = {row.state: row.count for row in counts}
        blockers = set()
        for state_name in technical_counts:
            if state_name in {"missing_dispatch", "sample_mismatch"}:
                blockers.add("dispatch_integrity_incomplete")
            if state_name == "delivery_unknown":
                blockers.add("delivery_unknown")
            elif state_name in {"pending", "dispatched", "not_dispatched", "unknown"}:
                blockers.add("dispatch_incomplete")
        if run["status"] == "recording":
            blockers.add("collection_not_finished")
        elif run["status"] == "interrupted":
            blockers.add("run_interrupted")
        return {
            "scope": "effectiveness_run_summary.v1",
            "run_id": run["id"],
            "project_id": project_id,
            "plan_id": plan["id"],
            "plan_hash": plan["definition_hash"],
            "component_id": plan["component_id"],
            "request_version_id": plan["request_version_id"],
            "dataset_id": dataset["id"],
            "dataset_revision": dataset["revision"],
            "dataset_hash": dataset["content_hash"],
            "status": run["status"],
            "started_at_ms": run["started_at_ms"],
            "finished_at_ms": run["finished_at_ms"],
            "stop_reason": run["stop_reason"],
            "request_count": run["request_count"],
            "concurrency": run["concurrency"],
            "case_count": sample_count,
            "snapshot_hash": snapshot_hash,
            "result_version": self._digest({"run_revision": run_context["revision"], "snapshot_hash": snapshot_hash}),
            "technical_counts": dict(sorted(technical_counts.items())),
            "assessment_status": "NOT_EVALUATED",
            "verdict": "BLOCKED" if blockers else "NOT_EVALUATED",
            "blockers": sorted(blockers),
        }

    async def list_runs(self, owner, project_id, *, filters=None, limit=_DEFAULT_LIMIT, cursor=None):
        limit = self._limit(limit)
        filters = self._run_filters(filters)
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            project_result_revision = await session.scalar(
                select(t.projects.c.result_revision).where(t.projects.c.id == project_id)
            )
            result_version = self._digest({"project_result_revision": project_result_revision})
            join = t.dispatch_runs.join(
                t.plans,
                and_(
                    t.plans.c.project_id == t.dispatch_runs.c.project_id,
                    t.plans.c.id == t.dispatch_runs.c.plan_id,
                ),
            )
            criteria = [
                t.dispatch_runs.c.project_id == project_id,
                t.dispatch_runs.c.plan_hash == t.plans.c.definition_hash,
                t.plans.c.definition["limits"]["mode"].as_string() == "effectiveness",
            ]
            filter_columns = {
                "plan_id": t.plans.c.id,
                "dataset_id": t.plans.c.dataset_id,
                "component_id": t.plans.c.component_id,
                "status": t.dispatch_runs.c.status,
            }
            criteria.extend(filter_columns[name] == value for name, value in filters.items())
            total = await session.scalar(select(func.count()).select_from(join).where(*criteria[:3]))
            matched_total = await session.scalar(select(func.count()).select_from(join).where(*criteria))
            binding = {
                "actor_id": owner,
                "project_id": project_id,
                "resource": "runs",
                "filters": filters,
                "limit": limit,
                "ordering": "started_at_ms-desc-run_id-asc",
                "result_version": result_version,
            }
            after = None
            if cursor is not None:
                payload = decode_cursor(cursor, self._cursor_secret, binding, stale_fields=frozenset({"result_version"}))
                position = payload["position"]
                if type(position) is not dict or set(position) != {"started_at_ms", "run_id"}:
                    raise InvalidResultCursor
                if type(position["started_at_ms"]) is not int or type(position["run_id"]) is not str:
                    raise InvalidResultCursor
                after = (position["started_at_ms"], position["run_id"])

            page_criteria = list(criteria)
            if after is not None:
                page_criteria.append(
                    (t.dispatch_runs.c.started_at_ms < after[0])
                    | and_(t.dispatch_runs.c.started_at_ms == after[0], t.dispatch_runs.c.id > after[1])
                )
            columns = [t.dispatch_runs.c[name] for name in t.dispatch_runs.c.keys()]
            columns.extend(
                [
                    t.plans.c.id.label("joined_plan_id"),
                    t.plans.c.component_id.label("joined_component_id"),
                    t.plans.c.request_version_id.label("joined_request_version_id"),
                    t.plans.c.dataset_id.label("joined_dataset_id"),
                    t.plans.c.definition.label("joined_definition"),
                    t.plans.c.definition_hash.label("joined_definition_hash"),
                ]
            )
            candidate_rows = (
                await session.execute(
                    select(*columns)
                    .select_from(join)
                    .where(*page_criteria)
                    .order_by(t.dispatch_runs.c.started_at_ms.desc(), t.dispatch_runs.c.id.asc())
                    .limit(limit + 1)
                )
            ).mappings().all()
            candidates = []
            for row in candidate_rows:
                run = {column.name: row[column.name] for column in t.dispatch_runs.c}
                plan = {
                    "id": row["joined_plan_id"],
                    "component_id": row["joined_component_id"],
                    "request_version_id": row["joined_request_version_id"],
                    "dataset_id": row["joined_dataset_id"],
                    "definition": row["joined_definition"],
                    "definition_hash": row["joined_definition_hash"],
                }
                candidates.append((run, plan))
            page_items = [
                await self._run_summary_projection(session, owner, project_id, run, plan)
                for run, plan in candidates[:limit]
            ]
            next_cursor = None
            if len(candidates) > limit and page_items:
                last = candidates[limit - 1][0]
                next_cursor = encode_cursor(
                    {
                        "binding": binding,
                        "position": {"started_at_ms": last["started_at_ms"], "run_id": last["id"]},
                    },
                    self._cursor_secret,
                )
            current_project_result_revision = await session.scalar(
                select(t.projects.c.result_revision).where(t.projects.c.id == project_id)
            )
            if current_project_result_revision != project_result_revision:
                raise StaleResultCursor
            return {
                "scope": "effectiveness_run_list.v1",
                "result_version": result_version,
                "total": total,
                "matched_total": matched_total,
                "items": page_items,
                "next_cursor": next_cursor,
            }

    async def get_run(self, owner, project_id, run_id):
        async with self.sf() as session:
            return await self._run_projection(session, owner, project_id, run_id)

    async def list_cases(self, owner, project_id, run_id, *, filters=None, limit=_DEFAULT_LIMIT, cursor=None):
        limit = self._limit(limit)
        filters = self._filters(filters)
        async with self.sf() as session:
            run, _, dataset, sample_count, snapshot_hash = await self._run_context(session, owner, project_id, run_id)
            result_version = self._digest({"snapshot_hash": snapshot_hash, "run_revision": run["revision"]})
            binding = {
                "actor_id": owner,
                "project_id": project_id,
                "resource": "run-cases",
                "run_id": run_id,
                "filters": filters,
                "limit": limit,
                "ordering": "ordinal-asc",
                "snapshot_hash": snapshot_hash,
                "result_version": result_version,
            }
            after_ordinal = 0
            if cursor is not None:
                try:
                    after_ordinal = decode_cursor(
                        cursor,
                        self._cursor_secret,
                        binding,
                        stale_fields=frozenset({"snapshot_hash", "result_version"}),
                    )["position"]["ordinal"]
                except StaleResultCursor:
                    raise
                except InvalidResultCursor:
                    raise InvalidResultCursor from None
                if type(after_ordinal) is not int or after_ordinal < 1:
                    raise InvalidResultCursor
            source = self._case_source(dataset["id"])
            from_clause, criteria = self._case_filters(source, run_id, filters)
            matched_total = await session.scalar(select(func.count()).select_from(from_clause).where(*criteria))
            page_rows = (await session.execute(select(source.c.ordinal, source.c.case_id).select_from(from_clause).where(*criteria, source.c.ordinal > after_ordinal).order_by(source.c.ordinal).limit(limit + 1))).all()
            page_candidates = [(row.ordinal, row.case_id) for row in page_rows]
            page_candidates = page_candidates[: limit + 1]
            page_rows_to_project = page_candidates[:limit]
            page_items, _ = await self._case_projection(session, run, dataset, page_rows_to_project, snapshot_hash)
            current_revision = await session.scalar(select(t.dispatch_runs.c.revision).where(t.dispatch_runs.c.id == run_id))
            if current_revision != run["revision"]:
                raise StaleResultCursor
            next_cursor = None
            if len(page_candidates) > limit and page_items:
                next_cursor = encode_cursor({"binding": binding, "position": {"ordinal": page_items[-1]["ordinal"]}}, self._cursor_secret)
            return {
                "scope": "effectiveness_result_list.v1",
                "run_id": run_id,
                "snapshot_hash": snapshot_hash,
                "result_version": result_version,
                "total": sample_count,
                "matched_total": matched_total,
                "items": page_items,
                "next_cursor": next_cursor,
            }

    async def get_case(self, owner, project_id, run_id, case_id):
        if type(case_id) is not str or not case_id:
            raise NotFound
        async with self.sf() as session:
            run, _, dataset, _, snapshot_hash = await self._run_context(session, owner, project_id, run_id)
            exists = await session.scalar(select(t.samples.c.sample_id).where(t.samples.c.dataset_id == dataset["id"], t.samples.c.sample_id == case_id))
            if exists is None:
                raise NotFound from None
            ordinal = await session.scalar(select(func.count()).select_from(t.samples).where(t.samples.c.dataset_id == dataset["id"], t.samples.c.sample_id <= case_id))
            result_version = self._digest({"snapshot_hash": snapshot_hash, "run_revision": run["revision"]})
            items, _ = await self._case_projection(session, run, dataset, ((ordinal, case_id),), snapshot_hash)
            current_revision = await session.scalar(select(t.dispatch_runs.c.revision).where(t.dispatch_runs.c.id == run_id))
            if current_revision != run["revision"]:
                raise StaleResultCursor
            item = items[0]
            return {
                "scope": "effectiveness_case_detail.v1",
                "run_id": run_id,
                "snapshot_hash": snapshot_hash,
                "result_version": result_version,
                **item,
            }
