"""Synthetic-only performance worker acceptance tests."""

import asyncio
import json
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
async def test_cancellation_marks_all_concurrent_fences_unknown_without_resend(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(delay_ms=250)
    original_request = transport.request
    started = set()
    both_started = asyncio.Event()
    hold_requests = asyncio.Event()

    async def observe_start(body):
        ordinal = json.loads(body)["ordinal"]
        started.add(ordinal)
        if ordinal in {1, 2}:
            if {1, 2}.issubset(started):
                both_started.set()
            await hold_requests.wait()
        return await original_request(body)

    monkeypatch.setattr(transport, "request", observe_start)
    worker = PerformanceWorker(runs, transport=transport)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(both_started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert started == {0, 1, 2}
    assert [row["state"] for row in rows] == ["succeeded", "unknown", "unknown", "not_dispatched", "not_dispatched", "not_dispatched"]
    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")
    assert started == {0, 1, 2}


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
    assert result["state_counts"]["unknown"] == 0
    assert result["state_counts"]["not_dispatched"] + result["state_counts"]["succeeded"] == 6
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


@pytest.mark.asyncio
async def test_worker_honors_bounded_concurrency_and_accounts_every_artifact(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(delay_ms=25)
    original_request = transport.request
    active = 0
    maximum = 0
    both_started = asyncio.Event()

    async def measured_request(request_body):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active >= 2:
            both_started.set()
        try:
            if json.loads(request_body)["ordinal"] in (1, 2):
                # Prove concurrent transport without assuming a DB latency.
                await both_started.wait()
            return await original_request(request_body)
        finally:
            active -= 1

    monkeypatch.setattr(transport, "request", measured_request)
    result = await PerformanceWorker(runs, transport=transport).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert both_started.is_set(), f"the worker must actually overlap two synthetic requests: {result}"
    assert maximum == 2
    assert result["status"] == "completed"
    assert result["metrics"] is None
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["ordinal"] for row in rows] == list(range(len(scenario["definition"]["manifest"])))
    assert all(row["state"] == "succeeded" for row in rows)
    async with repo.sf() as session:
        artifacts = (await session.execute(select(t.performance_response_artifacts).where(t.performance_response_artifacts.c.run_id == run["id"]).order_by(t.performance_response_artifacts.c.ordinal))).mappings().all()
    assert len(artifacts) == len(rows)
    assert all(artifact["status"] == "complete" for artifact in artifacts)
    assert [artifact["dispatch_id"] for artifact in artifacts] == [row["dispatch_id"] for row in rows]


@pytest.mark.asyncio
async def test_failure_during_claim_does_not_acknowledge_next_ordinal(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    original_claim = runs.claim_dispatch
    original_acknowledge = runs.acknowledge_dispatch
    original_send = PerformanceWorker._send
    transport_failure_returned = asyncio.Event()
    acknowledged = []

    async def gated_claim(*args, **kwargs):
        ordinal = args[3]
        if ordinal == 2:
            await asyncio.wait_for(transport_failure_returned.wait(), timeout=3)
            # Let the completed _send task become observable to the coordinator.
            await asyncio.sleep(0)
        return await original_claim(*args, **kwargs)

    async def record_acknowledgement(*args, **kwargs):
        acknowledged.append(args[3])
        return await original_acknowledge(*args, **kwargs)

    async def fail_second_send(self, body, timeout_ms):
        result = await original_send(self, body, timeout_ms)
        if json.loads(body)["ordinal"] == 1:
            transport_failure_returned.set()
        return result

    monkeypatch.setattr(runs, "claim_dispatch", gated_claim)
    monkeypatch.setattr(runs, "acknowledge_dispatch", record_acknowledgement)
    monkeypatch.setattr(PerformanceWorker, "_send", fail_second_send)
    transport = SyntheticPerformanceTransport(fail_at_ordinal=1)
    worker = PerformanceWorker(runs, transport=transport)

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "delivery_unknown"
    assert 2 not in acknowledged
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert rows[2]["state"] == "not_dispatched"


@pytest.mark.asyncio
async def test_failure_stops_new_admission_and_drains_fenced_peer(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(fail_at_ordinal=1)
    original_request = transport.request
    peer_started = asyncio.Event()
    failure_delivered = asyncio.Event()
    seen = []

    async def request(body):
        ordinal = json.loads(body)["ordinal"]
        seen.append(ordinal)
        if ordinal == 1:
            await peer_started.wait()
            try:
                return await original_request(body)
            finally:
                failure_delivered.set()
        if ordinal == 2:
            peer_started.set()
            await failure_delivered.wait()
            await asyncio.sleep(0.1)
        return await original_request(body)

    monkeypatch.setattr(transport, "request", request)
    worker = PerformanceWorker(runs, transport=transport)
    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")
    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "delivery_unknown"
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in rows] == ["succeeded", "unknown", "succeeded", "not_dispatched", "not_dispatched", "not_dispatched"]
    assert (await runs.reconcile_response_artifact("owner", project_id, run["id"], 2))["status"] == "complete"
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")
    assert seen == [0, 1, 2]


@pytest.mark.asyncio
async def test_unexpected_transport_error_still_drains_fenced_peer(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    original_request = transport.request
    peer_started = asyncio.Event()
    failure_delivered = asyncio.Event()
    seen = []

    async def request(body):
        ordinal = json.loads(body)["ordinal"]
        seen.append(ordinal)
        if ordinal == 1:
            await peer_started.wait()
            try:
                raise RuntimeError("synthetic transport programming error")
            finally:
                failure_delivered.set()
        if ordinal == 2:
            peer_started.set()
            await failure_delivered.wait()
            await asyncio.sleep(0.1)
        return await original_request(body)

    monkeypatch.setattr(transport, "request", request)
    worker = PerformanceWorker(runs, transport=transport)
    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "delivery_unknown"
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in rows] == ["succeeded", "unknown", "succeeded", "not_dispatched", "not_dispatched", "not_dispatched"]
    assert (await runs.reconcile_response_artifact("owner", project_id, run["id"], 2))["status"] == "complete"
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")
    assert seen == [0, 1, 2]
