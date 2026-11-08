"""Immutable, owner-scoped same-benchmark human QA retest comparisons.

No new execution, raw answers, supplied metrics or acceptance decision. Both runs
are reverified off-loop and reread under ordered locks before an atomic append.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Literal

from pydantic import field_validator
from sqlalchemy import insert, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_reports import ArchiveSource
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.registry import fingerprint, version_key
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


class RetestCreate(StrictDTO):
    baseline: ArchiveSource
    retest: ArchiveSource
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


_BENCHMARK_KEYS = (
    "project_id",
    "component_id",
    "dataset_id",
    "dataset_revision",
    "dataset_hash",
    "dataset_purpose",
    "binding",
    "limits",
    "response_mode",
    "sample_order",
    "evaluation_policy",
    "preflight",
)
_RUN_BUDGET_KEYS = ("max_response_bytes", "max_total_response_bytes", "lease_grace_ms")


def _same_benchmark(baseline, retest):
    if any(baseline[key] != retest[key] for key in _BENCHMARK_KEYS):
        raise Conflict
    return {key: baseline[key] for key in _BENCHMARK_KEYS}


class RetestRepository(SummaryRepository):
    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("Invalid retest identifier")

    async def _retest_row(self, session, owner, project_id, retest_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.retest_archives).where(t.retest_archives.c.id == retest_id, t.retest_archives.c.project_id == project_id, t.retest_archives.c.owner_id == owner))).mappings().first()
        return dict(row) if row is not None else None

    @staticmethod
    def _decode(row):
        try:
            doc = row["document"]
            if not hmac.compare_digest(fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": doc}), row["archive_hash"]):
                raise ValueError
            if doc["schema"] != "qa-retest-archive.v1" or doc["scope"] != "same_benchmark_human_comparison" or doc["acceptance"] != "not_approved":
                raise ValueError
            if any(doc[key] != row[key] for key in ("id", "project_id", "component_id", "created_at_ms")):
                raise ValueError
            if any(doc[side]["run_id"] != row[side + "_run_id"] or doc[side]["plan_label"] != row[side + "_label"] for side in ("baseline", "retest")):
                raise ValueError
            return {**doc, "archive_hash": row["archive_hash"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Retest archive integrity check failed") from None

    async def get_retest(self, owner, project_id, retest_id):
        self._identifier(retest_id)
        async with self.sf() as session:
            row = await self._retest_row(session, owner, project_id, retest_id)
        if row is None:
            raise NotFound
        return await asyncio.to_thread(self._decode, row)

    async def list_retests(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            columns = [column for column in t.retest_archives.c if column.name not in {"document", "request_hash", "archive_hash", "owner_id"}]
            rows = (
                await session.execute(select(*columns).where(t.retest_archives.c.project_id == project_id, t.retest_archives.c.owner_id == owner).order_by(t.retest_archives.c.created_at_ms.desc(), t.retest_archives.c.id.desc()).limit(100))
            ).mappings()
            return [dict(row) for row in rows]

    @staticmethod
    def _verify_pair(owner, snapshots, protection, payload):
        before, after = snapshots
        summaries = [SummaryRepository._verify_summary(owner, snapshot, protection) for snapshot in snapshots]
        if any(summary["readiness"] != "review_complete" or summary["blockers"] for summary in summaries):
            raise Conflict
        for summary, viewed in zip(summaries, (payload.baseline, payload.retest), strict=True):
            if not hmac.compare_digest(summary["summary_hash"], viewed.summary_hash):
                raise Conflict
        old, new = before["plan"]["definition"], after["plan"]["definition"]
        benchmark = _same_benchmark(old, new)
        if (
            before["run"]["id"] == after["run"]["id"]
            or before["plan"]["id"] == after["plan"]["id"]
            or version_key(old["version_label"]) == version_key(new["version_label"])
            or before["run"]["finished_at_ms"] is None
            or after["run"]["started_at_ms"] <= before["run"]["finished_at_ms"]
            or any(before["run"][key] != after["run"][key] for key in _RUN_BUDGET_KEYS)
        ):
            raise Conflict
        benchmark["run_response_budgets"] = {key: before["run"][key] for key in _RUN_BUDGET_KEYS}
        # Every row was already authenticated by _verify_summary above. Copy only
        # bounded decision commitments, never decrypted Q/A/gold/review notes.
        reviews = [{row["ordinal"]: row for row in snapshot["latest_reviews"]} for snapshot in snapshots]
        cases = []
        transitions = {key: 0 for key in ("fail_to_pass", "pass_to_fail", "pass_to_pass", "fail_to_fail")}
        for left, right in zip(before["dispatches"], after["dispatches"], strict=True):
            if (left["ordinal"], left["sample_id"]) != (right["ordinal"], right["sample_id"]):
                raise Conflict
            decisions = [side[left["ordinal"]] for side in reviews]
            transition = decisions[0]["decision"] + "_to_" + decisions[1]["decision"]
            if transition not in transitions:
                raise Conflict
            transitions[transition] += 1
            case = {"ordinal": left["ordinal"], "sample_id": left["sample_id"], "transition": transition}
            for side, decision in zip(("baseline", "retest"), decisions, strict=True):
                case.update({side + "_decision": decision["decision"], side + "_case_hash": decision["case_hash"], side + "_revision": decision["revision"], side + "_review_hash": decision["protected_hash"]})
            cases.append(case)
        denominator = summaries[0]["human_pass_rate"]["denominator"]
        if len(cases) != denominator or summaries[1]["human_pass_rate"]["denominator"] != denominator:
            raise Conflict
        numerator = summaries[1]["human_pass_rate"]["numerator"] - summaries[0]["human_pass_rate"]["numerator"]
        return {
            "baseline": summaries[0],
            "retest": summaries[1],
            "benchmark": benchmark,
            "benchmark_hash": fingerprint(benchmark),
            "request_definition_changed": any(old[key] != new[key] for key in ("request_version_id", "request_protected_hash", "request_template_fingerprint")),
            "transitions": transitions,
            "cases": cases,
            "pass_rate_delta": {"numerator": numerator, "denominator": denominator, "value": numerator / denominator},
        }

    async def create_retest(self, owner, project_id, retest_id, payload: RetestCreate):
        self._identifier(retest_id)
        payload = RetestCreate.model_validate(payload.model_dump())
        if payload.baseline.run_id == payload.retest.run_id:
            raise Conflict
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            project = await self._project(session, owner, project_id)
            existing = await self._retest_row(session, owner, project_id, retest_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode, existing)
            snapshots = [await self._summary_snapshot(session, owner, project_id, source.run_id) for source in (payload.baseline, payload.retest)]
        verified = await asyncio.to_thread(self._verify_pair, owner, snapshots, self._evidence_protection(), payload)
        document = {
            "schema": "qa-retest-archive.v1",
            "scope": "same_benchmark_human_comparison",
            "id": retest_id,
            "project_id": project_id,
            "project_name": project["name"],
            "component_id": verified["baseline"]["component_id"],
            "component_name": verified["baseline"]["component_name"],
            "created_at_ms": self._time(),
            **verified,
            "acceptance": "not_approved",
        }
        row = {key: document[key] for key in ("id", "project_id", "component_id", "created_at_ms")}
        row.update({side + "_run_id": document[side]["run_id"] for side in ("baseline", "retest")})
        row.update({side + "_label": document[side]["plan_label"] for side in ("baseline", "retest")})
        row.update(owner_id=owner, request_hash=request_hash, document=document, archive_hash=fingerprint({"owner_id": owner, "request_hash": request_hash, "document": document}))
        async with self._transaction() as session:
            locked = (await session.execute(update(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner).values(id=t.projects.c.id).returning(t.projects))).mappings().first()
            if locked is None:
                raise NotFound
            if dict(locked) != project:
                raise Conflict
            existing = await self._retest_row(session, owner, project_id, retest_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode, existing)
            if (
                await session.execute(
                    select(t.retest_archives.c.id).where(t.retest_archives.c.project_id == project_id, t.retest_archives.c.baseline_run_id == payload.baseline.run_id, t.retest_archives.c.retest_run_id == payload.retest.run_id)
                )
            ).first():
                raise Conflict
            locked_runs = []
            for snapshot in sorted(snapshots, key=lambda source: source["run"]["id"]):
                run = await self._journal(session, owner, project_id, snapshot["run"]["id"], lock=True)
                if snapshot != await self._summary_snapshot(session, owner, project_id, run["id"], run=run):
                    raise Conflict
                locked_runs.append(run)
            await session.execute(insert(t.retest_archives).values(**row))
            for run in locked_runs:
                await self._journal_event(session, run, "retest_archived", document["created_at_ms"])
        return {**document, "archive_hash": row["archive_hash"]}
