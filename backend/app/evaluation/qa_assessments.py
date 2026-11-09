"""Verified independent all-sample assessments and immutable explicit revisions.

Post-collection double-blind evidence only: never owner votes, approval or execution.
Crypto/source verification is off-loop, then the whole snapshot is reread under the
same run lock used by task mutations. Old revisions never follow current reviews.
"""

from __future__ import annotations

import asyncio
import hmac
from collections import defaultdict
from typing import Literal

from pydantic import Field, field_validator
from sqlalchemy import func, insert, select

from app.evaluation import tables as t
from app.evaluation.criteria import assess_criteria
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_evidence import EvidenceRepository
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import POLICY, ROLES, ReviewTaskRepository, task_identifier


class AssessmentCreate(StrictDTO):
    summary_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_revision: int = Field(ge=0, le=999, strict=True)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


class AssessmentRepository(ReviewTaskRepository, SummaryRepository):
    async def _assessment_snapshot(self, session, owner, project_id, run_id, *, run=None):
        source = await self._summary_snapshot(session, owner, project_id, run_id, run=run, include_owner_reviews=False)
        source["tasks"] = [dict(r) for r in (await session.execute(select(t.review_tasks).where(t.review_tasks.c.run_id == run_id).order_by(t.review_tasks.c.id).limit(10001))).mappings()]
        if len(source["tasks"]) > 10000:
            raise Conflict
        for key, table, bound, order in (
            ("assignments", t.review_task_assignments, 30001, t.review_task_assignments.c.role),
            ("decisions", t.review_task_decisions, 30001, t.review_task_decisions.c.role),
            ("resolutions", t.review_task_resolutions, 20001, t.review_task_resolutions.c.revision),
        ):
            statement = select(table).join(t.review_tasks, (table.c.task_id == t.review_tasks.c.id) & (table.c.round == t.review_tasks.c.round)).where(t.review_tasks.c.run_id == run_id).order_by(table.c.task_id, order).limit(bound)
            source[key] = [dict(r) for r in (await session.execute(statement)).mappings()]
            if len(source[key]) >= bound:
                raise Conflict
        return source

    def _verify_assessment(self, owner, source):
        try:
            return self._verified_assessment(owner, source)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise Conflict from None

    def _verified_assessment(self, owner, source):
        ordered = EvidenceRepository._verify_source(source)
        run, plan = source["run"], source["plan"]
        total = run["request_count"]
        if total != len(ordered) or [r["ordinal"] for r in source["dispatches"]] != list(range(1, total + 1)):
            raise Conflict
        outputs = {r["ordinal"]: r for r in source["outputs"]}
        if len(outputs) != len(source["outputs"]) or not set(outputs).issubset(range(1, total + 1)):
            raise Conflict
        grouped = {name: defaultdict(list) for name in ("assignments", "decisions", "resolutions")}
        for name, groups in grouped.items():
            for row in source[name]:
                groups[row["task_id"]].append(row)
        task_ids = {task["id"] for task in source["tasks"]}
        if len(task_ids) != len(source["tasks"]) or any(not set(groups).issubset(task_ids) for groups in grouped.values()):
            raise Conflict
        tasks_by_ordinal = defaultdict(list)
        for task in source["tasks"]:
            task_identifier(task["id"])
            if task["owner_id"] != owner or task["project_id"] != run["project_id"] or task["run_id"] != run["id"] or task["ordinal"] not in range(1, total + 1):
                raise Conflict
            if type(task["round"]) is not int or not 1 <= task["round"] <= 10 or type(task["revision"]) is not int or not 1 <= task["revision"] <= 10000 or task["status"] not in {"queued", "in_review", "escalated", "resolved", "cancelled"}:
                raise Conflict
            tasks_by_ordinal[task["ordinal"]].append(task)
        counts = {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 0}
        collected, commitments, conflict_found = 0, [], False
        for dispatch in source["dispatches"]:
            ordinal = dispatch["ordinal"]
            output = outputs.get(ordinal)
            if dispatch["project_id"] != run["project_id"] or dispatch["run_id"] != run["id"] or (output and (output["project_id"] != run["project_id"] or output["run_id"] != run["id"])):
                raise Conflict
            case_source = {**source, "dispatch": dispatch, "evidence": output, "reviews": []}
            case = EvidenceRepository._verify_case(owner, case_source, self._evidence_protection(), ordered)
            collected += case["output"] is not None
            outcomes, refs, pending = [], [], False
            for task in tasks_by_ordinal[ordinal]:
                actors = self._verify_definition(task)
                if task["case_hash"] != case["case_hash"]:
                    raise Conflict
                assignments = grouped["assignments"][task["id"]]
                decisions, resolutions = grouped["decisions"][task["id"]], grouped["resolutions"][task["id"]]
                if len(assignments) != 3 or {a["role"] for a in assignments} != set(ROLES):
                    raise Conflict
                for row in [*assignments, *decisions, *resolutions]:
                    if row["round"] != task["round"] or row["task_id"] != task["id"]:
                        raise Conflict
                decision_roles = {d["role"] for d in decisions}
                for assignment in assignments:
                    if assignment["actor_id"] != actors[assignment["role"]] or assignment["status"] not in {"offered", "active", "submitted", "released"} or (assignment["status"] == "submitted") != (assignment["role"] in decision_roles):
                        raise Conflict
                self._verify_decisions(task, {"source": case_source, "decisions": decisions, "resolutions": resolutions})
                latest = resolutions[-1] if resolutions else None
                final = latest is not None and latest["document"]["outcome"] in {"pass", "fail"}
                if task["status"] == "resolved" and not final:
                    raise Conflict
                if task["status"] not in {"resolved", "cancelled"} and final:
                    raise Conflict
                if task["status"] == "escalated" and (latest is None or final):
                    raise Conflict
                if task["status"] == "resolved":
                    outcomes.append(latest["document"]["outcome"])
                elif task["status"] == "escalated":
                    outcomes.append("uncertain")
                else:
                    pending = True
                refs.append(
                    {
                        "task_id": task["id"],
                        "subject_hash": task["subject_hash"],
                        "round": task["round"],
                        "task_revision": task["revision"],
                        "status": task["status"],
                        "resolution_revision": latest["revision"] if latest else 0,
                        "resolution_hash": latest["resolution_hash"] if latest else None,
                    }
                )
            conflicting = len(set(outcomes) - {"uncertain"}) > 1
            conflict_found |= conflicting
            outcome = "unreviewed" if pending or not outcomes else "uncertain" if "uncertain" in outcomes or conflicting else outcomes[0]
            if outcome == "pass" and case["output"] is None:
                raise Conflict
            counts[outcome] += 1
            commitments.append({"ordinal": ordinal, "case_hash": case["case_hash"], "outcome": outcome, "tasks": refs})
        blockers = []
        if run["status"] != "recording_finished":
            blockers.append("collection_not_finished")
        if collected != total:
            blockers.append("technical_incomplete")
        if counts["unreviewed"]:
            blockers.append("independent_review_incomplete")
        if counts["uncertain"]:
            blockers.append("uncertain")
        if conflict_found:
            blockers.append("conflicting_independent_resolutions")
        result = {
            "schema": "qa-independent-assessment-preview.v1",
            "scope": "verified_independent_assessment_preview",
            "policy": {"id": POLICY, "population": "all_frozen_effectiveness_samples", "timing": "post_collection_assessment"},
            "run_id": run["id"],
            "run_status": run["status"],
            "project_id": run["project_id"],
            "component_id": plan["component_id"],
            "component_name": source["component"]["name_at_link"],
            "plan_id": plan["id"],
            "plan_label": plan["version_label"],
            "plan_hash": plan["definition_hash"],
            "counts": counts,
            "technical_counts": {"collected": collected, "other": total - collected},
            "human_pass_rate": {"numerator": counts["pass"], "denominator": total, "value": counts["pass"] / total},
            "readiness": "provisional" if blockers else "review_complete",
            "blockers": blockers,
            "acceptance": "not_approved",
            "cases": commitments,
        }
        if "acceptance_criteria" in plan["definition"]:
            result["criteria_evaluation"] = assess_criteria(plan["definition"]["acceptance_criteria"], counts["pass"], total, blockers)
        return {**result, "summary_hash": fingerprint(result)}

    async def get_preview(self, owner, project_id, run_id):
        async with self.sf() as session:
            snapshot = await self._assessment_snapshot(session, owner, project_id, run_id)
        result = await asyncio.to_thread(self._verify_assessment, owner, snapshot)
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            if snapshot != await self._assessment_snapshot(session, owner, project_id, run_id, run=run):
                raise Conflict
            await self._journal_event(session, run, "independent_assessment_opened", self._time())
        return result

    async def _assessment_row(self, session, owner, project_id, run_id, assessment_id):
        await self._journal(session, owner, project_id, run_id)
        row = (
            (await session.execute(select(t.run_assessments).where(t.run_assessments.c.id == assessment_id, t.run_assessments.c.owner_id == owner, t.run_assessments.c.project_id == project_id, t.run_assessments.c.run_id == run_id)))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    @staticmethod
    def _decode_assessment(row):
        try:
            document = row["document"]
            expected = fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": document})
            if not hmac.compare_digest(expected, row["assessment_hash"]) or document["schema"] != "qa-run-assessment-revision.v1" or document["scope"] != "immutable_independent_assessment" or document["acceptance"] != "not_approved":
                raise ValueError
            if any(document[key] != row[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms")) or document["assessment"]["summary_hash"] != row["summary_hash"]:
                raise ValueError
            return {**document, "assessment_hash": row["assessment_hash"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Assessment integrity check failed") from None

    async def get_assessment(self, owner, project_id, run_id, assessment_id):
        task_identifier(assessment_id)
        async with self.sf() as session:
            row = await self._assessment_row(session, owner, project_id, run_id, assessment_id)
        if row is None:
            raise NotFound
        return await asyncio.to_thread(self._decode_assessment, row)

    async def list_assessments(self, owner, project_id, run_id):
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            columns = [t.run_assessments.c[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms", "summary_hash", "assessment_hash")]
            return [
                dict(row)
                for row in (
                    await session.execute(
                        select(*columns).where(t.run_assessments.c.owner_id == owner, t.run_assessments.c.project_id == project_id, t.run_assessments.c.run_id == run_id).order_by(t.run_assessments.c.revision.desc()).limit(100)
                    )
                ).mappings()
            ]

    async def create_assessment(self, owner, project_id, run_id, assessment_id, payload):
        task_identifier(assessment_id)
        payload = AssessmentCreate.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            existing = await self._assessment_row(session, owner, project_id, run_id, assessment_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode_assessment, existing)
            snapshot = await self._assessment_snapshot(session, owner, project_id, run_id)
        assessment = await asyncio.to_thread(self._verify_assessment, owner, snapshot)
        if assessment["summary_hash"] != payload.summary_hash:
            raise Conflict
        document = {
            "schema": "qa-run-assessment-revision.v1",
            "scope": "immutable_independent_assessment",
            "id": assessment_id,
            "project_id": project_id,
            "run_id": run_id,
            "revision": payload.expected_previous_revision + 1,
            "created_at_ms": self._time(),
            "assessment": assessment,
            "acceptance": "not_approved",
        }
        assessment_hash = await asyncio.to_thread(fingerprint, {"owner_id": owner, "request_hash": request_hash, "document": document})
        row = {key: document[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms")}
        row.update(owner_id=owner, request_hash=request_hash, summary_hash=payload.summary_hash, document=document, assessment_hash=assessment_hash)
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            existing = await self._assessment_row(session, owner, project_id, run_id, assessment_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode_assessment, existing)
            if snapshot != await self._assessment_snapshot(session, owner, project_id, run_id, run=run):
                raise Conflict
            previous = (await session.execute(select(func.max(t.run_assessments.c.revision)).where(t.run_assessments.c.run_id == run_id))).scalar_one() or 0
            if previous != payload.expected_previous_revision:
                raise Conflict
            await session.execute(insert(t.run_assessments).values(**row))
            await self._journal_event(session, run, "independent_assessment_archived", document["created_at_ms"])
        return {**document, "assessment_hash": assessment_hash}
