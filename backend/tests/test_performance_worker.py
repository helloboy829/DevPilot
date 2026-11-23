"""Synthetic-only performance worker acceptance tests."""

import asyncio
import socket

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_dispatch_journal import prepared as prepared
from test_performance_run_repository import make_scenario

from app.evaluation import tables as t
from app.evaluation.performance_run_repository import PerformanceRunRepository
from app.evaluation.performance_worker import PerformanceWorker, SyntheticPerformanceTransport
from app.evaluation.qa_artifact_store import ResponseArtifactStore
from app.evaluation.repository import Conflict


@pytest.mark.asyncio
async def test_admitted_run_records_each_frozen_ordinal_with_synthetic_evidence(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))

    def deny_network(*_args, **_kwargs):
        raise AssertionError("synthetic performance worker attempted network access")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())
    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "completed"
    assert result["execution_mode"] == "synthetic_only"
    assert result["metrics"] is None
    assert result["state_counts"] == {
        "pending": 0,
        "dispatched": 0,
        "succeeded": 6,
        "failed": 0,
        "timeout": 0,
        "unknown": 0,
        "not_dispatched": 0,
    }
    async with repo.sf() as session:
        rows = (
            (
                await session.execute(
                    select(
                        t.performance_dispatches,
                        t.performance_response_artifacts.c.status.label("artifact_status"),
                        t.performance_response_artifacts.c.dispatch_id.label("artifact_dispatch_id"),
                    )
                    .join(
                        t.performance_response_artifacts,
                        (t.performance_response_artifacts.c.run_id == t.performance_dispatches.c.run_id) & (t.performance_response_artifacts.c.ordinal == t.performance_dispatches.c.ordinal),
                    )
                    .where(t.performance_dispatches.c.run_id == run["id"])
                    .order_by(t.performance_dispatches.c.ordinal)
                )
            )
            .mappings()
            .all()
        )
    assert [row["ordinal"] for row in rows] == list(range(6))
    assert [row["phase"] for row in rows] == ["warmup", "measurement", "measurement", "measurement", "measurement", "measurement"]
    assert [row["case_id"] for row in rows] == [entry["case_id"] for entry in scenario["definition"]["manifest"]]
    assert [row["state"] for row in rows] == ["succeeded"] * 6
    assert [row["artifact_status"] for row in rows] == ["complete"] * 6
    assert len({row["dispatch_id"] for row in rows}) == 6
    assert [row["artifact_dispatch_id"] for row in rows] == [row["dispatch_id"] for row in rows]


@pytest.mark.asyncio
async def test_worker_reentry_after_mode_mark_before_dispatch_is_safe(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    await runs.mark_synthetic_execution("owner", project_id, run["id"])

    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "completed"
    assert result["execution_mode"] == "synthetic_only"
    assert result["state_counts"]["succeeded"] == 6


@pytest.mark.asyncio
async def test_worker_refuses_unadmitted_run_without_claiming_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)

    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert all(row["state"] == "pending" for row in await runs.list_dispatches("owner", project_id, run["id"]))


def test_worker_rejects_non_synthetic_transport_before_any_run_access(prepared):
    class NetworkLikeTransport:
        async def request(self, _request):
            raise AssertionError("must never execute")

    repo = prepared[0]
    with pytest.raises(ValueError, match="synthetic"):
        PerformanceWorker(PerformanceRunRepository(repo.sf), transport=NetworkLikeTransport())


@pytest.mark.asyncio
async def test_failure_after_start_is_unknown_and_never_resends(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport(fail_at_ordinal=2))

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["state_counts"]["succeeded"] == 2
    assert result["state_counts"]["unknown"] == 1
    assert result["state_counts"]["not_dispatched"] == 3
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in rows] == ["succeeded", "succeeded", "unknown", "not_dispatched", "not_dispatched", "not_dispatched"]


@pytest.mark.asyncio
async def test_cancellation_after_start_persists_unknown_without_retry(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport(delay_ms=250))
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))

    for _ in range(100):
        rows = await runs.list_dispatches("owner", project_id, run["id"])
        if rows[0]["state"] == "dispatched":
            task.cancel()
            break
        await asyncio.sleep(0.01)
    with pytest.raises(asyncio.CancelledError):
        await task

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    assert result["state_counts"]["unknown"] == 1
    assert result["state_counts"]["not_dispatched"] == 5


@pytest.mark.asyncio
async def test_duration_limit_stops_measurement_and_accounts_remaining_ordinals(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"duration_limit_seconds": 1})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport(delay_ms=400))

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "duration_limit"
    assert result["state_counts"]["succeeded"] >= 2
    assert result["state_counts"]["unknown"] == 1
    assert result["state_counts"]["not_dispatched"] + result["state_counts"]["succeeded"] + 1 == 6
    assert all(row["state"] not in {"pending", "dispatched"} for row in await runs.list_dispatches("owner", project_id, run["id"]))


@pytest.mark.asyncio
async def test_request_byte_budget_interrupts_before_start_and_accounts_population(prepared):
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"max_request_bytes": 1, "max_total_bytes": 10_001})
    runs = PerformanceRunRepository(repo.sf)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "request_byte_budget"
    assert result["state_counts"]["not_dispatched"] == 6
    assert all(row["request_hash"] is None for row in await runs.list_dispatches("owner", project_id, run["id"]))


@pytest.mark.asyncio
async def test_response_byte_budget_records_failed_evidence_then_stops(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"max_response_bytes": 1, "max_total_bytes": 10_001})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "response_byte_budget"
    assert result["state_counts"]["failed"] == 1
    assert result["state_counts"]["not_dispatched"] == 5
    async with repo.sf() as session:
        artifact_status = await session.scalar(
            select(t.performance_response_artifacts.c.status).where(
                t.performance_response_artifacts.c.run_id == run["id"],
                t.performance_response_artifacts.c.ordinal == 0,
            )
        )
    assert artifact_status == "policy_skipped"


@pytest.mark.asyncio
async def test_aggregate_byte_budget_stops_before_exceeding_total(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"max_request_bytes": 500, "max_response_bytes": 500, "max_total_bytes": 1_000})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "aggregate_byte_budget"
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert all(row["state"] in {"succeeded", "not_dispatched"} for row in rows)
    assert sum((row["request_bytes"] or 0) + (row["response_bytes"] or 0) for row in rows) <= 1_000


@pytest.mark.asyncio
async def test_evidence_write_failure_interrupts_and_suppresses_synthetic_metrics(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    monkeypatch.setattr(ResponseArtifactStore, "publish", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic evidence write failure")))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "evidence_write_failed"
    assert result["execution_mode"] == "synthetic_only"
    assert result["metrics"] is None
    assert result["state_counts"]["not_dispatched"] == 5
