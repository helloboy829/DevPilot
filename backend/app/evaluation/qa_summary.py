"""Verified latest-human decisions over ALL frozen QA effectiveness samples.

Read-time preview, never report approval. No network/model calls or automatic
review. Crypto is outside the run lock; one final locked reread rejects races.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.evaluation import tables as t
from app.evaluation.qa_evidence import EvidenceRepository, _binding, _open_verified
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict


class SummaryRepository(EvidenceRepository):
    async def _summary_snapshot(self, session, owner, project_id, run_id, *, run=None):
        run = run if run is not None else await self._journal(session, owner, project_id, run_id)
        source = await self._snapshot(session, owner, project_id, run_id, 1, run=run)
        definition = source["plan"]["definition"]
        if definition["limits"]["mode"] != "effectiveness" or not 1 <= run["request_count"] <= 500:
            raise Conflict
        source = {key: value for key, value in source.items() if key not in {"dispatch", "evidence", "reviews"}}
        source["run"] = run
        source["dispatches"] = [dict(row) for row in (await session.execute(select(*[c for c in t.dispatches.c if c.name != "ticket_hash"]).where(t.dispatches.c.run_id == run_id).order_by(t.dispatches.c.ordinal).limit(501))).mappings()]
        source["outputs"] = [dict(row) for row in (await session.execute(select(t.output_evidence).where(t.output_evidence.c.run_id == run_id).order_by(t.output_evidence.c.ordinal).limit(501))).mappings()]
        # Only latest encrypted decisions enter a summary. Historical notes remain
        # in the explicit per-case history view; count == max proves no revision gap.
        latest = select(t.case_reviews.c.ordinal, func.max(t.case_reviews.c.revision).label("revision"), func.count().label("history_count")).where(t.case_reviews.c.run_id == run_id).group_by(t.case_reviews.c.ordinal).subquery()
        source["latest_reviews"] = [
            dict(row)
            for row in (
                await session.execute(
                    select(t.case_reviews, latest.c.history_count)
                    .join(latest, (t.case_reviews.c.ordinal == latest.c.ordinal) & (t.case_reviews.c.revision == latest.c.revision))
                    .where(t.case_reviews.c.run_id == run_id)
                    .order_by(t.case_reviews.c.ordinal)
                    .limit(501)
                )
            ).mappings()
        ]
        return source

    @staticmethod
    def _verify_summary(owner, source, protection):
        ordered = EvidenceRepository._verify_source(source)
        run, plan = source["run"], source["plan"]
        total = run["request_count"]
        if total != len(ordered) or [row["ordinal"] for row in source["dispatches"]] != list(range(1, total + 1)):
            raise Conflict
        outputs = {row["ordinal"]: row for row in source["outputs"]}
        reviews = {row["ordinal"]: row for row in source["latest_reviews"]}
        allowed = set(range(1, total + 1))
        if not set(outputs).issubset(allowed) or not set(reviews).issubset(allowed):
            raise Conflict
        counts = {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": 0}
        collected = 0
        commitments = []
        for dispatch in source["dispatches"]:
            ordinal = dispatch["ordinal"]
            output, latest = outputs.get(ordinal), reviews.get(ordinal)
            if dispatch["project_id"] != run["project_id"] or dispatch["run_id"] != run["id"]:
                raise Conflict
            for row in (output, latest):
                if row is not None and (row["project_id"] != run["project_id"] or row["run_id"] != run["id"]):
                    raise Conflict
            # Frozen source verified ONCE above, not O(samples squared) hashing.
            snapshot = {**source, "dispatch": dispatch, "evidence": output, "reviews": []}
            case = EvidenceRepository._verify_case(owner, snapshot, protection, ordered)
            has_output = case["output"] is not None
            collected += has_output
            decision = "unreviewed"
            if latest:
                if latest["revision"] != latest["history_count"] or not 1 <= latest["revision"] <= 100 or dispatch["state"] not in {"observed", "delivery_unknown", "not_dispatched"}:
                    raise Conflict
                decision = latest["decision"]
                if decision not in {"pass", "fail", "uncertain"} or (decision == "pass" and not has_output) or latest["case_hash"] != case["case_hash"] or latest["reviewer_id"] != owner:
                    raise Conflict
                decoded = _open_verified(protection, "review", latest, _binding(owner, run, dispatch))
                if (
                    not isinstance(decoded, dict)
                    or not isinstance(decoded.get("note"), str)
                    or not 1 <= len(decoded["note"]) <= 2000
                    or decoded != {"revision": latest["revision"], "decision": decision, "actor": latest["reviewer_id"], "note": decoded["note"], "case_hash": case["case_hash"]}
                ):
                    raise Conflict
            counts[decision] += 1
            commitments.append({"ordinal": ordinal, "case_hash": case["case_hash"], "revision": latest["revision"] if latest else 0, "review_hash": latest["protected_hash"] if latest else None})
        blockers = []
        if run["status"] != "recording_finished":
            blockers.append("collection_not_finished")
        if collected != total:
            blockers.append("technical_incomplete")
        if counts["unreviewed"]:
            blockers.append("unreviewed")
        if counts["uncertain"]:
            blockers.append("uncertain")
        result = {
            "schema": "qa-human-summary.v1",
            "scope": "verified_human_summary_preview",
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
        }
        return {**result, "summary_hash": fingerprint({"summary": result, "cases": commitments})}

    async def get_summary(self, owner, project_id, run_id):
        async with self.sf() as session:
            snapshot = await self._summary_snapshot(session, owner, project_id, run_id)
        summary = await asyncio.to_thread(self._verify_summary, owner, snapshot, self._evidence_protection())
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            if snapshot != await self._summary_snapshot(session, owner, project_id, run_id, run=run):
                raise Conflict
            await self._journal_event(session, run, "human_summary_opened", self._time())
        return summary
