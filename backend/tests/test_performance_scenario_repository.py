import json

import pytest
from sqlalchemy import select
from test_dispatch_journal import prepared as prepared
from test_evaluation_plans import draft, limits

from app.evaluation import tables as t
from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceProfile
from app.evaluation.plans import PlanCreate
from app.evaluation.repository import Conflict, NotFound


def profile(**changes):
    return PerformanceProfile.model_validate(
        {
            "concurrency": 2,
            "measured_request_count": 5,
            "warmup_request_count": 1,
            "duration_limit_seconds": None,
            "request_timeout_ms": 1000,
            "max_in_flight": 2,
            "wall_time_limit_seconds": 60,
            "drain_limit_seconds": 10,
            "max_request_bytes": 10000,
            "max_response_bytes": 10000,
            "max_total_bytes": 100000,
            **changes,
        }
    )


@pytest.mark.asyncio
async def test_scenario_freezes_sorted_manifest_owner_scope_and_audit(prepared):
    repo, _, project, source_plan, _ = prepared
    project_id = project
    source = source_plan["definition"]
    component_id = source_plan["component_id"]
    version = {"id": source["request_version_id"], "protected_hash": source["request_protected_hash"]}
    dataset = {key: source[key] for key in ("dataset_id", "dataset_revision", "dataset_hash")}
    dataset = {"id": dataset["dataset_id"], "revision": dataset["dataset_revision"], "content_hash": dataset["dataset_hash"]}
    plan = await repo.create_plan("owner", project_id, component_id, PlanCreate.model_validate(draft(version, dataset, limits=limits(mode="performance", request_count=5))))
    scenarios = PerformanceScenarioRepository(repo.sf)
    result = await scenarios.create("owner", project_id, component_id, plan["id"], profile())
    definition = result["definition"]
    assert [(entry["phase"], entry["case_id"], entry["iteration"]) for entry in definition["manifest"]] == [
        ("warmup", "a", 0),
        ("measurement", "a", 0),
        ("measurement", "z", 0),
        ("measurement", "a", 1),
        ("measurement", "z", 1),
        ("measurement", "a", 2),
    ]
    assert "expected" not in json.dumps(result)
    assert await scenarios.get("owner", project_id, result["id"]) == result
    async with repo.sf() as session:
        events = (await session.execute(select(t.performance_scenario_audit.c.action))).scalars().all()
    assert events == ["scenario_frozen"]
    with pytest.raises(NotFound):
        await scenarios.get("another-owner", project_id, result["id"])


@pytest.mark.asyncio
async def test_scenario_rejects_measurement_count_different_from_frozen_plan(prepared):
    repo, _, project_id, plan, _ = prepared
    source = plan["definition"]
    performance_plan = await repo.create_plan(
        "owner",
        project_id,
        plan["component_id"],
        PlanCreate.model_validate(
            draft(
                {"id": source["request_version_id"], "protected_hash": source["request_protected_hash"]},
                {"id": source["dataset_id"], "revision": source["dataset_revision"], "content_hash": source["dataset_hash"]},
                limits=limits(mode="performance", request_count=3),
            )
        ),
    )
    with pytest.raises(Conflict):
        await PerformanceScenarioRepository(repo.sf).create("owner", project_id, plan["component_id"], performance_plan["id"], profile(measured_request_count=5))


@pytest.mark.asyncio
async def test_scenario_rejects_effectiveness_plan(prepared):
    repo, _, project, source_plan, _ = prepared
    project_id = project
    source = source_plan["definition"]
    component_id = source_plan["component_id"]
    version = {"id": source["request_version_id"], "protected_hash": source["request_protected_hash"]}
    dataset = {"id": source["dataset_id"], "revision": source["dataset_revision"], "content_hash": source["dataset_hash"]}
    plan = await repo.create_plan("owner", project_id, component_id, PlanCreate.model_validate(draft(version, dataset)))
    with pytest.raises(Conflict):
        await PerformanceScenarioRepository(repo.sf).create("owner", project_id, component_id, plan["id"], profile())
