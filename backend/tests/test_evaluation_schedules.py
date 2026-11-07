import copy

import pytest

from app.evaluation.schedules import component_fingerprint, freeze_plan, validate_plan


def component():
    return dict(id="comp-synthetic", name="Synthetic", transport="http_post", api_url="https://example.test", api_token="synthetic-secret", enabled=True, response_mode="blocking", acceptance_criteria={})


def test_schedule_freezes_plan_without_credentials_and_detects_changes():
    import json

    value = component()
    plan = freeze_plan(value, "perf", {"payload": {}, "max_requests": 3, "concurrency_levels": [1, 2]})
    assert "synthetic-secret" not in json.dumps(plan)
    assert plan["component_sha256"] == component_fingerprint(value)
    changed = copy.deepcopy(value)
    changed["api_url"] = "https://different.test"
    assert component_fingerprint(changed) != plan["component_sha256"]


@pytest.mark.parametrize(
    "params",
    [
        {"max_requests": 1000000},
        {"max_requests": True},
        {"max_requests": 3, "concurrency_levels": [10000]},
        {"max_requests": 3, "concurrency_levels": [1], "headers": {"Authorization": "secret"}},
        {"max_requests": 3, "concurrency_levels": [1], "judge_model": "anything"},
    ],
)
def test_unsafe_schedule_parameters_rejected(params):
    with pytest.raises(ValueError):
        validate_plan("perf", params)


def test_empty_effect_cannot_be_scheduled():
    with pytest.raises(ValueError):
        freeze_plan(component(), "effect", {"samples": []})


@pytest.mark.asyncio
async def test_dispatch_evaluates_without_chat_or_model_judge(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from app.evaluation import schedules
    from app.gateway import authz, deps
    from deerflow import config

    value = component()
    value["validation_type"] = "reference_text"
    user = SimpleNamespace(needs_setup=False)
    monkeypatch.setattr(deps, "get_local_provider", lambda: SimpleNamespace(get_user=AsyncMock(return_value=user)))
    monkeypatch.setattr(authz, "resolve_route_permissions", AsyncMock(return_value=[authz.Permissions.THREADS_WRITE, authz.Permissions.RUNS_CREATE]))
    monkeypatch.setattr(config, "get_app_config", lambda: object())
    monkeypatch.setattr(schedules, "resolve_destination", AsyncMock(return_value="192.0.2.1"))
    client = AsyncMock()
    monkeypatch.setattr(schedules.httpx, "AsyncClient", Mock(return_value=client))
    app = SimpleNamespace(
        state=SimpleNamespace(
            component_repo=SimpleNamespace(get=AsyncMock(return_value=value)),
            component_test_run_repo=SimpleNamespace(create=AsyncMock()),
            component_test_service=SimpleNamespace(enqueue=Mock()),
            scheduled_task_service=SimpleNamespace(handle_run_completion=AsyncMock()),
        )
    )
    result = await schedules.launch_scheduled_dispatch(
        app=app, assistant_id=schedules.ASSISTANT_ID, owner_user_id="owner", thread_id="thread", prompt=json.dumps(freeze_plan(value, "effect", {"samples": [{"input": {}}]})), metadata={"scheduled_task_id": "task"}
    )
    call = app.state.component_test_service.enqueue.call_args.kwargs
    assert call["component"]["validation_type"] == "manual_review"
    assert call["run_id"] == result["run_id"]
    await call["on_complete"]("failed")
    assert app.state.scheduled_task_service.handle_run_completion.call_args.args[0].status.value == "error"


def test_defaults_are_frozen_and_input_mutation_cannot_change_plan():
    params = {}
    plan = freeze_plan(component(), "perf", params)
    params["concurrency_levels"] = [999]
    assert plan["params"]["concurrency_levels"] == [1, 5]


@pytest.mark.asyncio
@pytest.mark.parametrize("status,allowed", [("paused", True), ("completed", False), ("enabled", False)])
async def test_evaluation_schedule_resume_requires_paused_state(monkeypatch, status, allowed):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.gateway.routers import scheduled_tasks

    repo = SimpleNamespace(get=AsyncMock(return_value={"id": "synthetic", "assistant_id": "devpilot_component_evaluation_v1", "status": status}), update=AsyncMock(return_value={"status": "enabled"}))
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _: repo)
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="owner")))
    if allowed:
        result = await scheduled_tasks.resume_scheduled_task.__wrapped__("synthetic", SimpleNamespace())
        assert result["status"] == "enabled"
    else:
        with pytest.raises(HTTPException) as error:
            await scheduled_tasks.resume_scheduled_task.__wrapped__("synthetic", SimpleNamespace())
        assert error.value.status_code == 409
        repo.update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["pause", "trigger"])
async def test_terminal_evaluation_schedule_cannot_be_rearmed_or_replayed(monkeypatch, action):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.gateway.routers import scheduled_tasks

    repo = SimpleNamespace(get=AsyncMock(return_value={"id": "synthetic", "assistant_id": "devpilot_component_evaluation_v1", "status": "completed"}), update=AsyncMock())
    service = SimpleNamespace(dispatch_task=AsyncMock())
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_repo", lambda _: repo)
    monkeypatch.setattr(scheduled_tasks, "get_scheduled_task_service", lambda _: service)
    monkeypatch.setattr(scheduled_tasks, "get_optional_user_from_request", AsyncMock(return_value=SimpleNamespace(id="owner")))
    route = scheduled_tasks.pause_scheduled_task if action == "pause" else scheduled_tasks.trigger_scheduled_task
    with pytest.raises(HTTPException) as error:
        await route.__wrapped__("synthetic", SimpleNamespace())
    assert error.value.status_code == 409
    repo.update.assert_not_awaited()
    service.dispatch_task.assert_not_awaited()
