"""Synthetic lifecycle; no operator secrets, real targets or production DB."""

import asyncio
from types import SimpleNamespace

import pytest
from test_dispatch_journal import prepared as prepared

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
