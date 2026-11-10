"""Immutable owner-scoped external technical declarations, NEVER platform evidence.

No output, journal, ZIP, credentials, key lookup, current-grant lookup or network.
Canonical technical sources are retained; original bytes are discarded after
checking their DECLARED hashes. Neither hash establishes external provenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
from uuid import uuid4

from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.evaluation import tables as t
from app.evaluation.authorized_exports import ExportRepository, _drain, _identifier
from app.evaluation.datasets import StrictDTO
from app.evaluation.external_qa_metadata import ExternalMetadataRejected, inspect_local_metadata
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound
from app.evaluation.request_protection import RequestProtectionError

MAX_DOCUMENT_BYTES = 8192
MAX_HTTP_BYTES = 32768
_ERROR = "External technical metadata archive failed integrity checks"


class IntakeIntegrityError(Exception):
    """Private generic failure; never retain a submitted document in the message."""


class ExternalQAIntakeCreate(StrictDTO):
    # Stripping raw JSON would silently change the bytes whose hash was viewed.
    model_config = ConfigDict(str_strip_whitespace=False)

    export_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    viewed_export_receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_run_id: str = Field(min_length=36, max_length=36)
    manifest_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_json: str = Field(min_length=1, max_length=MAX_DOCUMENT_BYTES, repr=False)
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reconciliation_json: str = Field(min_length=1, max_length=MAX_DOCUMENT_BYTES, repr=False)
    reconciliation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: bool
    technical_metadata_only_confirmed: bool
    untrusted_source_acknowledged: bool

    @field_validator("confirmed", "technical_metadata_only_confirmed", "untrusted_source_acknowledged", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _source_metadata(snapshot):
    """Validate historical metadata only, off-loop; never re-open a source secret."""
    receipt = ExportRepository._decode(snapshot["export"])
    plan = PlanRepository._public_plan(snapshot["plan"])
    definition = plan["definition"]
    if (
        receipt["tier"] != "baseline_inputs"
        or receipt["input_set_complete"] is not True
        or definition["dataset_purpose"] != "baseline"
        or definition["limits"]["mode"] != "effectiveness"
        or receipt["project_id"] != snapshot["project"]["id"]
        or receipt["plan_id"] != plan["id"]
        or receipt["plan_hash"] != plan["definition_hash"]
        or receipt["source_plan_schema"] != definition["schema"]
        or receipt["all_frozen_samples"] != definition["preflight"]["sample_count"]
        or any(receipt[name] != definition[name] for name in ("dataset_id", "dataset_revision", "dataset_hash", "request_version_id", "request_protected_hash"))
    ):
        raise Conflict
    return {
        "export_receipt": receipt,
        "frozen_request_count": definition["limits"]["request_count"],
        "max_total_request_bytes": definition["limits"]["max_total_body_bytes"],
    }


def _aligned(inspection, source):
    receipt = source["export_receipt"]
    if (
        inspection["declared_manifest_fingerprint"] != receipt["manifest_fingerprint"]
        or inspection["frozen_input_count"] != receipt["all_frozen_samples"]
        or inspection["frozen_request_count"] != source["frozen_request_count"]
        or inspection["reserved_request_bytes"] > source["max_total_request_bytes"]
    ):
        raise Conflict


def _request_hash(source, inspection, raw_lengths):
    return fingerprint(
        {
            "scope": "external_technical_metadata_quarantine_only",
            "export_id": source["export_receipt"]["id"],
            "viewed_export_receipt_hash": source["export_receipt"]["receipt_hash"],
            "original_run_id": inspection["original_run_id"],
            "manifest_fingerprint": inspection["declared_manifest_fingerprint"],
            "declared_raw_sha256": inspection["declared_raw_sha256"],
            "raw_document_bytes": raw_lengths,
            "confirmed": True,
            "technical_metadata_only_confirmed": True,
            "untrusted_source_acknowledged": True,
        }
    )


def _prepare(snapshot, payload):
    source = _source_metadata(snapshot)
    if source["export_receipt"]["receipt_hash"] != payload.viewed_export_receipt_hash:
        raise Conflict
    try:
        raw = {"receipt": payload.receipt_json.encode("utf-8"), "reconciliation": payload.reconciliation_json.encode("utf-8")}
    except UnicodeError:
        raise ExternalMetadataRejected("External QA metadata rejected; no evidence accepted") from None
    inspection = inspect_local_metadata(
        raw["receipt"],
        raw["reconciliation"],
        original_run_id=payload.original_run_id,
        manifest_fingerprint=payload.manifest_fingerprint,
        receipt_sha256=payload.receipt_sha256,
        reconciliation_sha256=payload.reconciliation_sha256,
    ).to_dict()
    _aligned(inspection, source)
    # Parsing above already rejected duplicates, extra fields, arrays and secrets.
    canonical = {name: _json(json.loads(data)).decode("ascii") for name, data in raw.items()}
    return source, inspection, canonical, {name: len(data) for name, data in raw.items()}


def _document(intake_id, project_id, created_at_ms, source, inspection, canonical, raw_lengths):
    return {
        "schema": "external-qa-quarantine-receipt.v1",
        "scope": "external_technical_metadata_quarantine_only",
        "id": intake_id,
        "project_id": project_id,
        "created_at_ms": created_at_ms,
        "source": source,
        "source_configuration_alignment_only": True,
        "original_run_id": inspection["original_run_id"],
        "inspection": inspection,
        "inspection_sha256": _sha(_json(inspection)),
        "canonical_source_sha256": {name: _sha(value.encode("ascii")) for name, value in canonical.items()},
        "raw_document_bytes": raw_lengths,
        "evidence_admitted": False,
        "approval_granted": False,
        "dispatch_authorized": False,
        "resend_permitted": False,
        "resume_permitted": False,
        "verdict": "NOT_EVALUATED",
    }


def _snapshot_hash(canonical):
    return fingerprint({name: _sha(data.encode("ascii")) for name, data in canonical.items()})


def _decode(row, snapshot):
    """Reinspect canonical bytes, NOT the discarded original byte representation."""
    try:
        document = row["document"]
        source = _source_metadata(snapshot)
        canonical = {"receipt": row["canonical_receipt"], "reconciliation": row["canonical_reconciliation"]}
        for data in canonical.values():
            if type(data) is not str or not 1 <= len(data) <= MAX_DOCUMENT_BYTES or _json(json.loads(data)).decode("ascii") != data:
                raise ValueError
        hashes = {name: _sha(data.encode("ascii")) for name, data in canonical.items()}
        inspection = inspect_local_metadata(
            canonical["receipt"].encode("ascii"),
            canonical["reconciliation"].encode("ascii"),
            original_run_id=row["original_run_id"],
            manifest_fingerprint=source["export_receipt"]["manifest_fingerprint"],
            receipt_sha256=hashes["receipt"],
            reconciliation_sha256=hashes["reconciliation"],
        ).to_dict()
        original_hashes = document["inspection"]["declared_raw_sha256"]
        lengths = document["raw_document_bytes"]
        if (
            type(original_hashes) is not dict
            or set(original_hashes) != {"receipt", "reconciliation"}
            or any(type(v) is not str or re.fullmatch(r"[0-9a-f]{64}", v) is None for v in original_hashes.values())
            or type(lengths) is not dict
            or set(lengths) != {"receipt", "reconciliation"}
            or any(type(v) is not int or not 1 <= v <= MAX_DOCUMENT_BYTES for v in lengths.values())
            or type(row["created_at_ms"]) is not int
            or row["created_at_ms"] <= 0
            or row["owner_id"] != snapshot["project"]["owner_id"]
            or row["project_id"] != snapshot["project"]["id"]
            or row["export_id"] != source["export_receipt"]["id"]
        ):
            raise ValueError
        inspection["declared_raw_sha256"] = original_hashes
        _aligned(inspection, source)
        expected = _document(row["id"], row["project_id"], row["created_at_ms"], source, inspection, canonical, lengths)
        request_hash = _request_hash(source, inspection, lengths)
        if (
            _json(expected) != _json(document)
            or not hmac.compare_digest(request_hash, row["request_hash"])
            or not hmac.compare_digest(_snapshot_hash(canonical), row["snapshot_hash"])
            or not hmac.compare_digest(fingerprint({"owner_id": row["owner_id"], "request_hash": request_hash, "document": expected}), row["archive_hash"])
        ):
            raise ValueError
        return {**expected, "archive_hash": row["archive_hash"]}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, OverflowError, RecursionError, Conflict, RequestProtectionError):
        pass
    # Avoid retaining a JSONDecodeError.doc or validation inputs as exception context.
    raise IntakeIntegrityError(_ERROR)


class ExternalQAIntakeRepository(EvaluationRepository):
    def __init__(self, session_factory, *, clock_ms=None):
        super().__init__(session_factory)
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)

    async def _source(self, session, owner, project_id, export_id, *, lock=False):
        project = await self._project(session, owner, project_id)
        statement = select(*ExportRepository._metadata).where(t.exports.c.id == export_id, t.exports.c.project_id == project_id, t.exports.c.owner_id == owner)
        row = (await session.execute(statement.with_for_update() if lock else statement)).mappings().first()
        if row is None:
            raise NotFound
        statement = select(t.plans).where(t.plans.c.project_id == project_id, t.plans.c.id == row["plan_id"])
        plan = (await session.execute(statement.with_for_update() if lock else statement)).mappings().first()
        if plan is None:
            raise NotFound
        return {"project": project, "export": dict(row), "plan": dict(plan)}

    async def _row(self, session, owner, project_id, intake_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.external_qa_intakes).where(t.external_qa_intakes.c.id == intake_id, t.external_qa_intakes.c.project_id == project_id, t.external_qa_intakes.c.owner_id == owner))).mappings().first()
        return dict(row) if row is not None else None

    async def create(self, owner, project_id, intake_id, payload):
        _identifier(intake_id)
        payload = ExternalQAIntakeCreate.model_validate(payload.model_dump())
        return await _drain(self._create(owner, project_id, intake_id, payload))

    async def _create(self, owner, project_id, intake_id, payload):
        async with self.sf() as session:
            if await self._row(session, owner, project_id, intake_id):
                raise Conflict  # Uncertain outcomes reconcile by GET, never PUT.
            snapshot = await self._source(session, owner, project_id, payload.export_id)
        source, inspection, canonical, lengths = await asyncio.to_thread(_prepare, snapshot, payload)
        created_at = self.clock_ms()
        if type(created_at) is not int or not 1 <= created_at <= 253_402_300_799_000:
            raise IntakeIntegrityError(_ERROR)
        document = _document(intake_id, project_id, created_at, source, inspection, canonical, lengths)
        request_hash = _request_hash(source, inspection, lengths)
        row = {
            "id": intake_id,
            "owner_id": owner,
            "project_id": project_id,
            "export_id": payload.export_id,
            "original_run_id": inspection["original_run_id"],
            "created_at_ms": created_at,
            "request_hash": request_hash,
            "snapshot_hash": _snapshot_hash(canonical),
            "archive_hash": fingerprint({"owner_id": owner, "request_hash": request_hash, "document": document}),
            "document": document,
            "canonical_receipt": canonical["receipt"],
            "canonical_reconciliation": canonical["reconciliation"],
        }
        # Validate our receipt before committing, not only on later reads.
        result = await asyncio.to_thread(_decode, row, snapshot)
        try:
            async with self.sf.begin() as session:
                locked = (await session.execute(update(t.projects).where(t.projects.c.id == project_id, t.projects.c.owner_id == owner).values(id=t.projects.c.id).returning(t.projects))).mappings().first()
                if locked is None:
                    raise NotFound
                if _json(dict(locked)) != _json(snapshot["project"]) or _json(snapshot) != _json(await self._source(session, owner, project_id, payload.export_id, lock=True)):
                    raise Conflict
                if await self._row(session, owner, project_id, intake_id):
                    raise Conflict
                await session.execute(insert(t.external_qa_intakes).values(**row))
                await self._event(session, owner, project_id, intake_id)
        except IntegrityError:
            raise Conflict from None
        return result

    async def _event(self, session, owner, project_id, intake_id):
        sequence = (await session.scalar(select(func.max(t.external_qa_intake_audit.c.sequence)).where(t.external_qa_intake_audit.c.intake_id == intake_id))) or 0
        await session.execute(insert(t.external_qa_intake_audit).values(id=uuid4().hex, project_id=project_id, intake_id=intake_id, actor=owner, action="metadata_quarantined", sequence=sequence + 1, at_ms=self.clock_ms()))

    async def get(self, owner, project_id, intake_id):
        _identifier(intake_id)
        return await _drain(self._get(owner, project_id, intake_id))

    async def _get(self, owner, project_id, intake_id):
        async with self.sf() as session:
            row = await self._row(session, owner, project_id, intake_id)
            if row is None:
                raise NotFound
            source = await self._source(session, owner, project_id, row["export_id"])
        return await asyncio.to_thread(_decode, row, source)

    async def audit(self, owner, project_id, intake_id, *, after_sequence=0, limit=100):
        _identifier(intake_id)
        if type(after_sequence) is not int or not 0 <= after_sequence <= 2_147_483_647 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid audit page")
        return await _drain(self._audit(owner, project_id, intake_id, after_sequence, limit))

    async def _audit(self, owner, project_id, intake_id, after_sequence, limit):
        await self._get(owner, project_id, intake_id)
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            return [
                dict(row)
                for row in (
                    await session.execute(
                        select(t.external_qa_intake_audit)
                        .where(t.external_qa_intake_audit.c.project_id == project_id, t.external_qa_intake_audit.c.intake_id == intake_id, t.external_qa_intake_audit.c.sequence > after_sequence)
                        .order_by(t.external_qa_intake_audit.c.sequence)
                        .limit(limit)
                    )
                ).mappings()
            ]
