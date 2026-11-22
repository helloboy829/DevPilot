"""Owner-scoped, no-network performance run ledger behavior."""

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from test_dispatch_journal import prepared as prepared
from test_evaluation_plans import draft, limits

from app.evaluation import tables as t
from app.evaluation.performance_run_repository import PerformanceRunRepository
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


async def make_scenario(prepared):
    repo, _, project_id, source_plan, _ = prepared
    source = source_plan["definition"]
    plan = await repo.create_plan(
        "owner",
        project_id,
        source_plan["component_id"],
        PlanCreate.model_validate(
            draft(
                {"id": source["request_version_id"], "protected_hash": source["request_protected_hash"]},
                {"id": source["dataset_id"], "revision": source["dataset_revision"], "content_hash": source["dataset_hash"]},
                limits=limits(mode="performance", request_count=5),
            )
        ),
    )
    scenario = await PerformanceScenarioRepository(repo.sf).create("owner", project_id, source_plan["component_id"], plan["id"], profile())
    return repo, project_id, scenario


@pytest.mark.asyncio
async def test_create_run_freezes_scenario_population_and_is_owner_scoped(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)

    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    assert run["status"] == "created"
    assert run["population_count"] == len(scenario["definition"]["manifest"]) == 6
    assert run["scenario_hash"] == scenario["definition_hash"]
    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["ordinal"] for row in dispatches] == list(range(6))
    assert [row["phase"] for row in dispatches] == ["warmup", "measurement", "measurement", "measurement", "measurement", "measurement"]
    with pytest.raises(NotFound):
        await runs.get_run("another-owner", project_id, run["id"])


@pytest.mark.asyncio
async def test_create_run_requires_confirmation_and_exact_scenario_hash(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)

    with pytest.raises(Conflict):
        await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=False)
    with pytest.raises(Conflict):
        await runs.create_run("owner", project_id, scenario["id"], "0" * 64, confirmed=True)


@pytest.mark.asyncio
async def test_dispatch_ack_commits_once_before_observation_and_unknown_interrupts_run(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    assert ticket == {"run_id": run["id"], "ordinal": 0, "dispatch_id": ticket["dispatch_id"]}
    with pytest.raises(Conflict):
        await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=101)
    await runs.record_observation("owner", project_id, ticket, state="unknown", finished_ns=200, elapsed_ms=0.0001)
    with pytest.raises(Conflict):
        await runs.record_observation("owner", project_id, ticket, state="succeeded", finished_ns=201, elapsed_ms=0.0001)

    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in dispatches] == ["unknown", "not_dispatched", "not_dispatched", "not_dispatched", "not_dispatched", "not_dispatched"]
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert [event["sequence"] for event in audit] == list(range(1, len(audit) + 1))
    assert [event["action"] for event in audit] == ["run_created", "dispatch_acknowledged", "observation_recorded", "run_interrupted"]


@pytest.mark.asyncio
async def test_completed_run_reconciles_all_terminal_observations(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    tickets = []
    for ordinal in range(run["population_count"]):
        tickets.append(await runs.acknowledge_dispatch("owner", project_id, run["id"], ordinal, send_started_ns=100 + ordinal))
    await runs.close_measurement_window("owner", project_id, run["id"], window_end_ns=106)
    for ordinal, ticket in enumerate(tickets):
        await runs.record_observation("owner", project_id, ticket, state="succeeded", finished_ns=200 + ordinal, elapsed_ms=0.1)

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "completed"
    assert result["window_start_ns"] == 101
    assert result["window_end_ns"] == 106
    assert result["state_counts"] == {"pending": 0, "dispatched": 0, "succeeded": 6, "failed": 0, "timeout": 0, "unknown": 0, "not_dispatched": 0}
    assert result["metrics"]["cohort_count"] == 5
    assert result["metrics"]["successful_latency_ms"]["n"] == 5
    assert result["metrics"]["attempt_qps"] == 1_000_000_000

    async with repo.sf() as session:
        events = (await session.execute(select(t.performance_run_audit.c.action).where(t.performance_run_audit.c.run_id == run["id"]).order_by(t.performance_run_audit.c.sequence))).scalars().all()
    assert events.count("run_finished") == 1


@pytest.mark.asyncio
async def test_database_rejects_duplicate_dispatch_ordinal(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    with pytest.raises(IntegrityError):
        async with repo.sf.begin() as session:
            await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 1).values(ordinal=0))


@pytest.mark.asyncio
async def test_interrupt_keeps_acknowledged_dispatch_as_right_censored_unknown(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.acknowledge_dispatch("owner", project_id, run["id"], 1, send_started_ns=100)

    assert await runs.interrupt_run("owner", project_id, run["id"], at_ns=150) is True

    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    censored = dispatches[1]
    assert censored["state"] == "unknown"
    assert censored["send_started_ns"] == 100
    assert censored["finished_ns"] is None
    assert censored["elapsed_ms"] is None
    assert [row["state"] for row in dispatches[2:]] == ["not_dispatched"] * 4


@pytest.mark.asyncio
async def test_database_rejects_timing_on_pending_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    with pytest.raises(IntegrityError):
        async with repo.sf.begin() as session:
            await session.execute(update(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 1).values(send_started_ns=100))


@pytest.mark.asyncio
async def test_dispatch_page_limit_covers_maximum_frozen_population(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    assert await runs.list_dispatches("owner", project_id, run["id"], offset=10_800, limit=200) == []
