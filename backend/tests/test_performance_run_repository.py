"""Owner-scoped, no-network performance run ledger behavior."""

import asyncio
import hashlib
import threading
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError
from test_dispatch_journal import prepared as prepared
from test_evaluation_plans import draft, limits

from app.evaluation import performance_run_repository as performance_run_repository_module
from app.evaluation import schema
from app.evaluation import tables as t
from app.evaluation.performance_run_repository import PerformanceRunRepository
from app.evaluation.performance_scenario_repository import PerformanceScenarioRepository
from app.evaluation.performance_scenarios import PerformanceProfile
from app.evaluation.plans import PlanCreate
from app.evaluation.qa_artifact_store import ResponseArtifactStore
from app.evaluation.qa_evidence import EvidenceAccessCreate
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


async def make_scenario(prepared, *, profile_overrides=None):
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
    scenario = await PerformanceScenarioRepository(repo.sf).create("owner", project_id, source_plan["component_id"], plan["id"], profile(**(profile_overrides or {})))
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
async def test_list_runs_is_project_and_owner_scoped_with_stable_cursor_pages(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    expected_ids = [f"{value:032x}" for value in (1, 2, 3)]
    for run_id in expected_ids:
        await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True, run_id=run_id)

    first = await runs.list_runs("owner", project_id, limit=2)
    second = await runs.list_runs("owner", project_id, limit=2, cursor=first["next_cursor"])

    assert first["total"] == 3
    assert [item["id"] for item in first["items"]] == list(reversed(expected_ids[1:]))
    assert [item["id"] for item in second["items"]] == expected_ids[:1]
    assert second["next_cursor"] is None
    with pytest.raises(NotFound):
        await runs.list_runs("another-owner", project_id)
    with pytest.raises(ValueError):
        await runs.list_runs("owner", project_id, limit=201)
    with pytest.raises(ValueError):
        await runs.list_runs("owner", project_id, cursor="not-a-cursor")


@pytest.mark.asyncio
async def test_create_run_requires_confirmation_and_exact_scenario_hash(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)

    with pytest.raises(Conflict):
        await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=False)
    with pytest.raises(Conflict):
        await runs.create_run("owner", project_id, scenario["id"], "0" * 64, confirmed=True)


@pytest.mark.asyncio
async def test_create_run_accepts_only_caller_preallocated_id_when_provided(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    expected_id = "a" * 32

    run = await runs.create_run(
        "owner",
        project_id,
        scenario["id"],
        scenario["definition_hash"],
        confirmed=True,
        run_id=expected_id,
    )

    assert run["id"] == expected_id
    with pytest.raises(Conflict):
        await runs.create_run(
            "owner",
            project_id,
            scenario["id"],
            scenario["definition_hash"],
            confirmed=True,
            run_id="invalid",
        )


@pytest.mark.asyncio
async def test_dispatch_ack_commits_once_before_observation_and_unknown_interrupts_run(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    assert ticket == {
        "run_id": run["id"],
        "ordinal": 0,
        "dispatch_id": ticket["dispatch_id"],
        "response_artifact_id": ticket["response_artifact_id"],
        "worker_id": "legacy-owner",
        "lease_epoch": 1,
    }
    with pytest.raises(Conflict):
        await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=101)
    with pytest.raises(Conflict):
        await runs.record_observation("owner", project_id, {**ticket, "response_artifact_id": "0" * 32}, state="succeeded", finished_ns=150, elapsed_ms=0.0001)
    await runs.record_observation("owner", project_id, ticket, state="unknown", finished_ns=200, elapsed_ms=0.0001)
    with pytest.raises(Conflict):
        await runs.record_observation("owner", project_id, ticket, state="succeeded", finished_ns=201, elapsed_ms=0.0001)
    async with repo.sf() as session:
        artifact_status = (await session.execute(select(t.performance_response_artifacts.c.status).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).scalar_one()
    assert artifact_status == "write_unknown"

    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in dispatches] == ["unknown", "not_dispatched", "not_dispatched", "not_dispatched", "not_dispatched", "not_dispatched"]
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert [event["sequence"] for event in audit] == list(range(1, len(audit) + 1))
    assert [event["action"] for event in audit] == ["run_created", "dispatch_claimed", "dispatch_acknowledged", "dispatch_started", "observation_recorded", "run_interrupted"]


@pytest.mark.asyncio
async def test_dispatch_ack_reserves_one_response_artifact_bound_to_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    assert ticket["response_artifact_id"]
    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
    assert (artifact["project_id"], artifact["run_id"], artifact["ordinal"], artifact["dispatch_id"]) == (
        project_id,
        run["id"],
        ticket["ordinal"],
        ticket["dispatch_id"],
    )
    assert artifact["status"] == "pending"


@pytest.mark.asyncio
async def test_observation_encrypts_response_and_persists_receipt(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    key = Fernet.generate_key()
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", key)
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)
    body = b"synthetic response"
    digest = hashlib.sha256(body).hexdigest()

    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=len(body),
        response_hash=digest,
        response_body=body,
        response_capture_status="complete",
        response_content_type="text/plain",
        response_content_encoding="identity",
    )

    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
    ciphertext = store._path(ticket["response_artifact_id"]).read_bytes()
    assert artifact["status"] == "complete"
    assert artifact["response_sha256"] == digest
    assert artifact["captured_bytes"] == artifact["observed_bytes"] == len(body)
    assert artifact["receipt_hash"]
    assert artifact["sealed_sha256"] == hashlib.sha256(ciphertext).hexdigest()
    assert body not in ciphertext


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
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 1, send_started_ns=100)

    assert await runs.interrupt_run("owner", project_id, run["id"], at_ns=150) is True

    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    censored = dispatches[1]
    assert censored["state"] == "unknown"
    assert censored["send_started_ns"] == 100
    assert censored["finished_ns"] is None
    assert censored["elapsed_ms"] is None
    assert [row["state"] for row in dispatches[2:]] == ["not_dispatched"] * 4
    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts.c.status).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).scalar_one()
    assert artifact == "write_unknown"


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


