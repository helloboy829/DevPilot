"""Synthetic lifecycle; no operator secrets, real targets or production DB."""

import asyncio
from types import SimpleNamespace

import pytest
from test_dispatch_journal import prepared as prepared
from test_qa_execution import admit, repository
from test_qa_execution import policy as policy

from app.evaluation.execution_lifecycle import qa_execution_runtime


@pytest.mark.asyncio
async def test_default_disabled_never_starts_worker(prepared, monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    starts = []

    class Worker:
        def __init__(self, *args):
            starts.append(True)

    monkeypatch.setattr("app.evaluation.execution_lifecycle.QAExecutionWorker", Worker)
    async with qa_execution_runtime(app, prepared[0].sf, SimpleNamespace(), lambda: SimpleNamespace()):
        assert app.state.evaluation_execution_repo.policy.enabled is False
        assert not starts
    assert app.state.evaluation_execution_repo is None


@pytest.mark.asyncio
async def test_enabled_worker_drains_before_lifecycle_returns(prepared, monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    entered = asyncio.Event()
    events = []

    class Worker:
        def __init__(self, repository, getter):
            self.repository = repository

        async def serve(self):
            entered.set()
            try:
                await asyncio.sleep(30)
            finally:
                # DB session is still open while the worker drains.
                assert await self.repository.list_projects("owner")
                events.append("drained")

    monkeypatch.setattr("app.evaluation.execution_lifecycle.QAExecutionWorker", Worker)
    async with qa_execution_runtime(app, prepared[0].sf, SimpleNamespace(evaluation_execution={"enabled": True}), lambda: SimpleNamespace()):
        await asyncio.wait_for(entered.wait(), 5)
        assert app.state.evaluation_execution_repo.policy.enabled
    events.append("database teardown allowed")
    assert events == ["drained", "database teardown allowed"]
    assert app.state.evaluation_execution_repo is None


@pytest.mark.asyncio
async def test_invalid_operator_policy_fails_before_startup(prepared):
    from pydantic import ValidationError

    app = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(ValidationError):
        async with qa_execution_runtime(app, prepared[0].sf, SimpleNamespace(evaluation_execution={"enabled": True, "max_active_runs": 0}), lambda: SimpleNamespace()):
            pytest.fail("Invalid policy must not start a worker")


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["normal", "cancelled", "error"])
@pytest.mark.parametrize("repeated_cancels", [1, 3])
async def test_repeated_shutdown_cancellation_does_not_interrupt_worker_drain(prepared, monkeypatch, exit_kind, repeated_cancels):
    app = SimpleNamespace(state=SimpleNamespace())
    entered, leave, draining, release = (asyncio.Event() for _ in range(4))
    workers, events = [], []

    class Worker:
        def __init__(self, repository, getter):
            self.repository = repository

        async def serve(self):
            workers.append(asyncio.current_task())
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                draining.set()
                await release.wait()
                # A real migrated DB remains usable until the original Worker drains.
                assert await self.repository.list_projects("owner")
                events.append("worker drained")

    monkeypatch.setattr("app.evaluation.execution_lifecycle.QAExecutionWorker", Worker)

    async def lifetime():
        try:
            async with qa_execution_runtime(app, prepared[0].sf, SimpleNamespace(evaluation_execution={"enabled": True}), lambda: SimpleNamespace()):
                await leave.wait()
                if exit_kind == "error":
                    raise RuntimeError("synthetic lifecycle body failure")
        finally:
            events.append("database teardown allowed")

    task = asyncio.create_task(lifetime())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        if exit_kind == "cancelled":
            task.cancel()
        else:
            leave.set()
        await asyncio.wait_for(draining.wait(), 5)
        for _ in range(repeated_cancels):
            task.cancel()
            await asyncio.sleep(0)
            assert workers[0].cancelling() == 1
            assert not workers[0].done()
            assert not task.done()
            assert app.state.evaluation_execution_repo is not None
            assert not events
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert events == ["worker drained", "database teardown allowed"]
    assert app.state.evaluation_execution_repo is None
    assert workers[0].cancelled()


@pytest.mark.asyncio
async def test_body_failure_waits_for_worker_cleanup_and_keeps_original_exception(prepared, monkeypatch):
    app = SimpleNamespace(state=SimpleNamespace())
    entered = asyncio.Event()
    events = []

    class Worker:
        def __init__(self, repository, getter):
            self.repository = repository

        async def serve(self):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                assert await self.repository.list_projects("owner")
                events.append("worker drained")
                raise ValueError("synthetic worker cleanup failure")

    monkeypatch.setattr("app.evaluation.execution_lifecycle.QAExecutionWorker", Worker)
    with pytest.raises(RuntimeError, match="synthetic body failure"):
        async with qa_execution_runtime(app, prepared[0].sf, SimpleNamespace(evaluation_execution={"enabled": True}), lambda: SimpleNamespace()):
            await asyncio.wait_for(entered.wait(), 5)
            raise RuntimeError("synthetic body failure")
    events.append("database teardown allowed")
    assert events == ["worker drained", "database teardown allowed"]
    assert app.state.evaluation_execution_repo is None


@pytest.mark.asyncio
async def test_real_worker_repeated_shutdown_keeps_quota_until_network_and_database_drain(prepared, policy, monkeypatch):
    repo = repository(prepared, policy)
    await repo.initialize()
    row = await admit(repo, prepared)
    app = SimpleNamespace(state=SimpleNamespace())
    entered, leave, draining, release = (asyncio.Event() for _ in range(4))
    sends, drained = [], []

    async def collect(*args):
        sends.append(asyncio.current_task())
        if len(sends) == 2:
            entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            draining.set()
            await release.wait()
            assert (await repo.get_execution("owner", prepared[2], row["id"]))["reservation_held"]
            drained.append(asyncio.current_task())

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    monkeypatch.setattr("app.evaluation.execution_lifecycle.ExecutionRepository", lambda *args, **kwargs: repo)

    async def lifetime():
        async with qa_execution_runtime(app, repo.sf, SimpleNamespace(evaluation_execution=policy.model_dump()), repo.config_getter):
            await leave.wait()

    task = asyncio.create_task(lifetime())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        leave.set()
        await asyncio.wait_for(draining.wait(), 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert app.state.evaluation_execution_repo is repo
            assert (await repo.get_execution("owner", prepared[2], row["id"]))["reservation_held"]
            assert not drained
    finally:
        release.set()
        result = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert len(sends) == len(drained) == 2
    assert app.state.evaluation_execution_repo is None
    state = await repo.get_execution("owner", prepared[2], row["id"])
    assert state["state"] == "interrupted" and not state["reservation_held"]
    assert await repo.claim() is None
