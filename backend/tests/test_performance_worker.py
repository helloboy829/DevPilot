"""Synthetic-only performance worker acceptance tests."""

import asyncio
import json
import socket

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
async def test_worker_sends_rendered_frozen_case_body(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)

    captured_bodies = []
    original_request = SyntheticPerformanceTransport.request

    async def capture_request(transport, request_body, *, ordinal):
        captured_bodies.append((ordinal, request_body))
        return await original_request(transport, request_body, ordinal=ordinal)

    monkeypatch.setattr(SyntheticPerformanceTransport, "request", capture_request)
    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "completed"
    assert len(captured_bodies) == len(scenario["definition"]["manifest"]) == 6
    manifest = scenario["definition"]["manifest"]
    async with repo.sf() as session:
        frozen_inputs = dict((await session.execute(select(t.samples.c.sample_id, t.samples.c.input).where(t.samples.c.dataset_id == scenario["definition"]["dataset_id"]))).all())
    bodies_by_ordinal = dict(captured_bodies)
    assert len(bodies_by_ordinal) == len(captured_bodies) == len(manifest)
    rendered = [(entry["ordinal"], json.loads(bodies_by_ordinal[entry["ordinal"]])) for entry in manifest]
    assert [body for _, body in rendered] == [{"q": frozen_inputs[entry["case_id"]]} for entry in manifest]
    bodies_by_case = {}
    for entry, (_, body) in zip(manifest, rendered, strict=True):
        bodies_by_case.setdefault(entry["case_id"], set()).add(json.dumps(body, sort_keys=True))
    assert all(len(bodies) == 1 for bodies in bodies_by_case.values())
    assert all("SYNTHETIC_GOLD" not in body.values() for _, body in rendered)
    assert all("SYNTHETIC_SECRET" not in body.values() for _, body in rendered)
    assert all("ordinal" not in body for _, body in rendered)
    import hashlib

    async with repo.sf() as session:
        dispatches = (
            await session.execute(
                select(t.performance_dispatches.c.ordinal, t.performance_dispatches.c.request_bytes, t.performance_dispatches.c.request_hash).where(t.performance_dispatches.c.run_id == run["id"]).order_by(t.performance_dispatches.c.ordinal)
            )
        ).all()
    assert [(row.ordinal, row.request_bytes, row.request_hash) for row in dispatches] == [(ordinal, len(bodies_by_ordinal[ordinal]), hashlib.sha256(bodies_by_ordinal[ordinal]).hexdigest()) for ordinal in range(len(manifest))]


@pytest.mark.parametrize("corrupt_target", ["plan", "scenario"])
@pytest.mark.asyncio
async def test_worker_interrupts_run_when_frozen_definition_is_corrupt(prepared, tmp_path, corrupt_target):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    async with repo.sf.begin() as session:
        if corrupt_target == "plan":
            await session.execute(update(t.plans).where(t.plans.c.id == scenario["definition"]["plan_id"]).values(definition={"corrupt": True}))
        else:
            await session.execute(update(t.performance_scenarios).where(t.performance_scenarios.c.id == scenario["id"]).values(definition={"corrupt": True}))

    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["state_counts"]["not_dispatched"] == result["population_count"]
    assert all(row["send_started_ns"] is None for row in await runs.list_dispatches("owner", project_id, run["id"]))
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert audit[-1]["action"] == "run_interrupted"
    assert audit[-1]["details"]["reason"] == "preflight_invalid"


@pytest.mark.asyncio
async def test_worker_interrupts_run_when_frozen_sample_content_drifted(prepared, tmp_path):
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    dataset_id = scenario["definition"]["dataset_id"]
    async with repo.sf.begin() as session:
        await session.execute(update(t.samples).where(t.samples.c.dataset_id == dataset_id, t.samples.c.sample_id == "a").values(input="TAMPERED_INPUT"))

    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["state_counts"]["not_dispatched"] == result["population_count"]
    assert all(row["send_started_ns"] is None for row in await runs.list_dispatches("owner", project_id, run["id"]))
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert audit[-1]["action"] == "run_interrupted"
    assert audit[-1]["details"]["reason"] == "preflight_invalid"


