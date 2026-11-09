"""Explicit two-human blind case review, arbitration and immutable rounds.

Assignments grant only one frozen subject, never project membership or execution.
Owner self-review, verified summaries, archives and formal approval are unchanged.
All sensitive verification is off-loop, followed by ordered run-lock rechecks.
"""

from __future__ import annotations

import asyncio
import hmac
import re
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, insert, or_, select, update

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.qa_evidence import EvidenceRepository, _binding, _open_verified, _token_hash
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound

POLICY = "independent-double-blind.v1"
LEASE_MS = 1_800_000
ROLES = ("reviewer_1", "reviewer_2", "arbitrator")


class TaskCommand(StrictDTO):
    expected_revision: int = Field(ge=1, le=10_000)
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def boolean_only(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value


class TaskCreate(StrictDTO):
    run_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    ordinal: int = Field(ge=1, le=10_000)
    case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_ids: list[str] = Field(min_length=2, max_length=2)
    arbitrator_id: str
    share_reference: Literal[True]
    confirmed: Literal[True]

    @field_validator("share_reference", "confirmed", mode="before")
    @classmethod
    def boolean_only(cls, value):
        return TaskCommand.boolean_only(value)

    @model_validator(mode="after")
    def independent_actors(self):
        actors = [*self.reviewer_ids, self.arbitrator_id]
        if len(set(actors)) != 3:
            raise ValueError("Three distinct human accounts required")
        try:
            if any(str(UUID(actor)) != actor for actor in actors):
                raise ValueError
        except (ValueError, AttributeError):
            raise ValueError("Canonical account IDs required") from None
        return self


class TaskDecision(TaskCommand):
    subject_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["pass", "fail", "uncertain"]
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def unicode_text(cls, value):
        try:
            value.encode("utf-8")
            if not value.strip():
                raise ValueError("A reason is required")
        except UnicodeError:
            raise ValueError("Invalid text") from None
        return value


class TaskReopen(TaskCommand):
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def unicode_text(cls, value):
        return TaskDecision.unicode_text(value)


def task_identifier(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise NotFound
    return value


class ReviewTaskRepository(EvidenceRepository):
    @staticmethod
    def _definition(owner, project, task_id, payload):
        if owner in [*payload.reviewer_ids, payload.arbitrator_id]:
            raise Conflict
        return {"schema": "independent-case-task.v1", "policy": POLICY, "task_id": task_id, "owner_id": owner, "project_id": project, **payload.model_dump()}

    @classmethod
    def _verify_definition(cls, row):
        try:
            definition = row["definition"]
            fields = {name: definition[name] for name in TaskCreate.model_fields}
            expected = cls._definition(row["owner_id"], row["project_id"], row["id"], TaskCreate.model_validate(fields))
            if definition != expected or not hmac.compare_digest(row["subject_hash"], fingerprint(expected)) or any(row[n] != definition[n] for n in ("run_id", "ordinal", "case_hash")):
                raise Conflict
        except (ValueError, KeyError, TypeError):
            raise Conflict from None
        return dict(zip(ROLES, [*definition["reviewer_ids"], definition["arbitrator_id"]], strict=True))

    async def _state(self, session, actor, task_id):
        task_identifier(task_id)
        grant = (
            select(t.review_task_assignments.c.task_id).where(t.review_task_assignments.c.task_id == t.review_tasks.c.id, t.review_task_assignments.c.round == t.review_tasks.c.round, t.review_task_assignments.c.actor_id == actor).exists()
        )
        row = (await session.execute(select(t.review_tasks).where(t.review_tasks.c.id == task_id, or_(t.review_tasks.c.owner_id == actor, grant)))).mappings().first()
        if row is None:
            raise NotFound
        task = dict(row)
        actors = self._verify_definition(task)
        if actor != task["owner_id"] and actor not in actors.values():
            raise NotFound
        assignments = [
            dict(r)
            for r in (await session.execute(select(t.review_task_assignments).where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == task["round"]).order_by(t.review_task_assignments.c.role))).mappings()
        ]
        if len(assignments) != 3 or any(a["actor_id"] != actors.get(a["role"]) for a in assignments):
            raise Conflict
        return {"task": task, "assignments": assignments}

    def _public(self, actor, state):
        task = state["task"]
        result = {key: task[key] for key in ("id", "project_id", "run_id", "ordinal", "subject_hash", "case_hash", "round", "revision", "status", "created_at_ms")}
        result.update(scope="independent_review_only", policy=POLICY, approval="not_approved")

        def assignment(a):
            expired = a["status"] == "active" and (a["lease_until_ms"] is None or a["lease_until_ms"] <= self._time())
            return {"role": a["role"], "status": "expired" if expired else a["status"], "lease_until_ms": a["lease_until_ms"]}

        if actor == task["owner_id"]:
            result.update(role="owner", assignments=[{**assignment(a), "actor_id": a["actor_id"]} for a in state["assignments"]])
        else:
            own = next(a for a in state["assignments"] if a["actor_id"] == actor)
            result.update(role=own["role"], assignment=assignment(own))
        return result

    async def get_task(self, actor, task_id):
        async with self.sf() as session:
            return self._public(actor, await self._state(session, actor, task_id))

    async def inbox(self, actor, *, offset=0, limit=100):
        if type(offset) is not int or not 0 <= offset <= 10_000 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid pagination")
        async with self.sf() as session:
            grant = (
                select(t.review_task_assignments.c.task_id)
                .where(t.review_task_assignments.c.task_id == t.review_tasks.c.id, t.review_task_assignments.c.round == t.review_tasks.c.round, t.review_task_assignments.c.actor_id == actor)
                .exists()
            )
            ids = (await session.execute(select(t.review_tasks.c.id).where(or_(t.review_tasks.c.owner_id == actor, grant)).order_by(t.review_tasks.c.created_at_ms, t.review_tasks.c.id).offset(offset).limit(limit))).scalars().all()
            rows = [self._public(actor, await self._state(session, actor, task_id)) for task_id in ids]
        return {"tasks": rows, "offset": offset, "limit": limit}

    async def list_project(self, owner, project_id, *, offset=0, limit=100):
        if type(offset) is not int or not 0 <= offset <= 10_000 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid pagination")
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            ids = (
                (
                    await session.execute(
                        select(t.review_tasks.c.id).where(t.review_tasks.c.owner_id == owner, t.review_tasks.c.project_id == project_id).order_by(t.review_tasks.c.created_at_ms, t.review_tasks.c.id).offset(offset).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            rows = [self._public(owner, await self._state(session, owner, task_id)) for task_id in ids]
        return {"tasks": rows, "offset": offset, "limit": limit}

    async def _event(self, session, state, actor, action, *, encrypted_reason=None):
        task = state["task"]
        sequence = (await session.execute(select(func.max(t.review_task_audit.c.sequence)).where(t.review_task_audit.c.task_id == task["id"]))).scalar_one() or 0
        await session.execute(
            insert(t.review_task_audit).values(
                task_id=task["id"],
                sequence=sequence + 1,
                round=task["round"],
                actor=actor,
                action=action,
                subject_hash=task["subject_hash"],
                at_ms=self._time(),
                encrypted_reason=encrypted_reason,
                protected_hash=_token_hash(encrypted_reason) if encrypted_reason else None,
            )
        )

    async def _assign_round(self, session, task):
        actors = self._verify_definition(task)
        await session.execute(
            insert(t.review_task_assignments), [{"task_id": task["id"], "round": task["round"], "role": role, "actor_id": actor, "status": "offered", "lease_until_ms": None, "viewed_revision": None} for role, actor in actors.items()]
        )

    async def create_task(self, owner, project_id, task_id, payload):
        task_identifier(task_id)
        payload = TaskCreate.model_validate(payload.model_dump())
        definition = self._definition(owner, project_id, task_id, payload)
        subject_hash = fingerprint(definition)
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            existing = (await session.execute(select(t.review_tasks.c.subject_hash).where(t.review_tasks.c.id == task_id, t.review_tasks.c.owner_id == owner, t.review_tasks.c.project_id == project_id))).scalar_one_or_none()
        if existing is not None:
            if existing != subject_hash:
                raise Conflict
            return await self.get_task(owner, task_id)
        async with self.sf() as session:
            snapshot = await self._snapshot(session, owner, project_id, payload.run_id, payload.ordinal, include_owner_reviews=False)
        case = await asyncio.to_thread(self._verify_snapshot, owner, snapshot, self._evidence_protection())
        if case["case_hash"] != payload.case_hash or case["state"] not in {"observed", "not_dispatched", "delivery_unknown"}:
            raise Conflict
        task = dict(
            id=task_id,
            owner_id=owner,
            project_id=project_id,
            run_id=payload.run_id,
            ordinal=payload.ordinal,
            case_hash=payload.case_hash,
            subject_hash=subject_hash,
            definition=definition,
            round=1,
            revision=1,
            status="queued",
            created_at_ms=self._time(),
        )
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, payload.run_id, lock=True)
            if snapshot != await self._snapshot(session, owner, project_id, payload.run_id, payload.ordinal, run=run, include_owner_reviews=False):
                raise Conflict
            existing = (await session.execute(select(t.review_tasks.c.subject_hash).where(t.review_tasks.c.id == task_id))).scalar_one_or_none()
            if existing is not None:
                if existing != subject_hash:
                    raise Conflict
            else:
                count = (await session.execute(select(func.count()).select_from(t.review_tasks).where(t.review_tasks.c.run_id == payload.run_id))).scalar_one()
                if count >= 10_000:
                    raise Conflict
                await session.execute(insert(t.review_tasks).values(**task))
                await self._assign_round(session, task)
                await self._event(session, {"task": task}, owner, "created_sensitive_grants")
        return await self.get_task(owner, task_id)

    async def _locked(self, session, actor, observed, expected_revision=None):
        task = observed["task"]
        await self._journal(session, task["owner_id"], task["project_id"], task["run_id"], lock=True)
        current = await self._state(session, actor, task["id"])
        if current != observed or (expected_revision is not None and current["task"]["revision"] != expected_revision):
            raise Conflict
        return current

    @staticmethod
    def _own(actor, state):
        own = next((a for a in state["assignments"] if a["actor_id"] == actor), None)
        if own is None:
            raise Conflict
        return own

    @staticmethod
    def _phase(task, own):
        if task["status"] in {"cancelled", "resolved"} or (own["role"] == "arbitrator" and task["status"] != "escalated") or (own["role"] != "arbitrator" and task["status"] == "escalated"):
            raise Conflict

    def _active(self, actor, state, *, viewed=False):
        own = self._own(actor, state)
        self._phase(state["task"], own)
        if own["status"] != "active" or own["lease_until_ms"] is None or own["lease_until_ms"] <= self._time() or (viewed and own["viewed_revision"] != state["task"]["revision"]):
            raise Conflict
        return own

    async def _bump(self, session, task, *, status=None, round_number=None):
        if task["revision"] >= 10_000:
            raise Conflict
        values = {"revision": task["revision"] + 1, "status": status or task["status"], "round": round_number or task["round"]}
        await session.execute(update(t.review_tasks).where(t.review_tasks.c.id == task["id"]).values(**values))
        task.update(values)

    async def claim(self, actor, task_id, payload):
        payload = TaskCommand.model_validate(payload.model_dump())
        async with self.sf() as session:
            state = await self._state(session, actor, task_id)
        async with self._transaction() as session:
            state = await self._locked(session, actor, state, payload.expected_revision)
            own = self._own(actor, state)
            self._phase(state["task"], own)
            if own["status"] == "submitted":
                raise Conflict
            if own["status"] != "active" or own["lease_until_ms"] is None or own["lease_until_ms"] <= self._time():
                if own["status"] == "active":
                    await self._event(session, state, actor, "lease_expired")
                await session.execute(
                    update(t.review_task_assignments)
                    .where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == state["task"]["round"], t.review_task_assignments.c.actor_id == actor)
                    .values(status="active", lease_until_ms=self._time() + LEASE_MS, viewed_revision=None)
                )
                await self._bump(session, state["task"], status="escalated" if own["role"] == "arbitrator" else "in_review")
                await self._event(session, state, actor, "claimed")
        return await self.get_task(actor, task_id)

    async def release(self, actor, task_id, payload):
        payload = TaskCommand.model_validate(payload.model_dump())
        async with self.sf() as session:
            state = await self._state(session, actor, task_id)
        async with self._transaction() as session:
            state = await self._locked(session, actor, state, payload.expected_revision)
            self._active(actor, state)
            await session.execute(
                update(t.review_task_assignments)
                .where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == state["task"]["round"], t.review_task_assignments.c.actor_id == actor)
                .values(status="released", lease_until_ms=None, viewed_revision=None)
            )
            others = [a for a in state["assignments"] if a["actor_id"] != actor]
            pending = any(a["status"] == "submitted" or (a["status"] == "active" and a["lease_until_ms"] is not None and a["lease_until_ms"] > self._time()) for a in others)
            status = "escalated" if state["task"]["status"] == "escalated" else "in_review" if pending else "queued"
            await self._bump(session, state["task"], status=status)
            await self._event(session, state, actor, "released")
        return await self.get_task(actor, task_id)

    async def _materials(self, session, state, *, decisions=False, round_number=None):
        task = state["task"]
        snapshot = await self._snapshot(session, task["owner_id"], task["project_id"], task["run_id"], task["ordinal"], include_owner_reviews=False)
        result = {"source": snapshot}
        if decisions:
            number = round_number or task["round"]
            result["decisions"] = [
                dict(r) for r in (await session.execute(select(t.review_task_decisions).where(t.review_task_decisions.c.task_id == task["id"], t.review_task_decisions.c.round == number).order_by(t.review_task_decisions.c.role))).mappings()
            ]
            result["resolutions"] = [
                dict(r)
                for r in (
                    await session.execute(select(t.review_task_resolutions).where(t.review_task_resolutions.c.task_id == task["id"], t.review_task_resolutions.c.round == number).order_by(t.review_task_resolutions.c.revision))
                ).mappings()
            ]
        return result

    def _verify_materials(self, task, materials):
        source = materials["source"]
        case = self._verify_snapshot(task["owner_id"], source, self._evidence_protection())
        if case["case_hash"] != task["case_hash"]:
            raise Conflict
        return case

    def _verify_decisions(self, task, materials):
        actors = self._verify_definition(task)
        source = materials["source"]
        binding = _binding(task["owner_id"], source["run"], source["dispatch"])
        opened = []
        roles = set()
        for row in materials["decisions"]:
            if row["role"] in roles or actors.get(row["role"]) != row["actor_id"]:
                raise Conflict
            roles.add(row["role"])
            decoded = _open_verified(self._evidence_protection(), "task_decision", row, binding)
            expected = {
                "task_id": task["id"],
                "round": row["round"],
                "role": row["role"],
                "actor": row["actor_id"],
                "subject_hash": task["subject_hash"],
                "created_at_ms": row["created_at_ms"],
                "decision": row["decision"],
                "note": decoded["note"],
            }
            if decoded != expected or (row["decision"] == "pass" and (source["evidence"] is None or source["dispatch"]["kind"] != "output_collected")):
                raise Conflict
            opened.append(decoded)
        expected = self._resolutions(task, materials["decisions"])
        if [r["document"] for r in materials["resolutions"]] != expected or any(r["resolution_hash"] != fingerprint(r["document"]) or r["revision"] != i for i, r in enumerate(materials["resolutions"], 1)):
            raise Conflict
        return opened

    @staticmethod
    def _resolutions(task, rows):
        by_role = {r["role"]: r for r in rows}
        if "reviewer_1" not in by_role or "reviewer_2" not in by_role:
            if "arbitrator" in by_role:
                raise Conflict
            return []
        pair = [by_role[role] for role in ROLES[:2]]
        same = pair[0]["decision"] == pair[1]["decision"] and pair[0]["decision"] != "uncertain"
        common = {"schema": "independent-case-resolution.v1", "scope": "case_resolution_only", "approval": "not_approved", "task_id": task["id"], "round": pair[0]["round"], "subject_hash": task["subject_hash"]}
        documents = [{**common, "revision": 1, "basis": "unanimous" if same else "needs_arbitration", "outcome": pair[0]["decision"] if same else "uncertain", "decision_hashes": [r["protected_hash"] for r in pair]}]
        if "arbitrator" in by_role:
            if same:
                raise Conflict
            arb = by_role["arbitrator"]
            documents.append({**common, "revision": 2, "basis": "arbitrated", "outcome": arb["decision"], "decision_hashes": [r["protected_hash"] for r in [*pair, arb]]})
        return documents

    async def open_task(self, actor, task_id):
        async with self.sf() as session:
            state = await self._state(session, actor, task_id)
            own = self._active(actor, state)
            arb = own["role"] == "arbitrator"
            materials = await self._materials(session, state, decisions=arb)
        case = await asyncio.to_thread(self._verify_materials, state["task"], materials)
        prior = await asyncio.to_thread(self._verify_decisions, state["task"], materials) if arb else []
        if arb and (len(prior) != 2 or {d["role"] for d in prior} != set(ROLES[:2]) or materials["resolutions"][-1]["document"]["basis"] != "needs_arbitration"):
            raise Conflict
        async with self._transaction() as session:
            await self._locked(session, actor, state)
            self._active(actor, state)
            if materials != await self._materials(session, state, decisions=arb):
                raise Conflict
            await session.execute(
                update(t.review_task_assignments)
                .where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == state["task"]["round"], t.review_task_assignments.c.actor_id == actor)
                .values(viewed_revision=state["task"]["revision"])
            )
            await self._event(session, state, actor, "sensitive_case_opened")
        return {
            **{k: v for k, v in case.items() if k not in {"reviews", "review_revision", "scope"}},
            "scope": "independent_review_only",
            "task_id": task_id,
            "subject_hash": state["task"]["subject_hash"],
            "task_revision": state["task"]["revision"],
            "round": state["task"]["round"],
            "prior_decisions": prior,
        }

    async def submit_decision(self, actor, task_id, payload):
        payload = TaskDecision.model_validate(payload.model_dump())
        async with self.sf() as session:
            state = await self._state(session, actor, task_id)
            own = self._active(actor, state, viewed=True)
            task = state["task"]
            if payload.expected_revision != task["revision"] or payload.subject_hash != task["subject_hash"]:
                raise Conflict
            materials = await self._materials(session, state, decisions=True)
        case = await asyncio.to_thread(self._verify_materials, task, materials)
        await asyncio.to_thread(self._verify_decisions, task, materials)
        if payload.decision == "pass" and (case["output"] is None or case["technical"]["kind"] != "output_collected"):
            raise Conflict
        note = {"task_id": task_id, "round": task["round"], "role": own["role"], "actor": actor, "subject_hash": task["subject_hash"], "created_at_ms": self._time(), "decision": payload.decision, "note": payload.note}
        source = materials["source"]
        token = await asyncio.to_thread(self._evidence_protection().seal, "task_decision", note, _binding(task["owner_id"], source["run"], source["dispatch"]))
        row = {"task_id": task_id, "round": task["round"], "role": own["role"], "actor_id": actor, "decision": payload.decision, "encrypted_payload": token, "protected_hash": _token_hash(token), "created_at_ms": note["created_at_ms"]}
        resolutions = self._resolutions(task, [*materials["decisions"], row])
        status = "in_review" if not resolutions else "resolved" if resolutions[-1]["outcome"] in {"pass", "fail"} else "escalated"
        async with self._transaction() as session:
            await self._locked(session, actor, state, payload.expected_revision)
            self._active(actor, state, viewed=True)
            if materials != await self._materials(session, state, decisions=True):
                raise Conflict
            await session.execute(insert(t.review_task_decisions).values(**row))
            await session.execute(
                update(t.review_task_assignments)
                .where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == task["round"], t.review_task_assignments.c.actor_id == actor)
                .values(status="submitted", lease_until_ms=None, viewed_revision=None)
            )
            for document in resolutions[len(materials["resolutions"]) :]:
                await session.execute(insert(t.review_task_resolutions).values(task_id=task_id, round=task["round"], revision=document["revision"], document=document, resolution_hash=fingerprint(document)))
            await self._bump(session, task, status=status)
            await self._event(session, state, actor, "decision_submitted")
        return await self.get_task(actor, task_id)

    async def get_result(self, owner, task_id, *, round_number=None):
        async with self.sf() as session:
            state = await self._state(session, owner, task_id)
            task = state["task"]
            if task["owner_id"] != owner:
                raise NotFound
            number = task["round"] if round_number is None else round_number
            if type(number) is not int or not 1 <= number <= task["round"]:
                raise Conflict
            materials = await self._materials(session, state, decisions=True, round_number=number)
        await asyncio.to_thread(self._verify_materials, task, materials)
        decisions = await asyncio.to_thread(self._verify_decisions, task, materials)
        if not materials["resolutions"]:
            raise Conflict
        async with self._transaction() as session:
            await self._locked(session, owner, state)
            if materials != await self._materials(session, state, decisions=True, round_number=number):
                raise Conflict
            await self._event(session, state, owner, "resolution_opened")
        return {"task_id": task_id, "round": number, "decisions": decisions, "resolution": materials["resolutions"][-1]["document"]}

    async def cancel(self, owner, task_id, payload):
        payload = TaskCommand.model_validate(payload.model_dump())
        async with self.sf() as session:
            state = await self._state(session, owner, task_id)
        if state["task"]["owner_id"] != owner:
            raise NotFound
        async with self._transaction() as session:
            await self._locked(session, owner, state, payload.expected_revision)
            if state["task"]["status"] == "cancelled":
                raise Conflict
            await self._bump(session, state["task"], status="cancelled")
            await session.execute(
                update(t.review_task_assignments)
                .where(t.review_task_assignments.c.task_id == task_id, t.review_task_assignments.c.round == state["task"]["round"], t.review_task_assignments.c.status != "submitted")
                .values(status="released", lease_until_ms=None, viewed_revision=None)
            )
            await self._event(session, state, owner, "cancelled")
        return await self.get_task(owner, task_id)

    async def reopen(self, owner, task_id, payload):
        payload = TaskReopen.model_validate(payload.model_dump())
        async with self.sf() as session:
            state = await self._state(session, owner, task_id)
            task = state["task"]
            if task["owner_id"] != owner:
                raise NotFound
            if task["status"] not in {"resolved", "escalated"} or task["round"] >= 10 or task["revision"] != payload.expected_revision:
                raise Conflict
            materials = await self._materials(session, state, decisions=True)
        await asyncio.to_thread(self._verify_materials, task, materials)
        await asyncio.to_thread(self._verify_decisions, task, materials)
        source = materials["source"]
        reason = {"task_id": task_id, "round": task["round"] + 1, "actor": owner, "subject_hash": task["subject_hash"], "created_at_ms": self._time(), "action": "reopened", "reason": payload.reason}
        token = await asyncio.to_thread(self._evidence_protection().seal, "task_action", reason, _binding(owner, source["run"], source["dispatch"]))
        async with self._transaction() as session:
            await self._locked(session, owner, state, payload.expected_revision)
            if materials != await self._materials(session, state, decisions=True):
                raise Conflict
            await self._bump(session, task, status="queued", round_number=task["round"] + 1)
            await self._assign_round(session, task)
            await self._event(session, state, owner, "reopened", encrypted_reason=token)
        return await self.get_task(owner, task_id)
