"""Authenticated synthetic-only performance scenario API checks."""

import pytest
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api

from app.gateway.routers.evaluation_performance import router

PROFILE = {
    "concurrency": 1,
    "measured_request_count": 2,
    "warmup_request_count": 1,
    "duration_limit_seconds": None,
    "request_timeout_ms": 1000,
    "max_in_flight": 1,
    "wall_time_limit_seconds": 30,
    "drain_limit_seconds": 5,
    "max_request_bytes": 10000,
    "max_response_bytes": 10000,
    "max_total_bytes": 100000,
}


@pytest.mark.asyncio
async def test_scenario_api_requires_confirmation_and_only_freezes_definition(api, monkeypatch):
    client, app, base, _ = api
    plan_path, payload = await setup_plan(api, monkeypatch)
    app.include_router(router)
    payload["limits"]["mode"] = "performance"
    payload["limits"]["request_count"] = 2
    plan = await client.post(plan_path, json=payload)
    assert plan.status_code == 200
    scenarios_path = plan_path.removesuffix("/plans") + "/performance-scenarios"
    body = {"plan_id": plan.json()["id"], "profile": PROFILE, "confirmed": False}
    invalid = await client.post(scenarios_path, json=body)
    assert invalid.status_code == 422, (scenarios_path, invalid.text)
    body["confirmed"] = True
    response = await client.post(scenarios_path, json=body)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert response.json()["definition"]["scope"] == "frozen_definition_only"
    assert "SYNTHETIC" not in response.text and "expected" not in response.text
    assert (await client.get(scenarios_path)).json()["scenarios"] == [response.json()]
    assert (await client.get(base + "/performance-scenarios/" + response.json()["id"])).json() == response.json()
    app.state.internal = True
    assert (await client.post(scenarios_path, json=body)).status_code == 403