@pytest.mark.asyncio
async def test_worker_reentry_after_mode_mark_before_dispatch_is_safe(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
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
        PerformanceWorker(PerformanceRunRepository(repo.sf, request_protection=repo.protection), transport=NetworkLikeTransport())


@pytest.mark.asyncio
async def test_failure_after_start_is_unknown_and_never_resends(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
async def test_cancellation_after_start_drains_completed_request_without_retry(prepared):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
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
    assert result["state_counts"]["succeeded"] == 1
    assert result["state_counts"]["unknown"] == 0
    assert result["state_counts"]["not_dispatched"] == 5
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")


@pytest.mark.asyncio
async def test_cancellation_drain_collects_peer_completed_during_evidence_write(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    original_request = transport.request
    both_started = asyncio.Event()
    first_observation_started = asyncio.Event()
    started = set()

    async def request(body, *, ordinal):
        started.add(ordinal)
        if {1, 2}.issubset(started):
            both_started.set()
        if ordinal == 2:
            await first_observation_started.wait()
        return await original_request(body, ordinal=ordinal)

    monkeypatch.setattr(transport, "request", request)
    worker = PerformanceWorker(runs, transport=transport)
    original_observe = worker._observe

    async def observe(owner, project, dispatch, finished, response, max_bytes):
        if dispatch.ticket["ordinal"] == 1:
            first_observation_started.set()
            await asyncio.sleep(0.05)
        return await original_observe(owner, project, dispatch, finished, response, max_bytes)

    monkeypatch.setattr(worker, "_observe", observe)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(both_started.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert [row["state"] for row in rows] == ["succeeded", "succeeded", "succeeded", "not_dispatched", "not_dispatched", "not_dispatched"]


@pytest.mark.asyncio
async def test_cancellation_during_observation_waits_for_evidence_before_interrupting(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    original_request = transport.request
    first_observation = asyncio.Event()
    release_observation = asyncio.Event()
    both_started = asyncio.Event()
    started = set()

    async def request(body, *, ordinal):
        started.add(ordinal)
        if {1, 2}.issubset(started):
            both_started.set()
        return await original_request(body, ordinal=ordinal)

    monkeypatch.setattr(transport, "request", request)
    worker = PerformanceWorker(runs, transport=transport)
    original_observe = worker._observe

    async def observe(owner, project, dispatch, finished, response, max_bytes):
        if dispatch.ticket["ordinal"] == 1:
            first_observation.set()
            await release_observation.wait()
        return await original_observe(owner, project, dispatch, finished, response, max_bytes)

    monkeypatch.setattr(worker, "_observe", observe)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(first_observation.wait(), timeout=3)
    task.cancel()
    asyncio.get_running_loop().call_later(0.05, release_observation.set)
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert rows[1]["state"] == "succeeded"
    assert (await runs.reconcile_response_artifact("owner", project_id, run["id"], 1))["status"] == "complete"
    assert rows[2]["state"] in {"succeeded", "unknown"}
    assert all(row["state"] == "not_dispatched" for row in rows[3:])
    assert (await runs.get_run("owner", project_id, run["id"]))["status"] == "interrupted"


@pytest.mark.asyncio
async def test_cancellation_bounds_stalled_evidence_write_by_drain_deadline(prepared, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"drain_limit_seconds": 1})
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport(delay_ms=50))
    entered = asyncio.Event()
    never_release = asyncio.Event()

    async def stalled_observe(*_args):
        entered.set()
        await never_release.wait()

    monkeypatch.setattr(worker, "_observe", stalled_observe)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.5)

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    assert result["state_counts"]["unknown"] == 1
    audit = await runs.run_audit("owner", project_id, run["id"])
    interruption = next(row for row in audit if row["action"] == "run_interrupted")
    assert interruption["details"]["reason"] == "evidence_write_failed"


@pytest.mark.asyncio
async def test_cancellation_bounds_drain_time_evidence_write_by_drain_deadline(prepared, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"drain_limit_seconds": 1})
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport(delay_ms=50))
    never_release = asyncio.Event()

    async def stalled_observe(*_args):
        await never_release.wait()

    monkeypatch.setattr(worker, "_observe", stalled_observe)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    for _ in range(100):
        rows = await runs.list_dispatches("owner", project_id, run["id"])
        if rows[0]["state"] == "dispatched":
            task.cancel()
            break
        await asyncio.sleep(0.01)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.5)

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    assert result["state_counts"]["unknown"] == 1
    audit = await runs.run_audit("owner", project_id, run["id"])
    interruption = next(row for row in audit if row["action"] == "run_interrupted")
    assert interruption["details"]["reason"] == "evidence_write_failed"


