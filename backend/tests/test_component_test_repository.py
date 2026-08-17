from __future__ import annotations

from datetime import UTC, datetime

import pytest

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.component_tests import ComponentRepository, ComponentTestRunRepository
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config


def _component(**overrides):
    """Default component kwargs; tests override what they need."""
    defaults = dict(
        component_id="comp-1",
        user_id="user-1",
        name="Test Component",
        component_code="tc-001",
        transport="openai_chat",
        api_url="https://example.test/v1/chat/completions",
        api_token=None,
        response_mode="blocking",
        supports_streaming=False,
        validation_type="reference_text",
        acceptance_criteria={"effect": {"pass_threshold": 0.8}},
    )
    defaults.update(overrides)
    return defaults


@pytest.mark.asyncio
async def test_component_crud_lifecycle(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    assert sf is not None

    repo = ComponentRepository(sf)
    created = await repo.create(**_component())
    assert created["id"] == "comp-1"
    assert created["enabled"] is True
    # datetimes are coerced to ISO strings on read
    assert isinstance(created["created_at"], str)

    got = await repo.get("comp-1", user_id="user-1")
    assert got is not None
    assert got["name"] == "Test Component"

    updated = await repo.update("comp-1", user_id="user-1", updates={"name": "Renamed", "enabled": False})
    assert updated is not None
    assert updated["name"] == "Renamed"
    assert updated["enabled"] is False

    assert await repo.delete("comp-1", user_id="user-1") is True
    assert await repo.get("comp-1", user_id="user-1") is None

    await close_engine()


@pytest.mark.asyncio
async def test_component_list_scoped_to_user(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    repo = ComponentRepository(sf)

    await repo.create(**_component(component_id="comp-a", user_id="user-1"))
    await repo.create(**_component(component_id="comp-b", user_id="user-2"))

    assert [c["id"] for c in await repo.list_by_user("user-1")] == ["comp-a"]
    assert [c["id"] for c in await repo.list_by_user("user-2")] == ["comp-b"]

    await close_engine()


@pytest.mark.asyncio
async def test_component_ownership_isolation(tmp_path):
    """A different user must not be able to read, mutate, or delete another user's component."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    repo = ComponentRepository(sf)

    await repo.create(**_component(component_id="comp-1", user_id="user-1"))

    assert await repo.get("comp-1", user_id="user-2") is None
    assert await repo.update("comp-1", user_id="user-2", updates={"name": "hijacked"}) is None
    assert await repo.delete("comp-1", user_id="user-2") is False

    # owner still sees the untouched component
    got = await repo.get("comp-1", user_id="user-1")
    assert got is not None
    assert got["name"] == "Test Component"

    await close_engine()


@pytest.mark.asyncio
async def test_run_create_list_and_update(tmp_path):
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    repo = ComponentTestRunRepository(sf)

    row = await repo.create(
        run_id="run-1",
        user_id="user-1",
        component_id="comp-1",
        test_type="effect",
        params={"samples": []},
    )
    assert row["id"] == "run-1"
    assert row["status"] == "queued"
    assert row["result"] == {}

    updated = await repo.update(
        "run-1",
        user_id="user-1",
        updates={
            "status": "completed",
            "result": {"passed": True, "score": 0.9},
            "completed_at": datetime(2026, 8, 14, 1, 0, tzinfo=UTC),
        },
    )
    assert updated is not None
    assert updated["status"] == "completed"
    assert updated["result"]["passed"] is True
    assert isinstance(updated["completed_at"], str)

    assert [r["id"] for r in await repo.list_by_user("user-1")] == ["run-1"]
    assert [r["id"] for r in await repo.list_by_component("comp-1", user_id="user-1")] == ["run-1"]

    await close_engine()


@pytest.mark.asyncio
async def test_run_ownership_and_component_scoping(tmp_path):
    """Runs are scoped by both user_id and component_id on every read path."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    sf = get_session_factory()
    repo = ComponentTestRunRepository(sf)

    await repo.create(run_id="run-1", user_id="user-1", component_id="comp-1", test_type="effect", params={})
    await repo.create(run_id="run-2", user_id="user-1", component_id="comp-2", test_type="perf", params={})
    await repo.create(run_id="run-3", user_id="user-2", component_id="comp-1", test_type="effect", params={})

    # cross-user reads are denied
    assert await repo.get("run-1", user_id="user-2") is None
    assert await repo.update("run-1", user_id="user-2", updates={"status": "failed"}) is None

    # component filter never leaks another user's run on the same component id
    assert [r["id"] for r in await repo.list_by_component("comp-1", user_id="user-1")] == ["run-1"]
    assert [r["id"] for r in await repo.list_by_component("comp-1", user_id="user-2")] == ["run-3"]

    # user filter never leaks another component's run
    assert sorted(r["id"] for r in await repo.list_by_user("user-1")) == ["run-1", "run-2"]

    await close_engine()