@pytest.mark.asyncio
async def test_not_received_observation_does_not_create_a_body_object(prepared, tmp_path):
    repo, project_id, scenario = await make_scenario(prepared)
    key = Fernet.generate_key()
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", key)
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="failed",
        finished_ns=200,
        elapsed_ms=0.1,
        response_capture_status="not_received",
    )

    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
    assert artifact["status"] == "not_received"
    assert artifact["hash_scope"] == "none"
    assert artifact["sealed_sha256"] is None
    assert not store._path(ticket["response_artifact_id"]).exists()


@pytest.mark.asyncio
async def test_truncated_observation_keeps_full_hash_separate_from_encrypted_prefix(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)
    prefix = b"x" * 1_048_576
    response_hash = hashlib.sha256(b"x" * 2_000_000).hexdigest()

    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=2_000_000,
        response_hash=response_hash,
        response_body=prefix,
        response_capture_status="truncated",
        response_content_type="application/octet-stream",
        response_content_encoding="identity",
    )

    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
        dispatch = (await session.execute(select(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 0))).mappings().one()
    assert dispatch["response_hash"] == response_hash
    assert dispatch["response_bytes"] == 2_000_000
    assert artifact["status"] == "truncated"
    assert artifact["response_sha256"] is None
    assert artifact["captured_prefix_sha256"] == hashlib.sha256(prefix).hexdigest()
    assert artifact["captured_bytes"] == 1_048_576
    assert artifact["observed_bytes"] == 2_000_000


@pytest.mark.asyncio
async def test_policy_skipped_observation_records_metadata_without_body_storage(prepared, tmp_path):
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=10_000_000,
        response_hash="a" * 64,
        response_capture_status="policy_skipped",
    )

    async with repo.sf() as session:
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
        dispatch = (await session.execute(select(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 0))).mappings().one()
    assert artifact["status"] == "policy_skipped"
    assert artifact["hash_scope"] == "none"
    assert artifact["observed_bytes"] == 10_000_000
    assert dispatch["response_bytes"] == 10_000_000
    assert not store._path(ticket["response_artifact_id"]).exists()


@pytest.mark.asyncio
async def test_missing_response_object_reconciles_to_write_failed_without_republish(prepared, tmp_path, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)
    body = b"synthetic response"
    monkeypatch.setattr(store, "publish", lambda *_args: (_ for _ in ()).throw(OSError("write failed before publish")))

    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=len(body),
        response_hash=hashlib.sha256(body).hexdigest(),
        response_body=body,
        response_capture_status="complete",
    )
    monkeypatch.setattr(store, "publish", lambda *_args: pytest.fail("reconcile must not republish"))

    result = await runs.reconcile_response_artifact("owner", project_id, run["id"], 0)

    assert result == {"artifact_id": ticket["response_artifact_id"], "status": "write_failed", "reconciled": True}


