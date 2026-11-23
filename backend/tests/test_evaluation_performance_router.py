"""Authenticated synthetic-only performance scenario API checks."""

import asyncio
import hashlib
import socket
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api

from app.evaluation.performance_run_repository import PerformanceRunRepository
from app.evaluation.qa_artifact_store import ResponseArtifactStore
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
    run_page = await client.get(runs_path + "?limit=1")
    assert run_page.status_code == 200
    assert "no-store" in run_page.headers["cache-control"]
    assert run_page.json()["total"] == 1
    assert [item["id"] for item in run_page.json()["items"]] == [run["id"]]
    assert run_page.json()["next_cursor"] is None
    assert (await client.get(runs_path + "?limit=201")).status_code == 422
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
    assert (await client.get(runs_path)).status_code == 404
    app.state.actor = 1
    app.state.internal = True
    internal_summary = await client.get(run_path)
    internal_dispatches = await client.get(run_path + "/dispatches")
    assert (internal_summary.status_code, internal_dispatches.status_code) == (403, 403)


@pytest.mark.asyncio
async def test_response_evidence_api_scopes_and_consumes_a_grant_once(api, monkeypatch):
    client, app, base, _ = api
    plan_path, payload = await setup_plan(api, monkeypatch)
    app.include_router(router)
    payload["limits"].update(mode="performance", request_count=2)
    plan = await client.post(plan_path, json=payload)
    assert plan.status_code == 200
    scenario = await client.post(
        plan_path.removesuffix("/plans") + "/performance-scenarios",
        json={"plan_id": plan.json()["id"], "profile": PROFILE, "confirmed": True},
    )
    assert scenario.status_code == 200
    run_id = "a" * 32
    run_path = f"{base}/performance-runs/{run_id}"
    created = await client.post(base + "/performance-runs", json={"run_id": run_id, "scenario_id": scenario.json()["id"], "scenario_hash": scenario.json()["definition_hash"], "confirmed": True})
    assert created.status_code == 200

    store = ResponseArtifactStore(app.state.test_artifact_root, Fernet.generate_key())
    monkeypatch.setattr(ResponseArtifactStore, "from_environment", classmethod(lambda cls: store))
    monkeypatch.setattr(ResponseArtifactStore, "_fsync_directory", staticmethod(lambda path: None))
    runs = PerformanceRunRepository(app.state.evaluation_repo.sf)
    actor = str(UUID(int=1))
    project_id = base.rsplit("/", 1)[1]
    ticket = await runs.acknowledge_dispatch(actor, project_id, run_id, 0, send_started_ns=100)
    body = b"SYNTHETIC performance response"
    digest = hashlib.sha256(body).hexdigest()
    await runs.record_observation(actor, project_id, ticket, state="succeeded", finished_ns=200, elapsed_ms=0.1, response_status=200, response_bytes=len(body), response_hash=digest, response_body=body)

    grant_path = f"{run_path}/dispatches/0/evidence-access"
    access_payload = {"kind": "response", "evidence_hash": digest, "confirmed": True}
    assert (await client.post(grant_path, json={**access_payload, "confirmed": False})).status_code == 422
    assert (await client.post(grant_path, json={**access_payload, "evidence_hash": "0" * 64})).status_code == 409
    grant = await client.post(grant_path, json=access_payload)
    assert grant.status_code == 200, grant.text
    assert grant.headers["cache-control"] == "private, no-store"
    access_id = grant.json()["access_id"]
    access_path = f"{base}/performance-evidence/{access_id}"

    app.state.actor = 2
    assert (await client.get(access_path)).status_code == 404
    assert (await client.post(grant_path, json=access_payload)).status_code == 404
    app.state.actor = 1
    assert (await client.get(access_path.replace(project_id, "b" * 32))).status_code == 404
    assert (await client.get(access_path + "%C3%A9")).status_code == 404
    app.state.internal = True
    assert (await client.get(access_path)).status_code == 403
    app.state.internal = False

    rejected = await client.get(access_path, headers={"Range": "bytes=0-1,3-4"})
    assert rejected.status_code == 416
    assert rejected.headers["cache-control"] == "private, no-store"
    responses = await asyncio.gather(*(client.get(access_path, headers={"Range": "bytes=1-4"}) for _ in range(2)))
    assert sorted(response.status_code for response in responses) == [206, 404]
    accepted = next(response for response in responses if response.status_code == 206)
    assert accepted.content == body[1:5]
    assert accepted.headers["content-range"] == f"bytes 1-4/{len(body)}"
    assert accepted.headers["cache-control"] == "private, no-store"
    assert accepted.headers["content-disposition"].startswith("attachment;")
    assert (await client.get(access_path)).status_code == 404
    events = await runs.run_audit(actor, project_id, run_id)
    assert [event["action"] for event in events][-2:] == ["response_access_granted", "response_access_read"]


@pytest.mark.asyncio
async def test_run_admission_is_explicit_idempotent_and_owner_scoped(api, monkeypatch):
    client, app, base, _ = api
    plan_path, payload = await setup_plan(api, monkeypatch)
    app.include_router(router)
    payload["limits"].update(mode="performance", request_count=2)
    plan = await client.post(plan_path, json=payload)
    scenario = await client.post(
        plan_path.removesuffix("/plans") + "/performance-scenarios",
        json={"plan_id": plan.json()["id"], "profile": PROFILE, "confirmed": True},
    )
    run_payload = {"run_id": "e" * 32, "scenario_id": scenario.json()["id"], "scenario_hash": scenario.json()["definition_hash"], "confirmed": True}
    created = await client.post(base + "/performance-runs", json=run_payload)
    assert created.status_code == 200
    run_path = base + "/performance-runs/" + run_payload["run_id"]
    admission_path = run_path + "/admit"

    assert (await client.post(admission_path, json={"confirmed": False})).status_code == 422
    admitted = await client.post(admission_path, json={"confirmed": True})
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["status"] == "running"
    repeated = await client.post(admission_path, json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json() == admitted.json()
    dispatches = await client.get(run_path + "/dispatches")
    assert all(row["state"] == "pending" and row["send_started_ns"] is None for row in dispatches.json()["dispatches"])

    app.state.actor = 2
    assert (await client.post(admission_path, json={"confirmed": True})).status_code == 404
