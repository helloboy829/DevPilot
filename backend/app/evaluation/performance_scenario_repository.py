"""Owner-scoped creation and integrity checking for frozen performance scenarios."""

import hmac
from uuid import uuid4

from sqlalchemy import insert, select

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, dataset_hash
from app.evaluation.performance_scenarios import PerformanceProfile, build_case_manifest
from app.evaluation.plan_repository import PlanRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, EvaluationRepository, NotFound, now


class PerformanceScenarioRepository(EvaluationRepository):
    async def create(self, owner, project_id, component_id, plan_id, profile: PerformanceProfile):
        async with self.sf.begin() as session:
            await self._project(session, owner, project_id)
            linked = (await session.execute(select(t.project_components.c.id).where(t.project_components.c.project_id == project_id, t.project_components.c.id == component_id))).first()
            if linked is None:
                raise NotFound
            plan_row = (await session.execute(select(t.plans).where(t.plans.c.project_id == project_id, t.plans.c.component_id == component_id, t.plans.c.id == plan_id))).mappings().first()
            if plan_row is None:
                raise NotFound
            plan = PlanRepository._public_plan(dict(plan_row))
            definition = plan["definition"]
            if definition.get("limits", {}).get("mode") != "performance" or profile.measured_request_count != definition.get("limits", {}).get("request_count"):
                raise Conflict
            dataset = await self._dataset(session, owner, project_id, plan["dataset_id"])
            if dataset["status"] != "frozen":
                raise Conflict
            rows = (
                (
                    await session.execute(
                        select(t.samples, t.references.c.expected)
                        .outerjoin(t.references, (t.samples.c.dataset_id == t.references.c.dataset_id) & (t.samples.c.sample_id == t.references.c.sample_id))
                        .where(t.samples.c.dataset_id == dataset["id"])
                        .order_by(t.samples.c.sample_id)
                    )
                )
                .mappings()
                .all()
            )
            try:
                samples = [QASample.model_validate({key: value for key, value in row.items() if key != "dataset_id"}) for row in rows]
                if len(samples) != dataset["sample_count"] or dataset_hash(dataset["source"], dataset["purpose"], samples) != dataset["content_hash"]:
                    raise ValueError
                case_ids = [sample.sample_id for sample in samples]
                if profile.measured_request_count > 10_000 or profile.warmup_request_count > 1_000:
                    raise ValueError
                manifest = build_case_manifest(case_ids, warmup_count=profile.warmup_request_count, measured_count=profile.measured_request_count)
            except (ValueError, TypeError, KeyError):
                raise Conflict from None
            scenario = {
                "schema": "devpilot-performance-scenario.v1",
                "scope": "frozen_definition_only",
                "project_id": project_id,
                "component_id": component_id,
                "plan_id": plan_id,
                "plan_hash": plan["definition_hash"],
                "dataset_id": dataset["id"],
                "dataset_revision": dataset["revision"],
                "dataset_hash": dataset["content_hash"],
                "case_order": sorted(case_ids),
                "profile": profile.model_dump(mode="json"),
                "manifest": manifest,
            }
            row = {
                "id": uuid4().hex,
                "project_id": project_id,
                "component_id": component_id,
                "plan_id": plan_id,
                "version": 1,
                "definition": scenario,
                "definition_hash": fingerprint(scenario),
                "created_by": owner,
                "created_at": now(),
            }
            await session.execute(insert(t.performance_scenarios).values(**row))
            await session.execute(insert(t.performance_scenario_audit).values(id=uuid4().hex, project_id=project_id, scenario_id=row["id"], actor=owner, action="scenario_frozen", at=now()))
        return self._public(row)

    @staticmethod
    def _public(row):
        try:
            definition = row["definition"]
            if not isinstance(definition, dict) or definition.get("scope") != "frozen_definition_only":
                raise ValueError
            if not hmac.compare_digest(fingerprint(definition), row["definition_hash"]):
                raise ValueError
            profile = PerformanceProfile.model_validate(definition["profile"])
            case_order = definition["case_order"]
            expected_manifest = build_case_manifest(case_order, warmup_count=profile.warmup_request_count, measured_count=profile.measured_request_count)
            if definition["manifest"] != expected_manifest:
                raise ValueError
            if definition["project_id"] != row["project_id"] or definition["component_id"] != row["component_id"] or definition["plan_id"] != row["plan_id"]:
                raise ValueError
            return dict(row)
        except (ValueError, TypeError, KeyError):
            raise Conflict from None

    async def list(self, owner, project_id, component_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            linked = (await session.execute(select(t.project_components.c.id).where(t.project_components.c.project_id == project_id, t.project_components.c.id == component_id))).first()
            if linked is None:
                raise NotFound
            rows = (
                (
                    await session.execute(
                        select(t.performance_scenarios)
                        .where(t.performance_scenarios.c.project_id == project_id, t.performance_scenarios.c.component_id == component_id)
                        .order_by(t.performance_scenarios.c.created_at, t.performance_scenarios.c.id)
                        .limit(100)
                    )
                )
                .mappings()
                .all()
            )
            return [self._public(dict(row)) for row in rows]

    async def get(self, owner, project_id, scenario_id):
        async with self.sf() as session:
            await self._project(session, owner, project_id)
            row = (await session.execute(select(t.performance_scenarios).where(t.performance_scenarios.c.project_id == project_id, t.performance_scenarios.c.id == scenario_id))).mappings().first()
            if row is None:
                raise NotFound
            return self._public(dict(row))