@pytest.mark.asyncio
async def test_cancellation_records_evidence_write_failure_as_run_stop_reason(prepared, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared)
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(delay_ms=50)
    worker = PerformanceWorker(runs, transport=transport)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fail_observe(*_args):
        entered.set()
        await release.wait()
        raise OSError("synthetic evidence write failure")

    monkeypatch.setattr(worker, "_observe", fail_observe)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(entered.wait(), timeout=3)
    task.cancel()
    asyncio.get_running_loop().call_later(0.05, release.set)
    with pytest.raises(asyncio.CancelledError):
        await task

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    assert result["state_counts"]["unknown"] == 1
    audit = await runs.run_audit("owner", project_id, run["id"])
    interruption = next(row for row in audit if row["action"] == "run_interrupted")
    assert interruption["details"]["reason"] == "evidence_write_failed"


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_interrupt_durable_drain_cleanup(prepared):
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"drain_limit_seconds": 1})
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    never_finishes = asyncio.Event()

    async def hang_request(body, *, ordinal):
        await never_finishes.wait()
        return await transport.request(body, ordinal=ordinal)

    transport.request = hang_request
    worker = PerformanceWorker(runs, transport=transport)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    for _ in range(100):
        rows = await runs.list_dispatches("owner", project_id, run["id"])
        if rows[0]["state"] == "dispatched":
            task.cancel()
            asyncio.get_running_loop().call_later(0.05, task.cancel)
            break
        await asyncio.sleep(0.01)
    with pytest.raises(asyncio.CancelledError):
        await task

    result = await runs.get_run("owner", project_id, run["id"])
    assert result["status"] == "interrupted"
    assert result["state_counts"]["unknown"] == 1


@pytest.mark.asyncio
async def test_cancellation_marks_only_unresolved_dispatch_unknown_after_drain_deadline(prepared):
    repo, project_id, scenario = await make_scenario(
        prepared,
        profile_overrides={"concurrency": 1, "max_in_flight": 1, "drain_limit_seconds": 1},
    )
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    never_finishes = asyncio.Event()

    async def hang_request(body, *, ordinal):
        await never_finishes.wait()
        return await transport.request(body, ordinal=ordinal)

    transport.request = hang_request
    worker = PerformanceWorker(runs, transport=transport)
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
    with pytest.raises(Conflict):
        await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")


