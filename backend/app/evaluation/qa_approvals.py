"""Explicit, revisioned human formal approval over immutable assessments.

Approval is a decision an identified human approver records for a pinned
independent assessment revision. Case outcomes, threshold arithmetic and
review completeness never create an approval by themselves; missing evidence,
unfinished review or a non-met frozen threshold refuse the write. Revocation
appends a new revision with a required reason. The stored assessment and all
historical evidence stay unchanged.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, insert, select

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_assessments import AssessmentRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import POLICY

PROJECT_CHAIN_ROW_LIMIT = 5000
PROJECT_CHAIN_RUN_LIMIT = 1000


def approval_identifier(value):
    if type(value) is not str or len(value) != 32 or any(c not in "0123456789abcdef" for c in value):
        raise NotFound
    return value


class ApprovalCreate(StrictDTO):
    assessment_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    assessment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_previous_revision: int = Field(ge=0, le=999, strict=True)
    approver_id: str
    decision: Literal["approved", "revoked"]
    note: str | None = Field(default=None, max_length=2000)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value

    @field_validator("approver_id")
    @classmethod
    def canonical_approver(cls, value):
        try:
            if str(UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("Canonical account ID required") from None
        return value

    @field_validator("note")
    @classmethod
    def unicode_text(cls, value):
        if value is None:
            return value
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid text") from None
        return value

    @model_validator(mode="after")
    def revocation_reason(self):
        if self.decision == "revoked" and self.note is None:
            raise ValueError("A revocation reason is required")
        return self


class SignoffPolicySet(StrictDTO):
    required_distinct_approvers: int = Field(ge=1, le=10, strict=True)
    expected_previous_revision: int = Field(ge=0, le=999, strict=True)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


class ApprovalRepository(AssessmentRepository):
    async def _run_actors(self, session, run_id):
        actors: set[str] = set()
        rows = (await session.execute(select(t.review_tasks).where(t.review_tasks.c.run_id == run_id).order_by(t.review_tasks.c.id).limit(10001))).mappings()
        count = 0
        for row in rows:
            count += 1
            actors.update(self._verify_definition(dict(row)).values())
        if count > 10000:
            raise Conflict
        return frozenset(actors)

    async def _approval_snapshot(self, session, owner, project_id, run_id, assessment_id):
        run = await self._journal(session, owner, project_id, run_id)
        row = await self._assessment_row(session, owner, project_id, run_id, assessment_id)
        if row is None:
            raise NotFound
        return {"run": run, "assessment": row, "actors": await self._run_actors(session, run_id)}

    def _verify_approval_target(self, owner, snapshot, payload):
        try:
            run = snapshot["run"]
            row = snapshot["assessment"]
            actors = snapshot["actors"]
        except (KeyError, TypeError):
            raise Conflict from None
        assessment = self._decode_assessment(row)["assessment"]
        if assessment["summary_hash"] != row["summary_hash"] or row["assessment_hash"] != payload.assessment_hash:
            raise Conflict
        if run["status"] != "recording_finished" or assessment["run_status"] != "recording_finished":
            raise Conflict
        if assessment["readiness"] != "review_complete" or assessment["blockers"]:
            raise Conflict
        if payload.approver_id == owner or payload.approver_id in actors:
            raise Conflict
        criteria = assessment.get("criteria_evaluation")
        if criteria is not None and criteria.get("status") != "met":
            raise Conflict
        return assessment

    async def _approval_row(self, session, owner, project_id, run_id, approval_id):
        await self._journal(session, owner, project_id, run_id)
        row = (
            (
                await session.execute(
                    select(t.run_approvals).where(
                        t.run_approvals.c.id == approval_id,
                        t.run_approvals.c.owner_id == owner,
                        t.run_approvals.c.project_id == project_id,
                        t.run_approvals.c.run_id == run_id,
                    )
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    @staticmethod
    def _decode_approval(row):
        try:
            document = row["document"]
            expected = fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": document})
            if not hmac.compare_digest(expected, row["approval_hash"]):
                raise ValueError
            if document["schema"] != "qa-run-formal-approval.v1" or document["scope"] != "formal_approval_decision":
                raise ValueError
            if document["decision"] != row["decision"] or document["decision"] not in {"approved", "revoked"}:
                raise ValueError
            if document["assessment"]["id"] != row["assessment_id"] or document["assessment"]["assessment_hash"] != row["assessment_hash"]:
                raise ValueError
            if document["approver_id"] != row["approver_id"] or document["recorded_by"] != row["owner_id"]:
                raise ValueError
            if any(document[key] != row[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms")):
                raise ValueError
            return {**document, "approval_hash": row["approval_hash"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Approval integrity check failed") from None

    async def get_approval(self, owner, project_id, run_id, approval_id):
        approval_identifier(approval_id)
        async with self.sf() as session:
            row = await self._approval_row(session, owner, project_id, run_id, approval_id)
        if row is None:
            raise NotFound
        return await asyncio.to_thread(self._decode_approval, row)

    async def list_approvals(self, owner, project_id, run_id):
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            columns = [t.run_approvals.c[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms", "assessment_id", "assessment_hash", "approver_id", "decision", "approval_hash")]
            return [
                dict(row)
                for row in (
                    await session.execute(select(*columns).where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id, t.run_approvals.c.run_id == run_id).order_by(t.run_approvals.c.revision.desc()).limit(100))
                ).mappings()
            ]

    async def list_approval_audit(self, owner, project_id, run_id):
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            statement = select(t.approval_audit).where(t.approval_audit.c.project_id == project_id, t.approval_audit.c.run_id == run_id).order_by(t.approval_audit.c.sequence).limit(1000)
            return [dict(row) for row in (await session.execute(statement)).mappings()]

    @classmethod
    def _chain_blockers(cls, approvals, audit):
        blockers = set()
        if len(approvals) > 1000 or len(audit) > 1000:
            blockers.add("chain_too_long")
        if len(approvals) != len(audit):
            blockers.add("event_count_mismatch")
        if any(row["revision"] != index + 1 for index, row in enumerate(approvals)):
            blockers.add("revision_gap")
        if any(row["sequence"] != index + 1 for index, row in enumerate(audit)):
            blockers.add("sequence_gap")
        for approval_row, event in zip(approvals, audit):
            try:
                matched = (
                    event["approval_id"] == approval_row["id"] and event["revision"] == approval_row["revision"] and event["action"] == approval_row["decision"] and hmac.compare_digest(event["subject_hash"], approval_row["approval_hash"])
                )
            except (TypeError, ValueError):
                matched = False
            if not matched:
                blockers.add("event_mismatch")
                break
        for approval_row in approvals:
            try:
                cls._decode_approval(dict(approval_row))
            except RequestProtectionError:
                blockers.add("approval_integrity_failed")
                break
        return blockers

    async def verify_approval_chain(self, owner, project_id, run_id):
        """Read-only integrity check over the run's approvals and ordered audit."""
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            approvals = (
                (await session.execute(select(t.run_approvals).where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id, t.run_approvals.c.run_id == run_id).order_by(t.run_approvals.c.revision).limit(1001)))
                .mappings()
                .all()
            )
            audit = (await session.execute(select(t.approval_audit).where(t.approval_audit.c.project_id == project_id, t.approval_audit.c.run_id == run_id).order_by(t.approval_audit.c.sequence).limit(1001))).mappings().all()
        blockers = self._chain_blockers(approvals, audit)
        return {
            "schema": "qa-approval-chain.v1",
            "scope": "approval_audit_chain_only",
            "status": "verified" if not blockers else "broken",
            "approvals": len(approvals),
            "events": len(audit),
            "blockers": sorted(blockers),
        }

    async def verify_project_approval_chains(self, owner, project_id):
        """Aggregate read-only chain status over every run in the project."""
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            approvals_filter = (t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id)
            approvals_count = (await session.execute(select(func.count()).select_from(t.run_approvals).where(*approvals_filter))).scalar_one()
            audit_count = (await session.execute(select(func.count()).select_from(t.approval_audit).where(t.approval_audit.c.project_id == project_id))).scalar_one()
            run_count = (await session.execute(select(func.count(func.distinct(t.run_approvals.c.run_id))).where(*approvals_filter))).scalar_one()
            if approvals_count > PROJECT_CHAIN_ROW_LIMIT or audit_count > PROJECT_CHAIN_ROW_LIMIT or run_count > PROJECT_CHAIN_RUN_LIMIT:
                return {
                    "schema": "qa-approval-chain-summary.v1",
                    "scope": "project_approval_audit_chains_only",
                    "status": "unverifiable",
                    "runs": run_count,
                    "verified_runs": 0,
                    "broken_runs": 0,
                    "approvals": approvals_count,
                    "events": audit_count,
                    "blockers": ["project_chain_too_long"],
                }
            approvals = (await session.execute(select(t.run_approvals).where(*approvals_filter).order_by(t.run_approvals.c.run_id, t.run_approvals.c.revision))).mappings().all()
            audit = (await session.execute(select(t.approval_audit).where(t.approval_audit.c.project_id == project_id).order_by(t.approval_audit.c.run_id, t.approval_audit.c.sequence))).mappings().all()
        approvals_by_run: dict[str, list] = {}
        audit_by_run: dict[str, list] = {}
        for row in approvals:
            approvals_by_run.setdefault(row["run_id"], []).append(row)
        for row in audit:
            audit_by_run.setdefault(row["run_id"], []).append(row)
        blockers = set()
        verified_runs = 0
        broken_runs = 0
        for run_id in set(approvals_by_run) | set(audit_by_run):
            run_approvals = approvals_by_run.get(run_id, [])
            run_audit = audit_by_run.get(run_id, [])
            run_blockers = self._chain_blockers(run_approvals, run_audit) if run_approvals else {"orphan_audit"}
            if run_blockers:
                blockers.update(run_blockers)
                broken_runs += 1
            else:
                verified_runs += 1
        return {
            "schema": "qa-approval-chain-summary.v1",
            "scope": "project_approval_audit_chains_only",
            "status": "verified" if not blockers else "broken",
            "runs": verified_runs + broken_runs,
            "verified_runs": verified_runs,
            "broken_runs": broken_runs,
            "approvals": len(approvals),
            "events": len(audit),
            "blockers": sorted(blockers),
        }

    async def approval_signoff_progress(self, owner, project_id, run_id):
        """Read-only aggregate sign-off progress; no multi-level policy is defined."""
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            rows = (
                (
                    await session.execute(
                        select(t.run_approvals.c.revision, t.run_approvals.c.decision, t.run_approvals.c.approver_id)
                        .where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id, t.run_approvals.c.run_id == run_id)
                        .order_by(t.run_approvals.c.revision)
                        .limit(1001)
                    )
                )
                .mappings()
                .all()
            )
        latest = rows[-1] if rows else None
        approvers = {row["approver_id"] for row in rows}
        approved = [row for row in rows if row["decision"] == "approved"]
        return {
            "schema": "qa-approval-signoff.v1",
            "scope": "approval_signoff_progress_only",
            "policy": "not_defined",
            "required_distinct_approvers": None,
            "revisions": len(rows),
            "distinct_approvers": len(approvers),
            "distinct_approved_approvers": len({row["approver_id"] for row in approved}),
            "approved_revisions": len(approved),
            "revoked_revisions": len(rows) - len(approved),
            "latest_revision": latest["revision"] if latest else None,
            "latest_decision": latest["decision"] if latest else None,
            "multi_level_satisfied": None,
            "blockers": ["multi_level_policy_not_defined", "approver_login_not_implemented"],
        }

    @staticmethod
    def _decode_signoff_policy(row):
        try:
            document = row["document"]
            expected = fingerprint({"owner_id": row["owner_id"], "request_hash": row["request_hash"], "document": document})
            if not hmac.compare_digest(expected, row["policy_hash"]):
                raise ValueError
            if document["schema"] != "qa-approval-signoff-policy.v1" or document["scope"] != "advisory_signoff_policy_only" or document["advisory"] is not True or document["enforcement"] != "none":
                raise ValueError
            if any(document[key] != row[key] for key in ("project_id", "revision", "required_distinct_approvers", "created_at_ms")):
                raise ValueError
            return {**document, "policy_hash": row["policy_hash"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Sign-off policy integrity check failed") from None

    async def get_signoff_policy(self, owner, project_id):
        """Latest advisory sign-off policy; metadata only, read-only."""
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            row = (
                (
                    await session.execute(
                        select(t.approval_signoff_policies).where(t.approval_signoff_policies.c.project_id == project_id, t.approval_signoff_policies.c.owner_id == owner).order_by(t.approval_signoff_policies.c.revision.desc()).limit(1)
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFound
        return self._decode_signoff_policy(dict(row))

    async def set_signoff_policy(self, owner, project_id, *, required_distinct_approvers, expected_previous_revision):
        """Append an advisory policy revision; never enforce or approve."""
        if type(required_distinct_approvers) is not int or not 1 <= required_distinct_approvers <= 10 or type(expected_previous_revision) is not int or not 0 <= expected_previous_revision <= 999:
            raise Conflict
        request_hash = fingerprint({"required_distinct_approvers": required_distinct_approvers, "expected_previous_revision": expected_previous_revision})
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            latest = (await session.execute(select(func.max(t.approval_signoff_policies.c.revision)).where(t.approval_signoff_policies.c.project_id == project_id))).scalar_one()
            revision = expected_previous_revision + 1
            existing = (await session.execute(select(t.approval_signoff_policies).where(t.approval_signoff_policies.c.project_id == project_id, t.approval_signoff_policies.c.revision == revision))).mappings().first()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return self._decode_signoff_policy(dict(existing))
            if (latest or 0) != expected_previous_revision:
                raise Conflict
        created_at_ms = self._time()
        document = {
            "schema": "qa-approval-signoff-policy.v1",
            "scope": "advisory_signoff_policy_only",
            "project_id": project_id,
            "revision": revision,
            "required_distinct_approvers": required_distinct_approvers,
            "created_at_ms": created_at_ms,
            "advisory": True,
            "enforcement": "none",
        }
        policy_hash = await asyncio.to_thread(fingerprint, {"owner_id": owner, "request_hash": request_hash, "document": document})
        async with self._transaction() as session:
            await self._project(session, owner, project_id)
            await session.execute(
                insert(t.approval_signoff_policies).values(
                    project_id=project_id, revision=revision, owner_id=owner, required_distinct_approvers=required_distinct_approvers, created_at_ms=created_at_ms, request_hash=request_hash, document=document, policy_hash=policy_hash
                )
            )
        return {**document, "policy_hash": policy_hash}

    async def list_project_approvals(self, owner, project_id):
        """Latest approval revision per run; metadata only, read-only."""
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            latest = (
                select(t.run_approvals.c.run_id, func.max(t.run_approvals.c.revision).label("revision")).where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id).group_by(t.run_approvals.c.run_id).subquery()
            )
            columns = [t.run_approvals.c[key] for key in ("run_id", "id", "revision", "decision", "assessment_id", "assessment_hash", "created_at_ms")]
            statement = (
                select(*columns)
                .join(latest, (t.run_approvals.c.run_id == latest.c.run_id) & (t.run_approvals.c.revision == latest.c.revision))
                .where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id)
                .order_by(t.run_approvals.c.created_at_ms.desc())
                .limit(200)
            )
            return [dict(row) for row in (await session.execute(statement)).mappings()]

    async def preview_approval(self, owner, project_id, run_id, assessment_id, approver_id):
        """Read-only eligibility preview; never writes an approval or audit row."""
        approval_identifier(assessment_id)
        try:
            if str(UUID(approver_id)) != approver_id:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise ValueError("Canonical account ID required") from None
        async with self.sf() as session:
            snapshot = await self._approval_snapshot(session, owner, project_id, run_id, assessment_id)
            latest = (
                (
                    await session.execute(
                        select(t.run_approvals.c.revision, t.run_approvals.c.decision)
                        .where(t.run_approvals.c.owner_id == owner, t.run_approvals.c.project_id == project_id, t.run_approvals.c.run_id == run_id)
                        .order_by(t.run_approvals.c.revision.desc())
                        .limit(1)
                    )
                )
                .mappings()
                .first()
            )
        decoded = await asyncio.to_thread(self._decode_assessment, snapshot["assessment"])
        body = decoded["assessment"]
        blockers = []
        if snapshot["run"]["status"] != "recording_finished" or body["run_status"] != "recording_finished":
            blockers.append("collection_not_finished")
        if body["readiness"] != "review_complete" or body["blockers"]:
            blockers.extend(body["blockers"] or ["independent_review_incomplete"])
        criteria = body.get("criteria_evaluation")
        if criteria is not None and criteria.get("status") != "met":
            blockers.append("criteria_" + str(criteria.get("status", "incomplete")))
        if approver_id == owner:
            blockers.append("approver_is_owner")
        if approver_id in snapshot["actors"]:
            blockers.append("approver_is_review_actor")
        row = snapshot["assessment"]
        return {
            "schema": "qa-approval-preflight.v1",
            "scope": "read_only_formal_approval_preflight",
            "project_id": project_id,
            "run_id": run_id,
            "assessment": {"id": row["id"], "revision": row["revision"], "assessment_hash": row["assessment_hash"]},
            "approver_id": approver_id,
            "eligible": not blockers,
            "blockers": sorted(set(blockers)),
            "readiness": body["readiness"],
            "criteria": {"status": criteria["status"] if criteria is not None else "not_defined"},
            "separation": {"approver_not_owner": approver_id != owner, "approver_not_review_actor": approver_id not in snapshot["actors"]},
            "latest_approval": {"revision": latest["revision"], "decision": latest["decision"]} if latest else None,
            "approval": "not_recorded",
        }

    @staticmethod
    def _document(owner, approval_id, project_id, run_id, revision, created_at_ms, row, assessment, payload):
        criteria = assessment.get("criteria_evaluation") or {"status": "not_defined", "approval": "not_approved"}
        return {
            "schema": "qa-run-formal-approval.v1",
            "scope": "formal_approval_decision",
            "policy": {
                "id": POLICY,
                "population": "all_frozen_effectiveness_samples",
                "source": "immutable_independent_assessment",
                "separation": "approver_not_owner_or_independent_reviewer",
            },
            "id": approval_id,
            "project_id": project_id,
            "run_id": run_id,
            "revision": revision,
            "created_at_ms": created_at_ms,
            "recorded_by": owner,
            "assessment": {"id": row["id"], "revision": row["revision"], "assessment_hash": row["assessment_hash"], "summary_hash": row["summary_hash"]},
            "counts": assessment["counts"],
            "technical_counts": assessment["technical_counts"],
            "human_pass_rate": assessment["human_pass_rate"],
            "criteria": criteria,
            "readiness": "review_complete",
            "decision": payload.decision,
            "approver_id": payload.approver_id,
            "note": payload.note,
        }

    async def create_approval(self, owner, project_id, run_id, approval_id, payload):
        approval_identifier(approval_id)
        payload = ApprovalCreate.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            existing = await self._approval_row(session, owner, project_id, run_id, approval_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode_approval, existing)
            snapshot = await self._approval_snapshot(session, owner, project_id, run_id, payload.assessment_id)
        assessment = await asyncio.to_thread(self._verify_approval_target, owner, snapshot, payload)
        created_at_ms = self._time()
        document = self._document(owner, approval_id, project_id, run_id, payload.expected_previous_revision + 1, created_at_ms, snapshot["assessment"], assessment, payload)
        approval_hash = await asyncio.to_thread(fingerprint, {"owner_id": owner, "request_hash": request_hash, "document": document})
        row = {key: document[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms")}
        row.update(
            owner_id=owner,
            request_hash=request_hash,
            assessment_id=payload.assessment_id,
            assessment_hash=payload.assessment_hash,
            approver_id=payload.approver_id,
            decision=payload.decision,
            document=document,
            approval_hash=approval_hash,
        )
        async with self._transaction() as session:
            await self._journal(session, owner, project_id, run_id, lock=True)
            existing = await self._approval_row(session, owner, project_id, run_id, approval_id)
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict
                return await asyncio.to_thread(self._decode_approval, existing)
            if snapshot != await self._approval_snapshot(session, owner, project_id, run_id, payload.assessment_id):
                raise Conflict
            previous = (await session.execute(select(func.max(t.run_approvals.c.revision)).where(t.run_approvals.c.run_id == run_id))).scalar_one() or 0
            if previous != payload.expected_previous_revision:
                raise Conflict
            await session.execute(insert(t.run_approvals).values(**row))
            sequence = (await session.execute(select(func.max(t.approval_audit.c.sequence)).where(t.approval_audit.c.run_id == run_id))).scalar_one() or 0
            await session.execute(
                insert(t.approval_audit).values(
                    project_id=project_id,
                    run_id=run_id,
                    sequence=sequence + 1,
                    approval_id=approval_id,
                    revision=document["revision"],
                    # The authenticated project owner records the named approver's
                    # decision; audit keeps who actually wrote the row.
                    actor=owner,
                    action=payload.decision,
                    subject_hash=approval_hash,
                    at_ms=created_at_ms,
                )
            )
        return {**document, "approval_hash": approval_hash}