@pytest.mark.asyncio
async def test_publish_then_error_reconciles_the_same_performance_artifact_id(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    key = Fernet.generate_key()
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", key)
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)
    body = b"synthetic response"
    publish = store.publish

    def publish_then_raise(*args):
        publish(*args)
        raise OSError("synthetic lost receipt")

    monkeypatch.setattr(store, "publish", publish_then_raise)
    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=len(body),
        response_hash=hashlib.sha256(body).hexdigest(),
        response_body=body,
        response_capture_status="complete",
        response_content_type="text/plain",
        response_content_encoding="identity",
    )
    async with repo.sf() as session:
        before = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
    assert before["status"] == "write_unknown"
    monkeypatch.setattr(store, "publish", lambda *_args: pytest.fail("reconcile must not republish"))

    result = await runs.reconcile_response_artifact("owner", project_id, run["id"], 0)

    assert result == {"artifact_id": ticket["response_artifact_id"], "status": "complete", "reconciled": True}
    async with repo.sf() as session:
        after = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).mappings().one()
    assert after["receipt_hash"]


@pytest.mark.asyncio
async def test_response_evidence_access_is_actor_bound_audited_and_one_time(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)
    body = b"response evidence"
    evidence_hash = hashlib.sha256(body).hexdigest()
    await runs.record_observation(
        "owner",
        project_id,
        ticket,
        state="succeeded",
        finished_ns=200,
        elapsed_ms=0.1,
        response_status=200,
        response_bytes=len(body),
        response_hash=evidence_hash,
        response_body=body,
        response_capture_status="complete",
        response_content_type="application/octet-stream",
    )

    grant = await runs.create_response_evidence_access(
        "owner",
        project_id,
        run["id"],
        0,
        EvidenceAccessCreate(kind="response", evidence_hash=evidence_hash, confirmed=True),
    )

    assert grant["evidence_hash"] == evidence_hash
    assert await runs.read_response_evidence_access("owner", grant["access_id"], "bytes=1-3", project_id=project_id) == {
        "body": body[1:4],
        "content_type": "application/octet-stream",
        "status_code": 206,
        "content_range": f"bytes 1-3/{len(body)}",
    }
    with pytest.raises(NotFound):
        await runs.read_response_evidence_access("another-owner", grant["access_id"], project_id=project_id)
    with pytest.raises(NotFound):
        await runs.read_response_evidence_access("owner", grant["access_id"], project_id=project_id)

    events = await runs.run_audit("owner", project_id, run["id"])
    assert [row["action"] for row in events][-2:] == ["response_access_granted", "response_access_read"]
    assert all(row["actor"] == "owner" for row in events[-2:])


@pytest.mark.asyncio
async def test_dispatch_claim_ack_and_send_start_have_separate_durable_boundaries(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    lease = await runs.claim_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_expires_at_ms=int(time.time() * 1000) + 60_000)
    assert lease["dispatch_id"]
    assert lease["worker_id"] == "worker-a"
    assert lease["lease_epoch"] == 1

    ticket = await runs.acknowledge_dispatch(
        "owner",
        project_id,
        run["id"],
        0,
        worker_id="worker-a",
        lease_epoch=lease["lease_epoch"],
        request_bytes=12,
    )
    assert ticket["dispatch_id"] == lease["dispatch_id"]
    row = (await runs.list_dispatches("owner", project_id, run["id"]))[0]
    assert row["state"] == "pending"
    assert row["send_started_ns"] is None

    started = await runs.start_dispatch(
        "owner",
        project_id,
        run["id"],
        ticket,
        worker_id="worker-a",
        lease_epoch=lease["lease_epoch"],
        send_started_ns=100,
    )
    assert started["dispatch_id"] == ticket["dispatch_id"]
    row = (await runs.list_dispatches("owner", project_id, run["id"]))[0]
    assert row["state"] == "dispatched"
    assert row["send_started_ns"] == 100


@pytest.mark.asyncio
async def test_stale_dispatch_fence_cannot_ack_or_start(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    lease = await runs.claim_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_expires_at_ms=int(time.time() * 1000) + 60_000)

    with pytest.raises(Conflict):
        await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, worker_id="worker-b", lease_epoch=lease["lease_epoch"])
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_epoch=lease["lease_epoch"])
    with pytest.raises(Conflict):
        await runs.start_dispatch("owner", project_id, run["id"], ticket, worker_id="worker-b", lease_epoch=lease["lease_epoch"], send_started_ns=100)


