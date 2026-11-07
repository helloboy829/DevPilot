"""Regression: enqueue reaches execution, cancellation closes queued clients too."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.component_tests import service


@pytest.mark.asyncio
async def test_enqueue_completes_and_calls_scheduler_callback(monkeypatch):
    repo = AsyncMock()
    runner = service.ComponentTestService(component_repo=AsyncMock(), run_repo=repo)
    client, complete = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "perf_run", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "perf_eval", lambda *a, **k: object())
    monkeypatch.setattr(service, "build_component_test_report", lambda *a, **k: {})
    monkeypatch.setattr(service, "build_run_summary", lambda *a, **k: {})
    runner._persist = AsyncMock(return_value="synthetic/raw.json")
    runner.enqueue(run_id="synthetic", user_id="owner", component={"transport": "http_post", "api_url": "https://example.test"}, test_type="perf", params={}, http_client=client, on_complete=complete)
    await asyncio.gather(*runner._tasks)
    assert repo.update.call_args.kwargs["updates"]["status"] == "completed"
    client.aclose.assert_awaited_once()
    complete.assert_awaited_once_with("completed")


@pytest.mark.asyncio
async def test_cancelled_semaphore_waiter_is_terminal_and_closes_client():
    repo, client, complete = AsyncMock(), AsyncMock(), AsyncMock()
    runner = service.ComponentTestService(component_repo=AsyncMock(), run_repo=repo, max_concurrent=0)
    task = asyncio.create_task(runner._execute(run_id="synthetic", user_id="owner", component={}, test_type="perf", params={}, http_client=client, on_complete=complete))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert repo.update.call_args.kwargs["updates"]["status"] == "failed"
    client.aclose.assert_awaited_once()
    complete.assert_awaited_once_with("failed")


@pytest.mark.asyncio
async def test_provider_errors_do_not_echo_secrets(monkeypatch):
    repo, client = AsyncMock(), AsyncMock()
    runner = service.ComponentTestService(component_repo=AsyncMock(), run_repo=repo)
    monkeypatch.setattr(service, "perf_run", AsyncMock(side_effect=RuntimeError("synthetic-credential")))
    await runner._execute(run_id="synthetic", user_id="owner", component={"transport": "http_post", "api_url": "https://example.test"}, test_type="perf", params={}, http_client=client)
    assert "synthetic-credential" not in str(repo.update.call_args_list)
    assert repo.update.call_args.kwargs["updates"]["status"] == "failed"
