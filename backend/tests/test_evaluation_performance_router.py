"""Authenticated synthetic-only performance scenario API checks."""

import asyncio
import socket

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


@pytest.mark.asyncio
async def test_run_api_creates_ledger_only_and_exposes_bounded_dispatch_reads(api, monkeypatch):
    client, app, base, _ = api
    plan_path, payload = await setup_plan(api, monkeypatch)
    app.include_router(router)
    payload["limits"]["mode"] = "performance"
    payload["limits"]["request_count"] = 2
    plan = await client.post(plan_path, json=payload)
    assert plan.status_code == 200

    scenarios_path = plan_path.removesuffix("/plans") + "/performance-scenarios"
    scenario = await client.post(
        scenarios_path,
        json={"plan_id": plan.json()["id"], "profile": PROFILE, "confirmed": True},
    )
    assert scenario.status_code == 200

    runs_path = base + "/performance-runs"
    create_payload = {
        "run_id": "f" * 32,
        "scenario_id": scenario.json()["id"],
        "scenario_hash": scenario.json()["definition_hash"],
        "confirmed": False,
    }
    assert (await client.post(runs_path, json=create_payload)).status_code == 422
    create_payload["confirmed"] = True
    assert (await client.post(runs_path, json={key: value for key, value in create_payload.items() if key != "run_id"})).status_code == 422
    assert (await client.post(runs_path, json={**create_payload, "run_id": "invalid"})).status_code == 422
    stale_hash = await client.post(runs_path, json={**create_payload, "scenario_hash": "0" * 64})
    assert stale_hash.status_code == 409

    def deny_network(*args, **kwargs):
        raise AssertionError("performance run creation must not perform network I/O")

    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", deny_network)
    for method in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, method, deny_network)

    created = await client.post(runs_path, json=create_payload)
    assert created.status_code == 200, created.text
    assert "no-store" in created.headers["cache-control"]
    run = created.json()
    assert run["id"] == create_payload["run_id"]
    assert run["status"] == "created"
    assert run["state_counts"]["pending"] == run["population_count"] == 3
    assert run["metrics"] is None
    assert "SYNTHETIC_GOLD" not in created.text and "SYNTHETIC_TOKEN" not in created.text

    run_path = runs_path + "/" + run["id"]
    summary = await client.get(run_path)
    assert summary.status_code == 200
    assert summary.json() == run
    dispatches = await client.get(run_path + "/dispatches?offset=0&limit=2")
    assert dispatches.status_code == 200
    assert len(dispatches.json()["dispatches"]) == 2
    assert all(row["state"] == "pending" and row["send_started_ns"] is None for row in dispatches.json()["dispatches"])
    assert (await client.get(run_path + "/dispatches?offset=11000&limit=2")).status_code == 422
    assert (await client.get(run_path + "/dispatches?offset=0&limit=201")).status_code == 422

    app.state.actor = 2
    assert (await client.get(run_path)).status_code == 404