@pytest.mark.asyncio
async def test_concurrent_claims_have_one_winner_and_one_fenced_epoch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    deadline = int(time.time() * 1000) + 60_000

    results = await asyncio.gather(
        runs.claim_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_expires_at_ms=deadline),
        runs.claim_dispatch("owner", project_id, run["id"], 0, worker_id="worker-b", lease_expires_at_ms=deadline),
        return_exceptions=True,
    )
    winners = [result for result in results if isinstance(result, dict)]
    failures = [result for result in results if isinstance(result, Conflict)]
    assert len(winners) == 1
    assert len(failures) == 1
    assert winners[0]["lease_epoch"] == 1


@pytest.mark.asyncio
async def test_duplicate_ack_with_different_request_metadata_conflicts(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    lease = await runs.claim_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_expires_at_ms=int(time.time() * 1000) + 60_000)
    first = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_epoch=lease["lease_epoch"], request_bytes=10, request_hash="a" * 64)
    assert first["response_artifact_id"]
    with pytest.raises(Conflict):
        await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, worker_id="worker-a", lease_epoch=lease["lease_epoch"], request_bytes=11, request_hash="b" * 64)


@pytest.mark.asyncio
async def test_eval0028_migrates_existing_dispatch_artifact_rows(prepared):
    repo, engine, project_id, source_plan, _ = prepared
    _, _, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    ticket = await runs.acknowledge_dispatch("owner", project_id, run["id"], 0, send_started_ns=100)

    # Simulate an eval_0027 database: the response artifact and dispatched row
    # exist, but the eval_0029-only audit actions do not.
    async with repo.sf.begin() as session:
        await session.execute(
            t.performance_run_audit.delete().where(
                t.performance_run_audit.c.run_id == run["id"],
                t.performance_run_audit.c.action.in_(["dispatch_claimed", "dispatch_started"]),
            )
        )
    await engine.dispose()
    config = Config()
    config.set_main_option("script_location", str(Path(schema.__file__).parent / "migrations"))
    config.attributes.update(engine_url=engine.url, postgres_schema="")
    await asyncio.to_thread(command.downgrade, config, "eval_0027")
    await schema.upgrade_evaluation_schema(engine)

    async with engine.connect() as connection:
        row = (await connection.execute(select(t.performance_dispatches.c.lease_epoch, t.performance_dispatches.c.dispatch_id).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 0))).one()
        artifact = (await connection.execute(select(t.performance_response_artifacts.c.id, t.performance_response_artifacts.c.dispatch_id).where(t.performance_response_artifacts.c.id == ticket["response_artifact_id"]))).one()
    assert row.lease_epoch == 0
    assert artifact.dispatch_id == row.dispatch_id


@pytest.mark.asyncio
async def test_admit_run_is_durable_idempotent_and_does_not_start_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    admitted = await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    assert admitted["status"] == "running"
    dispatches = await runs.list_dispatches("owner", project_id, run["id"])
    assert all(row["state"] == "pending" and row["send_started_ns"] is None for row in dispatches)
    actions = [event["action"] for event in await runs.run_audit("owner", project_id, run["id"])]
    assert actions[-1] == "run_admitted"

    repeated = await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    assert repeated == admitted
    actions = [event["action"] for event in await runs.run_audit("owner", project_id, run["id"])]
    assert actions.count("run_admitted") == 1

    with pytest.raises(Conflict):
        await runs.admit_run("owner", project_id, run["id"], confirmed=False)
    with pytest.raises(NotFound):
        await runs.admit_run("another-owner", project_id, run["id"], confirmed=True)


@pytest.mark.asyncio
async def test_ack_rejects_expired_lease_without_reserving_artifact(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    lease = await runs.claim_dispatch(
        "owner",
        project_id,
        run["id"],
        0,
        worker_id="worker-expiring",
        lease_expires_at_ms=int(time.time() * 1000) + 5,
    )
    await asyncio.sleep(0.02)

    with pytest.raises(Conflict):
        await runs.acknowledge_dispatch(
            "owner",
            project_id,
            run["id"],
            0,
            worker_id="worker-expiring",
            lease_epoch=lease["lease_epoch"],
            request_bytes=1,
            request_hash=hashlib.sha256(b"x").hexdigest(),
        )

    async with repo.sf() as session:
        dispatch = (await session.execute(select(t.performance_dispatches).where(t.performance_dispatches.c.run_id == run["id"], t.performance_dispatches.c.ordinal == 0))).mappings().one()
        artifact = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.run_id == run["id"], t.performance_response_artifacts.c.ordinal == 0))).first()
    assert dispatch["state"] == "pending"
    assert artifact is None


