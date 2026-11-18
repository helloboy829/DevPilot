"""Explicit, assigned human signatures over pinned independent assessments.

Assignments grant only their aggregate summary, never project/case access.
Request events are the persistent in-app notifications and operation receipts;
they commit atomically with the existing global approval ledger and audit.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, insert, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_approvals import ApprovalCreate, ApprovalRepository, approval_identifier
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError

MAX_TIME = 253402300799000
VIEW_TTL_MS = 10 * 60_000
REQUEST_TTL_MS = 30 * 24 * 60 * 60_000


class RequestCommand(StrictDTO):
    expected_revision: int = Field(ge=1, le=3, strict=True)
    subject_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


class ApprovalRequestCreate(StrictDTO):
    assessment_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    assessment_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_id: str
    expires_at_ms: int = Field(gt=0, le=MAX_TIME, strict=True)
    share_summary: Literal[True]
    confirmed: Literal[True]

    @field_validator("share_summary", "confirmed", mode="before")
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


class SignatureCreate(RequestCommand):
    decision: Literal["approved", "revoked"]
    expected_previous_approval_revision: int = Field(ge=0, le=999, strict=True)
    view_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note")
    @classmethod
    def unicode_text(cls, value):
        if value is not None:
            try:
                value.encode("utf-8")
            except UnicodeError:
                raise ValueError("Invalid text") from None
        return value

    @model_validator(mode="after")
    def explicit_action(self):
        if self.decision == "approved" and self.view_id is None:
            raise ValueError("Open the assigned summary first")
        if self.decision == "revoked" and (self.note is None or self.view_id is not None):
            raise ValueError("Revocation requires a reason and no summary view")
        return self


class ApprovalRequestRepository(ApprovalRepository):
    @staticmethod
    def _receipt(row):
        keys = ("id", "project_id", "run_id", "assessment_id", "assessment_hash", "approver_id", "created_at_ms", "expires_at_ms", "subject_hash", "revision", "status", "latest_approval_id")
        return {"schema": "qa-approval-request.v1", **{key: row[key] for key in keys}}

    async def _request(self, session, actor, request_id):
        approval_identifier(request_id)
        row = (await session.execute(select(t.approval_requests).where(t.approval_requests.c.id == request_id, (t.approval_requests.c.owner_id == actor) | (t.approval_requests.c.approver_id == actor)))).mappings().first()
        if row is None:
            raise NotFound
        row = dict(row)
        events = [dict(item) for item in (await session.execute(select(t.approval_request_events).where(t.approval_request_events.c.request_id == request_id).order_by(t.approval_request_events.c.revision).limit(4))).mappings()]
        await asyncio.to_thread(self._verify_request, row, events)
        return row, events

    @classmethod
    def _verify_request(cls, row, events):
        try:
            definition = row["definition"]
            if definition["schema"] != "qa-approval-request-definition.v1" or definition["owner_id"] == definition["approver_id"]:
                raise ValueError
            if not hmac.compare_digest(fingerprint(definition), row["subject_hash"]):
                raise ValueError
            for key in ("id", "owner_id", "project_id", "run_id", "assessment_id", "assessment_hash", "approver_id", "created_at_ms", "expires_at_ms"):
                if definition[key] != row[key]:
                    raise ValueError
            ApprovalRequestCreate.model_validate(definition["request"])
            if fingerprint(definition["request"]) != row["request_hash"]:
                raise ValueError
            if any(definition["request"][key] != row[key] for key in ("assessment_id", "assessment_hash", "approver_id", "expires_at_ms")):
                raise ValueError
            if not 1 <= len(events) <= 3 or len(events) != row["revision"]:
                raise ValueError
            previous_hash, status = None, None
            for revision, event in enumerate(events, 1):
                if event["request_id"] != row["id"] or event["revision"] != revision:
                    raise ValueError
                body = {key: event[key] for key in ("request_id", "operation_id", "revision", "actor", "action", "at_ms", "request_hash", "receipt", "previous_hash")}
                if fingerprint(body) != event["event_hash"] or event["previous_hash"] != previous_hash:
                    raise ValueError
                action = event["action"]
                transitions = {(None, "requested"): "pending", ("pending", "approved"): "approved", ("pending", "cancelled"): "cancelled", ("approved", "revoked"): "revoked"}
                status = transitions[(status, action)]
                expected_actor = row["owner_id"] if action in {"requested", "cancelled"} else row["approver_id"]
                if event["actor"] != expected_actor or event["at_ms"] < row["created_at_ms"]:
                    raise ValueError
                expected = cls._receipt({**row, "revision": revision, "status": status, "latest_approval_id": event["operation_id"] if action in {"approved", "revoked"} else None})
                if event["receipt"] != expected:
                    raise ValueError
                if action == "requested" and (event["operation_id"] != row["id"] or event["request_hash"] != row["request_hash"]):
                    raise ValueError
                previous_hash = event["event_hash"]
            if events[-1]["receipt"] != cls._receipt(row):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Approval request integrity check failed") from None

    async def _source(self, session, row):
        owner, project, run = row["owner_id"], row["project_id"], row["run_id"]
        target = await self._approval_snapshot(session, owner, project, run, row["assessment_id"])
        source = await self._assessment_snapshot(session, owner, project, run, run=target["run"])
        latest = (await session.execute(select(func.max(t.run_assessments.c.revision)).where(t.run_assessments.c.run_id == run))).scalar_one()
        return {"target": target, "source": source, "latest": latest}

    def _verify_source_target(self, row, snapshot):
        payload = ApprovalRequestCreate.model_validate(row["definition"]["request"])
        assessment = self._verify_approval_target(row["owner_id"], snapshot["target"], payload)
        try:
            current = self._verify_assessment(row["owner_id"], snapshot["source"])
        except Conflict:
            raise RequestProtectionError("Approval source integrity check failed") from None
        if snapshot["latest"] != snapshot["target"]["assessment"]["revision"] or current["summary_hash"] != assessment["summary_hash"]:
            raise Conflict
        # Deliberate allowlist: case commitments, identities, labels and all raw
        # evidence stay inside the owner/review repositories.
        return {key: assessment[key] for key in ("counts", "technical_counts", "human_pass_rate", "readiness", "blockers", "summary_hash")} | {
            "criteria": assessment.get("criteria_evaluation") or {"status": "not_defined", "approval": "not_approved"}
        }

    @staticmethod
    def _command(row, payload):
        if payload.expected_revision != row["revision"] or not hmac.compare_digest(payload.subject_hash, row["subject_hash"]):
            raise Conflict

    async def _event(self, session, row, operation_id, actor, action, request_hash, previous_hash):
        receipt = self._receipt(row)
        body = dict(request_id=row["id"], operation_id=operation_id, revision=row["revision"], actor=actor, action=action, at_ms=self._time(), request_hash=request_hash, receipt=receipt, previous_hash=previous_hash)
        event_hash = await asyncio.to_thread(fingerprint, body)
        await session.execute(insert(t.approval_request_events).values(**body, event_hash=event_hash))
        return receipt

    async def create_request(self, owner, project_id, run_id, request_id, payload):
        approval_identifier(request_id)
        payload = ApprovalRequestCreate.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            await self._journal(session, owner, project_id, run_id)
            existing = (await session.execute(select(t.approval_requests.c.id).where(t.approval_requests.c.id == request_id))).scalar_one_or_none()
            if existing:
                row, events = await self._request(session, owner, request_id)
                if row["owner_id"] != owner or row["project_id"] != project_id or row["run_id"] != run_id or row["request_hash"] != request_hash:
                    raise Conflict
                return events[0]["receipt"]
            at = self._time()
            if not at < payload.expires_at_ms <= min(MAX_TIME, at + REQUEST_TTL_MS):
                raise Conflict
            definition = dict(
                schema="qa-approval-request-definition.v1",
                id=request_id,
                owner_id=owner,
                project_id=project_id,
                run_id=run_id,
                created_at_ms=at,
                **{key: getattr(payload, key) for key in ("assessment_id", "assessment_hash", "approver_id", "expires_at_ms")},
                request=payload.model_dump(),
            )
            row = {key: definition[key] for key in ("id", "owner_id", "project_id", "run_id", "assessment_id", "assessment_hash", "approver_id", "created_at_ms", "expires_at_ms")}
            row.update(definition=definition, subject_hash=fingerprint(definition), request_hash=request_hash, revision=1, status="pending", latest_approval_id=None)
            snapshot = await self._source(session, row)
        await asyncio.to_thread(self._verify_source_target, row, snapshot)
        async with self._transaction() as session:
            await self._journal(session, owner, project_id, run_id, lock=True)
            existing = (await session.execute(select(t.approval_requests.c.id).where(t.approval_requests.c.id == request_id))).scalar_one_or_none()
            if existing:
                current, events = await self._request(session, owner, request_id)
                if current["owner_id"] != owner or current["project_id"] != project_id or current["run_id"] != run_id or current["request_hash"] != request_hash:
                    raise Conflict
                return events[0]["receipt"]
            count = (await session.execute(select(func.count()).select_from(t.approval_requests).where(t.approval_requests.c.run_id == run_id))).scalar_one()
            if count >= 1000 or self._time() >= payload.expires_at_ms or snapshot != await self._source(session, row):
                raise Conflict
            await session.execute(insert(t.approval_requests).values(**row))
            return await self._event(session, row, request_id, owner, "requested", request_hash, None)

    async def get_request(self, actor, request_id):
        async with self.sf() as session:
            row, _ = await self._request(session, actor, request_id)
        return self._receipt(row)

    async def request_state(self, actor, request_id):
        async with self.sf() as session:
            row, _ = await self._request(session, actor, request_id)
            previous = (await session.execute(select(func.max(t.run_approvals.c.revision)).where(t.run_approvals.c.run_id == row["run_id"]))).scalar_one() or 0
        effectiveness = await self.effectiveness(actor, request_id)
        async with self.sf() as session:
            current, _ = await self._request(session, actor, request_id)
            latest = (await session.execute(select(func.max(t.run_approvals.c.revision)).where(t.run_approvals.c.run_id == row["run_id"]))).scalar_one() or 0
            if current != row or previous != latest:
                raise Conflict
        return {"schema": "qa-approval-request-state.v1", "request": self._receipt(row), "approval_revision": latest, "effectiveness": effectiveness}

    async def get_operation(self, actor, request_id, operation_id):
        approval_identifier(operation_id)
        async with self.sf() as session:
            _, events = await self._request(session, actor, request_id)
        for event in events:
            if event["operation_id"] == operation_id:
                return event["receipt"]
        raise NotFound

    async def inbox(self, actor):
        async with self.sf() as session:
            ids = (await session.execute(select(t.approval_requests.c.id).where(t.approval_requests.c.approver_id == actor).order_by(t.approval_requests.c.created_at_ms.desc(), t.approval_requests.c.id).limit(101))).scalars().all()
            requests = [self._receipt((await self._request(session, actor, request_id))[0]) for request_id in ids[:100]]
        return {"schema": "qa-approval-inbox.v1", "requests": requests, "truncated": len(ids) > 100}

    async def notifications(self, actor):
        async with self.sf() as session:
            statement = (
                select(t.approval_request_events)
                .join(t.approval_requests, t.approval_request_events.c.request_id == t.approval_requests.c.id)
                .where((t.approval_requests.c.owner_id == actor) | (t.approval_requests.c.approver_id == actor))
                .order_by(t.approval_request_events.c.at_ms.desc(), t.approval_request_events.c.request_id, t.approval_request_events.c.revision.desc())
                .limit(101)
            )
            events = [dict(row) for row in (await session.execute(statement)).mappings()]
            for request_id in {event["request_id"] for event in events[:100]}:
                await self._request(session, actor, request_id)
        notices = [{key: item[key] for key in ("request_id", "operation_id", "action", "at_ms", "revision")} for item in reversed(events[:100])]
        return {"schema": "qa-approval-notifications.v1", "notifications": notices, "truncated": len(events) > 100}

    @staticmethod
    def _decode_view(row, request, actor):
        try:
            document = row["document"]
            expected = fingerprint({"request_hash": row["request_hash"], "document": document})
            if expected != row["view_hash"] or row["request_id"] != request["id"] or row["actor"] != actor or actor != request["approver_id"]:
                raise ValueError
            if document["schema"] != "qa-approval-summary-view.v1" or document["request_id"] != row["request_id"] or document["view_id"] != row["id"] or document["subject_hash"] != request["subject_hash"]:
                raise ValueError
            if document["revision"] != row["request_revision"] or document["expires_at_ms"] != row["expires_at_ms"] or document["summary"]["summary_hash"] != row["summary_hash"]:
                raise ValueError
            return {**document, "view_hash": row["view_hash"]}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestProtectionError("Approval summary view integrity check failed") from None

    async def _view(self, session, actor, request, view_id):
        row = (await session.execute(select(t.approval_request_views).where(t.approval_request_views.c.id == view_id, t.approval_request_views.c.request_id == request["id"], t.approval_request_views.c.actor == actor))).mappings().first()
        if row is None:
            raise NotFound
        row = dict(row)
        return row, await asyncio.to_thread(self._decode_view, row, request, actor)

    async def get_view(self, actor, request_id, view_id):
        approval_identifier(view_id)
        async with self.sf() as session:
            request, _ = await self._request(session, actor, request_id)
            if actor != request["approver_id"]:
                raise NotFound
            _, receipt = await self._view(session, actor, request, view_id)
        return receipt

    async def open_summary(self, actor, request_id, view_id, payload):
        approval_identifier(view_id)
        payload = RequestCommand.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            row, _ = await self._request(session, actor, request_id)
            if actor != row["approver_id"]:
                raise Conflict
            existing = (await session.execute(select(t.approval_request_views.c.id).where(t.approval_request_views.c.id == view_id))).scalar_one_or_none()
            if existing:
                view, receipt = await self._view(session, actor, row, view_id)
                if view["request_hash"] != request_hash:
                    raise Conflict
                return receipt
            self._command(row, payload)
            if row["status"] != "pending" or self._time() >= row["expires_at_ms"]:
                raise Conflict
            snapshot = await self._source(session, row)
        summary = await asyncio.to_thread(self._verify_source_target, row, snapshot)
        expiry = min(self._time() + VIEW_TTL_MS, row["expires_at_ms"])
        document = dict(schema="qa-approval-summary-view.v1", request_id=request_id, view_id=view_id, revision=row["revision"], subject_hash=row["subject_hash"], expires_at_ms=expiry, summary=summary)
        view_hash = await asyncio.to_thread(fingerprint, {"request_hash": request_hash, "document": document})
        async with self._transaction() as session:
            await self._journal(session, row["owner_id"], row["project_id"], row["run_id"], lock=True)
            current, _ = await self._request(session, actor, request_id)
            existing = (await session.execute(select(t.approval_request_views.c.id).where(t.approval_request_views.c.id == view_id))).scalar_one_or_none()
            if existing:
                view, receipt = await self._view(session, actor, current, view_id)
                if view["request_hash"] != request_hash:
                    raise Conflict
                return receipt
            if row != current or self._time() >= expiry or snapshot != await self._source(session, current):
                raise Conflict
            count = (await session.execute(select(func.count()).select_from(t.approval_request_views).where(t.approval_request_views.c.request_id == request_id))).scalar_one()
            if count >= 100:
                raise Conflict
            await session.execute(
                insert(t.approval_request_views).values(
                    id=view_id, request_id=request_id, actor=actor, request_revision=row["revision"], request_hash=request_hash, summary_hash=summary["summary_hash"], expires_at_ms=expiry, document=document, view_hash=view_hash
                )
            )
        return {**document, "view_hash": view_hash}

    @staticmethod
    def _existing(events, operation_id, actor, action, request_hash):
        for event in events:
            if event["operation_id"] == operation_id:
                if event["actor"] != actor or event["action"] != action or event["request_hash"] != request_hash:
                    raise Conflict
                return event["receipt"]
        return None

    async def cancel(self, actor, request_id, operation_id, payload):
        approval_identifier(operation_id)
        payload = RequestCommand.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            row, _ = await self._request(session, actor, request_id)
        async with self._transaction() as session:
            await self._journal(session, row["owner_id"], row["project_id"], row["run_id"], lock=True)
            row, events = await self._request(session, actor, request_id)
            if actor != row["owner_id"]:
                raise Conflict
            existing = self._existing(events, operation_id, actor, "cancelled", request_hash)
            if existing is not None:
                return existing
            self._command(row, payload)
            if row["status"] != "pending":
                raise Conflict
            row = {**row, "status": "cancelled", "revision": row["revision"] + 1}
            await session.execute(update(t.approval_requests).where(t.approval_requests.c.id == request_id).values(status=row["status"], revision=row["revision"]))
            return await self._event(session, row, operation_id, actor, "cancelled", request_hash, events[-1]["event_hash"])

    async def _signed_document(self, session, row):
        signed = await self._approval_row(session, row["owner_id"], row["project_id"], row["run_id"], row["latest_approval_id"])
        if signed is None:
            raise RequestProtectionError("Approval signature missing")
        event = (await session.execute(select(t.approval_request_events).where(t.approval_request_events.c.request_id == row["id"], t.approval_request_events.c.operation_id == row["latest_approval_id"]))).mappings().first()
        if event is None or event["request_hash"] != signed["request_hash"] or event["actor"] != row["approver_id"] or event["action"] != signed["decision"]:
            raise RequestProtectionError("Approval signature event mismatch")
        document = await asyncio.to_thread(self._decode_approval, signed)
        if (
            document["schema"] != "qa-run-formal-approval.v2"
            or document["authentication"] != {"mode": "signed_in_approver", "request_id": row["id"], "subject_hash": row["subject_hash"]}
            or document["decision"] != row["status"]
            or document["assessment"]["id"] != row["assessment_id"]
            or document["assessment"]["assessment_hash"] != row["assessment_hash"]
            or document["approver_id"] != row["approver_id"]
        ):
            raise RequestProtectionError("Approval signature mismatch")
        return document

    async def _latest_signed_id(self, session, row):
        statement = (
            select(t.run_approvals)
            .where(t.run_approvals.c.run_id == row["run_id"], t.run_approvals.c.assessment_id == row["assessment_id"], t.run_approvals.c.assessment_hash == row["assessment_hash"], t.run_approvals.c.approver_id == row["approver_id"])
            .order_by(t.run_approvals.c.revision.desc())
            .limit(1001)
        )
        rows = [dict(item) for item in (await session.execute(statement)).mappings()]
        if len(rows) > 1000:
            raise RequestProtectionError("Approval signature history exceeds bounds")

        def latest():
            for item in rows:
                document = self._decode_approval(item)
                if document["schema"] == "qa-run-formal-approval.v2":
                    return item["id"]
            return None

        return await asyncio.to_thread(latest)

    async def decide(self, actor, request_id, operation_id, payload):
        approval_identifier(operation_id)
        payload = SignatureCreate.model_validate(payload.model_dump())
        request_hash = fingerprint(payload.model_dump())
        async with self.sf() as session:
            row, events = await self._request(session, actor, request_id)
            if actor != row["approver_id"]:
                raise Conflict
            existing = self._existing(events, operation_id, actor, payload.decision, request_hash)
            if existing is not None:
                return existing
            self._command(row, payload)
            snapshot = None
            if payload.decision == "approved":
                if row["status"] != "pending" or self._time() >= row["expires_at_ms"]:
                    raise Conflict
                try:
                    view, _ = await self._view(session, actor, row, payload.view_id)
                except NotFound:
                    raise Conflict from None
                if view["request_revision"] != row["revision"] or self._time() >= view["expires_at_ms"]:
                    raise Conflict
                snapshot = await self._source(session, row)
                signed = None
            else:
                if row["status"] != "approved":
                    raise Conflict
                signed = await self._signed_document(session, row)
        if snapshot is not None:
            await asyncio.to_thread(self._verify_source_target, row, snapshot)
            legacy_payload = ApprovalCreate(
                assessment_id=row["assessment_id"], assessment_hash=row["assessment_hash"], expected_previous_revision=payload.expected_previous_approval_revision, approver_id=actor, decision="approved", note=payload.note, confirmed=True
            )
            assessment = snapshot["target"]["assessment"]["document"]["assessment"]
            document = self._document(actor, operation_id, row["project_id"], row["run_id"], payload.expected_previous_approval_revision + 1, self._time(), snapshot["target"]["assessment"], assessment, legacy_payload)
        else:
            document = {key: value for key, value in signed.items() if key != "approval_hash"}
            document.update(id=operation_id, revision=payload.expected_previous_approval_revision + 1, created_at_ms=self._time(), decision="revoked", note=payload.note)
        document.update(schema="qa-run-formal-approval.v2", recorded_by=actor, authentication={"mode": "signed_in_approver", "request_id": request_id, "subject_hash": row["subject_hash"]})
        approval_hash = await asyncio.to_thread(fingerprint, {"owner_id": row["owner_id"], "request_hash": request_hash, "document": document})
        async with self._transaction() as session:
            await self._journal(session, row["owner_id"], row["project_id"], row["run_id"], lock=True)
            current, events = await self._request(session, actor, request_id)
            existing = self._existing(events, operation_id, actor, payload.decision, request_hash)
            if existing is not None:
                return existing
            if current != row:
                raise Conflict
            if snapshot is not None:
                if self._time() >= min(row["expires_at_ms"], view["expires_at_ms"]) or snapshot != await self._source(session, row):
                    raise Conflict
                current_view, _ = await self._view(session, actor, row, payload.view_id)
                if current_view != view:
                    raise Conflict
            elif signed != await self._signed_document(session, row):
                raise Conflict
            previous = (await session.execute(select(func.max(t.run_approvals.c.revision)).where(t.run_approvals.c.run_id == row["run_id"]))).scalar_one() or 0
            if previous != payload.expected_previous_approval_revision:
                raise Conflict
            collision = (await session.execute(select(t.run_approvals.c.id).where(t.run_approvals.c.id == operation_id))).scalar_one_or_none()
            if collision:
                raise Conflict
            approval = {key: document[key] for key in ("id", "project_id", "run_id", "revision", "created_at_ms", "approver_id", "decision")}
            approval.update(owner_id=row["owner_id"], assessment_id=row["assessment_id"], assessment_hash=row["assessment_hash"], request_hash=request_hash, document=document, approval_hash=approval_hash)
            await session.execute(insert(t.run_approvals).values(**approval))
            sequence = (await session.execute(select(func.max(t.approval_audit.c.sequence)).where(t.approval_audit.c.run_id == row["run_id"]))).scalar_one() or 0
            await session.execute(
                insert(t.approval_audit).values(
                    project_id=row["project_id"],
                    run_id=row["run_id"],
                    sequence=sequence + 1,
                    approval_id=operation_id,
                    revision=document["revision"],
                    actor=actor,
                    action=payload.decision,
                    subject_hash=approval_hash,
                    at_ms=document["created_at_ms"],
                )
            )
            row = {**row, "status": payload.decision, "revision": row["revision"] + 1, "latest_approval_id": operation_id}
            await session.execute(update(t.approval_requests).where(t.approval_requests.c.id == request_id).values(status=row["status"], revision=row["revision"], latest_approval_id=operation_id))
            return await self._event(session, row, operation_id, actor, payload.decision, request_hash, events[-1]["event_hash"])

    async def effectiveness(self, actor, request_id):
        async with self.sf() as session:
            row, _ = await self._request(session, actor, request_id)
            if row["status"] in {"approved", "revoked"}:
                await self._signed_document(session, row)
                chain = await self.verify_approval_chain(row["owner_id"], row["project_id"], row["run_id"])
                if chain["status"] != "verified":
                    return {"schema": "qa-approval-effectiveness.v1", "status": "unverifiable", "blockers": ["approval_chain_broken"]}
            status = row["status"]
            if status in {"cancelled", "revoked"}:
                return {"schema": "qa-approval-effectiveness.v1", "status": status, "blockers": []}
            if status == "pending" and self._time() >= row["expires_at_ms"]:
                return {"schema": "qa-approval-effectiveness.v1", "status": "expired", "blockers": ["request_expired"]}
            latest_signature = await self._latest_signed_id(session, row) if status == "approved" else None
            snapshot = await self._source(session, row)
        try:
            await asyncio.to_thread(self._verify_source_target, row, snapshot)
        except Conflict:
            return {"schema": "qa-approval-effectiveness.v1", "status": "stale", "blockers": ["assessment_source_changed"]}
        # Reads get a coherent second observation, without creating an audit
        # write, locking the run or promoting a historical owner-recorded entry.
        async with self.sf() as session:
            current, _ = await self._request(session, actor, request_id)
            current_signature = await self._latest_signed_id(session, current) if status == "approved" else None
            if row != current or latest_signature != current_signature or snapshot != await self._source(session, row):
                return {"schema": "qa-approval-effectiveness.v1", "status": "unverifiable", "blockers": ["source_changed_during_observation"]}
        if status == "approved" and latest_signature != row["latest_approval_id"]:
            return {"schema": "qa-approval-effectiveness.v1", "status": "superseded", "blockers": ["newer_signature_decision"]}
        return {"schema": "qa-approval-effectiveness.v1", "status": "effective" if status == "approved" else "pending", "blockers": []}
