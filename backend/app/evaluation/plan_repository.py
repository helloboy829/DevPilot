"""Owner-scoped immutable QA plans; preflight only, never HTTP execution."""

import asyncio
import hmac
from uuid import uuid4

from devpilot.qa_json_binding import QAJSONBinding
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, dataset_hash
from app.evaluation.plans import PlanCreate, PlanDefinition, PlanPreflightError
from app.evaluation.registry import fingerprint, version_key
from app.evaluation.repository import Conflict, NotFound, now
from app.evaluation.request_version_repository import RequestVersionRepository


def _verified_inputs(dataset, rows):
    """Verify gold-bound integrity separately; only input text goes to render()."""
    try:
        samples = [QASample.model_validate(dict(row)) for row in rows]
        if not 1 <= len(samples) <= 500 or len(samples) != dataset["sample_count"] or dataset_hash(dataset["source"], dataset["purpose"], samples) != dataset["content_hash"]:
            raise ValueError
        if len({sample.sample_id for sample in samples}) != len(samples):
            raise ValueError
        return tuple(sample.input for sample in sorted(samples, key=lambda sample: sample.sample_id))
    except (ValueError, TypeError, KeyError):
        raise Conflict from None


def _preflight(frozen, inputs, payload):
    try:
        count, requested = len(inputs), payload.limits.request_count
        if requested < count or (payload.limits.mode == "effectiveness" and requested != count):
            raise ValueError
        binding = QAJSONBinding.from_dict(payload.binding)
        cycles, remainder = divmod(requested, count)
        total = 0
        for index, question in enumerate(inputs):
            prepared = binding.render(frozen, question)
            total += len(prepared.body.encode("utf-8")) * (cycles + (index < remainder))
            if total > payload.limits.max_total_body_bytes:
                raise ValueError
        return {"sample_count": count, "request_count": requested, "total_body_bytes": total}
    except (ValueError, TypeError, UnicodeError):
        raise PlanPreflightError from None


class PlanRepository(RequestVersionRepository):
    async def create_plan(self, owner, project_id, component_id, payload: PlanCreate):
        payload = PlanCreate.model_validate(payload.model_dump())
        try:
            async with self.sf.begin() as session:
                await self._linked_component(session, owner, project_id, component_id)
                version = await self._request_version(session, owner, project_id, payload.request_version_id, protected=True)
                if version["component_id"] != component_id:
                    raise NotFound
                dataset = await self._dataset(session, owner, project_id, payload.dataset_id)
                if dataset["status"] != "frozen" or dataset["revision"] != payload.dataset_revision or dataset["content_hash"] != payload.dataset_hash or version["protected_hash"] != payload.request_protected_hash:
                    raise Conflict
                # Outer join catches missing gold rows instead of silently omitting inputs.
                rows = (
                    (
                        await session.execute(
                            select(t.samples.c.sample_id, t.samples.c.input, t.samples.c.source_ref, t.samples.c.slice_tag, t.references.c.expected)
                            .outerjoin(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                            .where(t.samples.c.dataset_id == dataset["id"])
                            .limit(501)
                        )
                    )
                    .mappings()
                    .all()
                )
                inputs = await asyncio.to_thread(_verified_inputs, dataset, rows)
                frozen = await self._open_request_row(session, owner, version)
                checked = await asyncio.to_thread(_preflight, frozen, inputs, payload)
                definition = PlanDefinition.model_validate(
                    {
                        **payload.model_dump(exclude={"confirmed"}),
                        "schema": "qa-json-plan.v1",
                        "scope": "frozen_definition_only",
                        "project_id": project_id,
                        "component_id": component_id,
                        "request_template_fingerprint": frozen.template.fingerprint,
                        "dataset_purpose": dataset["purpose"],
                        "sample_order": "sample_id_ascending_cycle.v1",
                        "evaluation_policy": "human_review_required.v1",
                        "preflight": checked,
                    }
                ).model_dump(by_alias=True)
                row = {
                    "id": uuid4().hex,
                    "project_id": project_id,
                    "component_id": component_id,
                    "request_version_id": version["id"],
                    "dataset_id": dataset["id"],
                    "version_label": payload.version_label,
                    "label_key": version_key(payload.version_label),
                    "scope": "frozen_definition_only",
                    "definition": definition,
                    "definition_hash": fingerprint(definition),
                    "created_by": owner,
                    "created_at": now(),
                }
                await session.execute(insert(t.plans).values(**row))
                await session.execute(insert(t.plan_audit).values(id=uuid4().hex, project_id=project_id, plan_id=row["id"], actor=owner, action="plan_frozen", at=now()))
            return self._public_plan(row)
        except IntegrityError:
            raise Conflict from None

    @staticmethod
    def _public_plan(row):
        try:
            definition = row["definition"]
            validated = PlanDefinition.model_validate(definition).model_dump(by_alias=True)
            if definition != validated or not hmac.compare_digest(fingerprint(validated), row["definition_hash"]):
                raise ValueError
            for name in ("project_id", "component_id", "request_version_id", "dataset_id", "version_label", "scope"):
                if row[name] != validated[name]:
                    raise ValueError
            return {key: value for key, value in row.items() if key != "label_key"}
        except (ValueError, TypeError, KeyError):
            raise Conflict from None

    async def list_plans(self, owner, project_id, component_id):
        async with self.sf() as session:
            await self._linked_component(session, owner, project_id, component_id)
            rows = await session.execute(select(t.plans).where(t.plans.c.project_id == project_id, t.plans.c.component_id == component_id).order_by(t.plans.c.created_at, t.plans.c.id))
            return [self._public_plan(dict(row)) for row in rows.mappings()]

    async def _plan(self, session, owner, project_id, plan_id):
        await self._project(session, owner, project_id)
        row = (await session.execute(select(t.plans).where(t.plans.c.project_id == project_id, t.plans.c.id == plan_id))).mappings().first()
        if row is None:
            raise NotFound
        return self._public_plan(dict(row))

    async def get_plan(self, owner, project_id, plan_id):
        async with self.sf() as session:
            return await self._plan(session, owner, project_id, plan_id)

    async def plan_audit(self, owner, project_id, plan_id):
        async with self.sf() as session:
            await self._plan(session, owner, project_id, plan_id)
            rows = await session.execute(select(t.plan_audit).where(t.plan_audit.c.project_id == project_id, t.plan_audit.c.plan_id == plan_id).order_by(t.plan_audit.c.at, t.plan_audit.c.id))
            return [dict(row) for row in rows.mappings()]
