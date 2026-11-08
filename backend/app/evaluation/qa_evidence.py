"""Encrypted extracted-output evidence and revisioned human review, not admission.

No network/model calls, retries, quality automation or plaintext metadata reads.
Actual execution still requires a separately admitted Worker. Technical completion
is never an acceptance verdict. Human decisions are not silently auto-aggregated.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Literal

from pydantic import Field, field_validator
from sqlalchemy import func, insert, select

from app.evaluation import tables as t
from app.evaluation.datasets import StrictDTO
from app.evaluation.dispatch_journal import DispatchJournalRepository, DispatchTicket, TechnicalObservation, _positive_int
from app.evaluation.evidence_protection import EvidenceProtection
from app.evaluation.plan_repository import _verified_inputs
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict
from app.evaluation.request_protection import RequestProtectionError


class ReviewCreate(StrictDTO):
    case_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_revision: int = Field(ge=0, le=99)
    decision: Literal["pass", "fail", "uncertain"]
    note: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]

    @field_validator("note")
    @classmethod
    def valid_unicode(cls, value):
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise ValueError("Invalid review text") from None
        return value

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


def _technical(row):
    return {key: row[key] for key in ("kind", "http_status", "body_bytes", "elapsed_ms")}


def _binding(owner, run, dispatch):
    return {"owner_id": owner, "project_id": run["project_id"], "run_id": run["id"], "ordinal": dispatch["ordinal"], "sample_id": dispatch["sample_id"], "plan_hash": run["plan_hash"], "observation_hash": fingerprint(_technical(dispatch))}


def _token_hash(token):
    try:
        return hashlib.sha256(token.encode("ascii")).hexdigest()
    except (ValueError, TypeError, AttributeError, UnicodeError):
        raise RequestProtectionError("Evidence integrity check failed") from None


def _open_verified(protection, kind, row, binding):
    if not hmac.compare_digest(_token_hash(row["encrypted_payload"]), row["protected_hash"]):
        raise RequestProtectionError("Evidence integrity check failed")
    return protection.open(kind, row["encrypted_payload"], binding)


class EvidenceRepository(DispatchJournalRepository):
    def __init__(self, sf, *, protection=None, evidence_protection=None, clock_ms=None):
        super().__init__(sf, protection=protection, clock_ms=clock_ms)
        self.evidence_protection = evidence_protection

    def _evidence_protection(self):
        return self.evidence_protection if self.evidence_protection is not None else EvidenceProtection.from_environment()

    async def record_attempt(self, owner, project_id, run_id, ticket, observation):
        """Internal-only atomic output+observation write after ONE admitted send.

        An uncertain commit is NOT permission to resend/re-record. Only extracted
        text is retained (encrypted), not response headers/raw JSON. Inputs/gold
        never enter this method. Existing metadata-only journal calls still work.
        """
        if not isinstance(ticket, DispatchTicket) or ticket.run_id != run_id or type(ticket.token) is not str or not isinstance(observation, AttemptObservation):
            raise Conflict
        _positive_int(ticket.ordinal, 10_000)
        checked = TechnicalObservation.model_validate({"kind": observation.kind, "http_status": observation.http_status, "body_bytes": observation.body_bytes, "elapsed_ms": observation.elapsed_ms})
        collected = checked.kind == "output_collected"
        try:
            if collected:
                if type(observation.output) is not str or not observation.output.strip():
                    raise ValueError
                size = len(observation.output.encode("utf-8"))
            elif observation.output is not None:
                raise ValueError
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Invalid extracted output") from None
        run = await self.get_journal(owner, project_id, run_id)
        if collected and size > run["max_response_bytes"]:
            raise ValueError("Extracted output exceeds evidence limit")
        binding = {"owner_id": owner, "project_id": project_id, "run_id": run_id, "ordinal": ticket.ordinal, "sample_id": ticket.sample_id, "plan_hash": run["plan_hash"], "observation_hash": fingerprint(checked.model_dump())}
        token = await asyncio.to_thread(self._evidence_protection().seal, "output", observation.output, binding) if collected else None
        async with self._transaction() as session:
            locked = await self._journal(session, owner, project_id, run_id, lock=True)
            if locked["plan_hash"] != run["plan_hash"]:
                raise Conflict
            at = self._time()
            await self._record_observation(session, locked, at, ticket, checked)
            if token is not None:
                await session.execute(
                    insert(t.output_evidence).values(project_id=project_id, run_id=run_id, ordinal=ticket.ordinal, encrypted_payload=token, protected_hash=_token_hash(token), observation_hash=binding["observation_hash"], created_at_ms=at)
                )
                await self._journal_event(session, locked, "output_evidence_recorded", at, ordinal=ticket.ordinal)

    async def list_runs(self, owner, project_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            rows = await session.execute(
                select(t.dispatch_runs, t.project_components.c.name_at_link.label("component_name"), t.plans.c.version_label.label("plan_label"))
                .join(t.plans, (t.plans.c.id == t.dispatch_runs.c.plan_id) & (t.plans.c.project_id == t.dispatch_runs.c.project_id))
                .join(t.project_components, (t.project_components.c.id == t.plans.c.component_id) & (t.project_components.c.project_id == t.plans.c.project_id))
                .where(t.dispatch_runs.c.project_id == project_id)
                .order_by(t.dispatch_runs.c.started_at_ms.desc(), t.dispatch_runs.c.id)
                .limit(200)
            )
            return [dict(row) for row in rows.mappings()]

    async def list_cases(self, owner, project_id, run_id, *, offset=0, limit=100):
        if type(offset) is not int or not 0 <= offset <= 10_000:
            raise ValueError("Invalid case page")
        _positive_int(limit, 200)
        async with self.sf() as session:
            run = await self._journal(session, owner, project_id, run_id)
            columns = [column for column in t.dispatches.c if column.name != "ticket_hash"]
            cases = [dict(row) for row in (await session.execute(select(*columns).where(t.dispatches.c.run_id == run_id).order_by(t.dispatches.c.ordinal).offset(offset).limit(limit))).mappings()]
            outputs = set((await session.execute(select(t.output_evidence.c.ordinal).where(t.output_evidence.c.run_id == run_id))).scalars())
            # One latest human decision per ordinal; never count historical revisions twice.
            latest = select(t.case_reviews.c.ordinal, func.max(t.case_reviews.c.revision).label("revision")).where(t.case_reviews.c.run_id == run_id).group_by(t.case_reviews.c.ordinal).subquery()
            reviews = {
                row.ordinal: {"revision": row.revision, "decision": row.decision}
                for row in (
                    await session.execute(
                        select(t.case_reviews.c.ordinal, t.case_reviews.c.revision, t.case_reviews.c.decision)
                        .join(latest, (t.case_reviews.c.ordinal == latest.c.ordinal) & (t.case_reviews.c.revision == latest.c.revision))
                        .where(t.case_reviews.c.run_id == run_id)
                    )
                )
            }
        counts = {"pass": 0, "fail": 0, "uncertain": 0, "unreviewed": run["request_count"] - len(reviews)}
        for row in reviews.values():
            counts[row["decision"]] += 1
        for row in cases:
            reviewed = reviews.get(row["ordinal"])
            row.update(has_output_evidence=row["ordinal"] in outputs, review_revision=reviewed["revision"] if reviewed else 0, review_decision=reviewed["decision"] if reviewed else None)
        return {"scope": "human_review_only", "run": run, "cases": cases, "counts": counts, "offset": offset, "limit": limit}

    async def _snapshot(self, session, owner, project_id, run_id, ordinal, *, run=None):
        run = run if run is not None else await self._journal(session, owner, project_id, run_id)
        plan = await self._plan(session, owner, project_id, run["plan_id"])
        dataset = await self._dataset(session, owner, project_id, plan["dataset_id"])
        dispatch = (await session.execute(select(*[column for column in t.dispatches.c if column.name != "ticket_hash"]).where(t.dispatches.c.run_id == run_id, t.dispatches.c.ordinal == ordinal))).mappings().first()
        if dispatch is None:
            raise Conflict
        samples = [
            dict(row)
            for row in (
                await session.execute(
                    select(t.samples.c.sample_id, t.samples.c.input, t.samples.c.source_ref, t.samples.c.slice_tag, t.references.c.expected)
                    .outerjoin(t.references, (t.references.c.dataset_id == t.samples.c.dataset_id) & (t.references.c.sample_id == t.samples.c.sample_id))
                    .where(t.samples.c.dataset_id == dataset["id"])
                    .order_by(t.samples.c.sample_id)
                    .limit(501)
                )
            ).mappings()
        ]
        component = (await session.execute(select(t.project_components).where(t.project_components.c.id == plan["component_id"], t.project_components.c.project_id == project_id))).mappings().first()
        if component is None:
            raise Conflict
        evidence = (await session.execute(select(t.output_evidence).where(t.output_evidence.c.run_id == run_id, t.output_evidence.c.ordinal == ordinal))).mappings().first()
        reviews = [dict(row) for row in (await session.execute(select(t.case_reviews).where(t.case_reviews.c.run_id == run_id, t.case_reviews.c.ordinal == ordinal).order_by(t.case_reviews.c.revision).limit(101))).mappings()]
        # Exclude mutable run lifecycle/counters: concurrent *other* attempts may finish.
        return {
            "run": {key: run[key] for key in ("id", "project_id", "plan_id", "plan_hash", "request_count", "max_response_bytes")},
            "plan": plan,
            "dataset": dataset,
            "dispatch": dict(dispatch),
            "samples": samples,
            "component": dict(component),
            "evidence": dict(evidence) if evidence else None,
            "reviews": reviews,
        }

    @staticmethod
    def _verify_snapshot(owner, snapshot, protection):
        run, plan, dataset, dispatch = (snapshot[key] for key in ("run", "plan", "dataset", "dispatch"))
        definition = plan["definition"]
        if (
            run["plan_hash"] != plan["definition_hash"]
            or run["request_count"] != definition["limits"]["request_count"]
            or dataset["status"] != "frozen"
            or dataset["revision"] != definition["dataset_revision"]
            or dataset["content_hash"] != definition["dataset_hash"]
        ):
            raise Conflict
        _verified_inputs(dataset, snapshot["samples"])
        ordered = sorted(snapshot["samples"], key=lambda row: row["sample_id"])
        sample = ordered[(dispatch["ordinal"] - 1) % len(ordered)]
        if sample["sample_id"] != dispatch["sample_id"] or len(ordered) != definition["preflight"]["sample_count"]:
            raise Conflict
        binding = _binding(owner, run, dispatch)
        evidence = snapshot["evidence"]
        output = None
        if evidence:
            if dispatch["state"] != "observed" or dispatch["kind"] != "output_collected" or evidence["observation_hash"] != binding["observation_hash"]:
                raise Conflict
            output = _open_verified(protection, "output", evidence, binding)
            if len(output.encode("utf-8")) > run["max_response_bytes"]:
                raise Conflict
        case_hash = fingerprint({"binding": binding, "state": dispatch["state"], "dataset_hash": dataset["content_hash"], "evidence_hash": evidence["protected_hash"] if evidence else None})
        reviews = []
        for index, row in enumerate(snapshot["reviews"], 1):
            if row["revision"] != index or row["case_hash"] != case_hash:
                raise Conflict
            decoded = _open_verified(protection, "review", row, binding)
            if decoded != {"revision": index, "decision": row["decision"], "actor": row["reviewer_id"], "note": decoded["note"], "case_hash": case_hash}:
                raise Conflict
            reviews.append({"revision": index, "decision": row["decision"], "reviewer_id": row["reviewer_id"], "note": decoded["note"], "created_at_ms": row["created_at_ms"]})
        return {
            "scope": "human_review_only",
            "run_id": run["id"],
            "ordinal": dispatch["ordinal"],
            "sample_id": sample["sample_id"],
            "component_name": snapshot["component"]["name_at_link"],
            "plan_label": plan["version_label"],
            "input": sample["input"],
            "expected": sample["expected"],
            "source_ref": sample["source_ref"],
            "slice_tag": sample["slice_tag"],
            "output": output,
            "evidence_hash": evidence["protected_hash"] if evidence else None,
            "case_hash": case_hash,
            "state": dispatch["state"],
            "technical": _technical(dispatch),
            "review_revision": len(reviews),
            "reviews": reviews,
        }

    async def _read_verified(self, owner, project_id, run_id, ordinal):
        _positive_int(ordinal, 10_000)
        async with self.sf() as session:
            snapshot = await self._snapshot(session, owner, project_id, run_id, ordinal)
        case = await asyncio.to_thread(self._verify_snapshot, owner, snapshot, self._evidence_protection())
        return snapshot, case

    async def open_case(self, owner, project_id, run_id, ordinal):
        snapshot, case = await self._read_verified(owner, project_id, run_id, ordinal)
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            if snapshot != await self._snapshot(session, owner, project_id, run_id, ordinal, run=run):
                raise Conflict
            await self._journal_event(session, run, "review_case_opened", self._time(), ordinal=ordinal)
        return case

    async def review_case(self, owner, project_id, run_id, ordinal, payload: ReviewCreate):
        payload = ReviewCreate.model_validate(payload.model_dump())
        snapshot, case = await self._read_verified(owner, project_id, run_id, ordinal)
        if (
            case["case_hash"] != payload.case_hash
            or case["review_revision"] != payload.expected_revision
            or case["state"] not in {"observed", "delivery_unknown", "not_dispatched"}
            or (payload.decision == "pass" and (case["output"] is None or case["technical"]["kind"] != "output_collected"))
        ):
            raise Conflict
        revision = payload.expected_revision + 1
        note = {"revision": revision, "decision": payload.decision, "actor": owner, "note": payload.note, "case_hash": case["case_hash"]}
        token = await asyncio.to_thread(self._evidence_protection().seal, "review", note, _binding(owner, snapshot["run"], snapshot["dispatch"]))
        async with self._transaction() as session:
            run = await self._journal(session, owner, project_id, run_id, lock=True)
            if snapshot != await self._snapshot(session, owner, project_id, run_id, ordinal, run=run):
                raise Conflict
            at = self._time()
            await session.execute(
                insert(t.case_reviews).values(
                    project_id=project_id,
                    run_id=run_id,
                    ordinal=ordinal,
                    revision=revision,
                    case_hash=case["case_hash"],
                    decision=payload.decision,
                    reviewer_id=owner,
                    encrypted_payload=token,
                    protected_hash=_token_hash(token),
                    created_at_ms=at,
                )
            )
            await self._journal_event(session, run, "human_review_recorded", at, ordinal=ordinal)
        return {"revision": revision, "decision": payload.decision, "case_hash": case["case_hash"]}