@pytest.mark.asyncio
async def test_execution_snapshot_offloads_dataset_hash_from_event_loop(prepared, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    loop = asyncio.get_running_loop()
    release_hash = threading.Event()
    heartbeat_times = []
    release_times = []
    release_timer = threading.Timer(0.2, lambda: (release_times.append(time.monotonic()), release_hash.set()))
    original_dataset_hash = performance_run_repository_module.dataset_hash

    def heartbeat():
        heartbeat_times.append(time.monotonic())

    def schedule_heartbeat():
        loop.call_later(0.02, heartbeat)

    def blocked_dataset_hash(*args, **kwargs):
        loop.call_soon_threadsafe(schedule_heartbeat)
        release_hash.wait(timeout=2)
        return original_dataset_hash(*args, **kwargs)

    monkeypatch.setattr(performance_run_repository_module, "dataset_hash", blocked_dataset_hash)
    release_timer.start()
    try:
        snapshot = await runs.get_execution_snapshot("owner", project_id, run["id"])
    finally:
        release_hash.set()
        release_timer.cancel()

    assert len(snapshot["requests"]) == len(scenario["definition"]["case_order"])
    assert heartbeat_times and release_times and heartbeat_times[0] < release_times[0]


@pytest.mark.asyncio
async def test_execution_snapshot_does_not_join_expected_answers_into_sample_input_query(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    statements = []
    connection_engine = repo.sf.kw["bind"].sync_engine

    def listener(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(connection_engine, "before_cursor_execute", listener)
    try:
        await runs.get_execution_snapshot("owner", project_id, run["id"])
    finally:
        event.remove(connection_engine, "before_cursor_execute", listener)

    sample_selects = [statement.lower() for statement in statements if "samples" in statement.lower()]
    assert sample_selects
    assert all("evaluation_qa_references.expected" not in statement for statement in sample_selects)


@pytest.mark.asyncio
async def test_execution_snapshot_rejects_sample_content_drift_without_metadata_drift(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    dataset_id = scenario["definition"]["dataset_id"]
    async with repo.sf.begin() as session:
        await session.execute(update(t.samples).where(t.samples.c.dataset_id == dataset_id, t.samples.c.sample_id == "a").values(input="TAMPERED_INPUT"))

    with pytest.raises(Conflict):
        await runs.get_execution_snapshot("owner", project_id, run["id"])
    assert all(row["state"] == "pending" for row in await runs.list_dispatches("owner", project_id, run["id"]))


@pytest.mark.asyncio
async def test_execution_snapshot_rejects_dataset_metadata_drift_before_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    dataset_id = scenario["definition"]["dataset_id"]
    async with repo.sf.begin() as session:
        await session.execute(update(t.datasets).where(t.datasets.c.id == dataset_id).values(content_hash="0" * 64))

    with pytest.raises(Conflict):
        await runs.get_execution_snapshot("owner", project_id, run["id"])
    assert all(row["state"] == "pending" for row in await runs.list_dispatches("owner", project_id, run["id"]))


@pytest.mark.asyncio
async def test_cancel_request_is_persisted_idempotent_and_owner_scoped(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    cancelled = await runs.request_cancel("owner", project_id, run["id"], confirmed=True)
    replay = await runs.request_cancel("owner", project_id, run["id"], confirmed=True)

    assert cancelled["status"] == replay["status"] == "cancel_requested"
    assert await runs.cancellation_requested("owner", project_id, run["id"])
    with pytest.raises(Conflict):
        await runs.claim_dispatch(
            "owner",
            project_id,
            run["id"],
            0,
            worker_id="synthetic-worker",
            lease_expires_at_ms=int(time.time() * 1000) + 60_000,
        )
    async with repo.sf() as session:
        events = (
            (
                await session.execute(
                    select(t.performance_run_audit).where(
                        t.performance_run_audit.c.run_id == run["id"],
                        t.performance_run_audit.c.action == "run_cancel_requested",
                    )
                )
            )
            .mappings()
            .all()
        )
    assert len(events) == 1
    with pytest.raises(NotFound):
        await runs.request_cancel("another-owner", project_id, run["id"], confirmed=True)
    with pytest.raises(Conflict):
        await runs.request_cancel("owner", project_id, run["id"], confirmed=False)