@pytest.mark.asyncio
async def test_cancellation_drains_concurrent_fences_before_marking_run_interrupted(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"concurrency": 2, "max_in_flight": 2})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(delay_ms=250)
    original_request = transport.request
    started = set()
    both_started = asyncio.Event()
    hold_requests = asyncio.Event()

    async def observe_start(body, *, ordinal):
        started.add(ordinal)
        if ordinal in {1, 2}:
            if {1, 2}.issubset(started):
                both_started.set()
            await hold_requests.wait()
        return await original_request(body, ordinal=ordinal)

    monkeypatch.setattr(transport, "request", observe_start)
    worker = PerformanceWorker(runs, transport=transport)
    task = asyncio.create_task(worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker"))
    await asyncio.wait_for(both_started.wait(), timeout=3)
    task.cancel()
    asyncio.get_running_loop().call_later(0.05, hold_requests.set)
    with pytest.raises(asyncio.CancelledError):
        await task

    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert started == {0, 1, 2}
    assert [row["state"] for row in rows] == ["succeeded", "succeeded", "succeeded", "not_dispatched", "not_dispatched", "not_dispatched"]
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
async def test_request_byte_budget_rejects_snapshot_before_dispatch(prepared):
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"max_request_bytes": 1, "max_total_bytes": 10_001})
    runs = PerformanceRunRepository(repo.sf, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    worker = PerformanceWorker(runs, transport=SyntheticPerformanceTransport())

    result = await worker.run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["state_counts"]["not_dispatched"] == result["population_count"]
    assert all(row["request_hash"] is None and row["send_started_ns"] is None for row in await runs.list_dispatches("owner", project_id, run["id"]))


@pytest.mark.asyncio
async def test_response_byte_budget_records_failed_evidence_then_stops(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared, profile_overrides={"max_response_bytes": 1, "max_total_bytes": 10_001})
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(delay_ms=25)
    original_request = transport.request
    active = 0
    maximum = 0
    both_started = asyncio.Event()

    async def measured_request(request_body, *, ordinal):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active >= 2:
            both_started.set()
        try:
            if ordinal in (1, 2):
                # Prove concurrent transport without assuming a DB latency.
                await both_started.wait()
            return await original_request(request_body, ordinal=ordinal)
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
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

    async def fail_second_send(self, body, ordinal, timeout_ms):
        result = await original_send(self, body, ordinal, timeout_ms)
        if ordinal == 1:
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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport(fail_at_ordinal=1)
    original_request = transport.request
    peer_started = asyncio.Event()
    failure_delivered = asyncio.Event()
    seen = []

    async def request(body, *, ordinal):
        seen.append(ordinal)
        if ordinal == 1:
            await peer_started.wait()
            try:
                return await original_request(body, ordinal=ordinal)
            finally:
                failure_delivered.set()
        if ordinal == 2:
            peer_started.set()
            await failure_delivered.wait()
            await asyncio.sleep(0.1)
        return await original_request(body, ordinal=ordinal)

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
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    transport = SyntheticPerformanceTransport()
    original_request = transport.request
    peer_started = asyncio.Event()
    failure_delivered = asyncio.Event()
    seen = []

    async def request(body, *, ordinal):
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
        return await original_request(body, ordinal=ordinal)

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
async def test_worker_observes_durable_cancel_and_drains_current_synthetic_request(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    original = SyntheticPerformanceTransport.request
    requested = False

    async def cancel_during_request(transport, request_body, *, ordinal):
        nonlocal requested
        if not requested:
            requested = True
            await runs.request_cancel("owner", project_id, run["id"], confirmed=True)
        await asyncio.sleep(0.05)
        return await original(transport, request_body, ordinal=ordinal)

    monkeypatch.setattr(SyntheticPerformanceTransport, "request", cancel_during_request)
    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "cancelled"
    assert result["state_counts"]["succeeded"] >= 1
    assert result["state_counts"]["pending"] == 0
    assert result["state_counts"]["not_dispatched"] > 0
    assert all(row["state"] != "pending" for row in await runs.list_dispatches("owner", project_id, run["id"]))
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert [event["action"] for event in audit].count("run_cancel_requested") == 1
    assert audit[-1]["action"] == "run_interrupted"


@pytest.mark.asyncio
async def test_cancel_winning_final_completion_race_finishes_as_interrupted(prepared, tmp_path, monkeypatch):
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda _path: None))
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    original_close = runs.close_measurement_window

    async def request_cancel_before_close(owner, project, run_id, *, window_end_ns):
        await runs.request_cancel(owner, project, run_id, confirmed=True)
        return await original_close(owner, project, run_id, window_end_ns=window_end_ns)

    monkeypatch.setattr(runs, "close_measurement_window", request_cancel_before_close)
    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "cancelled"
    audit = await runs.run_audit("owner", project_id, run["id"])
    assert audit[-1]["action"] == "run_interrupted"
    assert not any(event["action"] == "run_finished" for event in audit)


@pytest.mark.asyncio
async def test_cancel_after_claim_before_ack_is_a_clean_stop_not_a_worker_error(prepared, tmp_path, monkeypatch):
    repo, project_id, scenario = await make_scenario(prepared)
    store = ResponseArtifactStore(tmp_path / "performance-artifacts", Fernet.generate_key())
    runs = PerformanceRunRepository(repo.sf, response_artifact_store=store, request_protection=repo.protection)
    run = await runs.create_run("owner", project_id, scenario["id"], scenario["definition_hash"], confirmed=True)
    await runs.admit_run("owner", project_id, run["id"], confirmed=True)
    original_ack = runs.acknowledge_dispatch
    requested = False

    async def cancel_before_ack(*args, **kwargs):
        nonlocal requested
        if not requested:
            requested = True
            await runs.request_cancel("owner", project_id, run["id"], confirmed=True)
        return await original_ack(*args, **kwargs)

    monkeypatch.setattr(runs, "acknowledge_dispatch", cancel_before_ack)
    result = await PerformanceWorker(runs, transport=SyntheticPerformanceTransport()).run_admitted("owner", project_id, run["id"], worker_id="synthetic-worker")

    assert result["status"] == "interrupted"
    assert result["stop_reason"] == "cancelled"
    rows = await runs.list_dispatches("owner", project_id, run["id"])
    assert all(row["send_started_ns"] is None for row in rows)
    assert rows[0]["state"] == "not_dispatched"
