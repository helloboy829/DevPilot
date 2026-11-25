"""Human-only execution receipts; synthetic target never dispatched by these API tests."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api

from app.evaluation.evidence_protection import EvidenceProtection
from app.evaluation.execution import ExecutionPolicy, ExecutionRepository
from app.evaluation.qa_artifact_store import ResponseArtifactStore
from app.gateway.authz import Permissions


async def setup_execution(api, monkeypatch, tmp_path):
    client, app, base, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    plan = (await client.post(path, json=payload)).json()
    key = Fernet.generate_key()
    repo = ExecutionRepository(
        app.state.evaluation_repo.sf,
        policy=ExecutionPolicy(enabled=True),
        evidence_protection=EvidenceProtection(key),
        response_artifact_store=ResponseArtifactStore(Path(tmp_path) / "qa-artifacts", key),
        config_getter=lambda: SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]}),
    )
    await repo.initialize()
    app.state.evaluation_execution_repo = repo
    return base + "/execution-runs/" + uuid4().hex, {"plan_id": plan["id"], "plan_hash": plan["definition_hash"], "confirmed": True, "target_authorized": True}


@pytest.mark.asyncio
async def test_execution_is_human_authorized_idempotent_private_and_never_sends_in_router(api, monkeypatch, tmp_path):
    client, app, base, _ = api
    path, payload = await setup_execution(api, monkeypatch, tmp_path)
    policy = await client.get(base + "/execution-policy")
    assert policy.status_code == 200 and policy.json()["enabled"] is True
    result = await client.put(path, json=payload)
    assert result.status_code == 200 and result.json()["state"] == "queued"
    assert "no-store" in result.headers["cache-control"]
    assert "SYNTHETIC" not in result.text and "claim_hash" not in result.text
    assert (await client.put(path, json=payload)).json() == result.json()
    assert len((await client.get(base + "/execution-runs")).json()["executions"]) == 1
    cancelled = await client.post(path + "/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["reservation_held"] is False
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 200
    assert (await client.put(path, json=payload)).status_code == 200
    assert (await client.post(path + "/cancel")).status_code == 200
    app.state.permissions += [Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW]
    app.state.internal = True
    assert (await client.put(path, json=payload)).status_code == 403
    assert (await client.post(path + "/cancel")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    assert (await client.get(base + "/execution-policy")).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_execution_reconciliation_is_original_id_read_only_and_owner_scoped(api, monkeypatch, tmp_path):
    client, app, base, _ = api
    path, payload = await setup_execution(api, monkeypatch, tmp_path)
    created = await client.put(path, json=payload)
    reconciliation_path = path + "/reconciliation"
    assert (await client.get(base + "/execution-runs/" + uuid4().hex + "/reconciliation")).status_code == 404

    before = await client.get(path)
    result = await client.get(reconciliation_path)
    assert result.status_code == 200
    body = result.json()
    assert body["execution"] == created.json()
    assert body["safety"]["scope"] == "execution_safety_observation_only"
    assert body["safety"]["state"] == "queued_ready"
    assert body["safety"]["worker_liveness"] == "not_established"
    assert body["safety"]["dispatch_authorized"] is False
    assert "claim_hash" not in result.text and "SYNTHETIC" not in result.text
    assert "no-store" in result.headers["cache-control"]
    assert (await client.get(path)).json() == before.json()

    assert (await client.get(reconciliation_path + "?unsupported=true")).status_code == 422
    app.state.actor = 2
    assert (await client.get(reconciliation_path)).status_code == 404


@pytest.mark.asyncio
async def test_execution_reconciliation_fails_closed_for_inconsistent_rows(api, monkeypatch, tmp_path):
    from sqlalchemy import update

    from app.evaluation import tables as t

    client, app, _, _ = api
    path, payload = await setup_execution(api, monkeypatch, tmp_path)
    await client.put(path, json=payload)
    execution_id = path.rsplit("/", 1)[1]
    async with app.state.evaluation_execution_repo.sf.begin() as session:
        await session.execute(update(t.executions).where(t.executions.c.id == execution_id).values(state="running", reservation_held=False))

    result = await client.get(path + "/reconciliation")
    assert result.status_code == 409
    assert "claim_hash" not in result.text and "SYNTHETIC" not in result.text


@pytest.mark.asyncio
async def test_operator_disabled_and_confirmation_validation_fail_closed(api, monkeypatch, tmp_path):
    client, app, base, _ = api
    path, payload = await setup_execution(api, monkeypatch, tmp_path)
    for changes in ({"target_authorized": 1}, {"confirmed": False}, {"secret": "SYNTHETIC_SECRET"}):
        result = await client.put(path, json={**payload, **changes})
        assert result.status_code == 422 and "SYNTHETIC_SECRET" not in result.text
    app.state.evaluation_execution_repo.policy = ExecutionPolicy()
    assert (await client.put(path, json=payload)).status_code == 409
    assert (await client.get(base + "/execution-runs")).json()["executions"] == []
