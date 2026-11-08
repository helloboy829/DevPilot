"""Private human-only retest API, synthetic data and no outbound requests."""

from uuid import UUID, uuid4

import pytest
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api

from app.evaluation.dispatch_journal import JournalLimits
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.qa_evidence import EvidenceRepository
from app.gateway.authz import Permissions


async def setup_pair(api, monkeypatch):
    client, app, base, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    owner = str(UUID(int=1))
    project = base.rsplit("/", 1)[1]
    clock = {"ms": 1_800_000_000_000}
    repo = EvidenceRepository(app.state.evaluation_repo.sf, clock_ms=lambda: clock["ms"])
    refs = []
    for version, decision in (("Synthetic v1", "fail"), ("Synthetic v2", "pass")):
        response = await client.post(path, json={**payload, "version_label": version})
        assert response.status_code == 200
        plan = response.json()
        clock["ms"] += 1000
        run = await repo.record_run(owner, project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=129))
        ticket = await repo.record_dispatch(owner, project, run["id"], 1, body_bytes=20)
        await repo.record_attempt(owner, project, run["id"], ticket, AttemptObservation("output_collected", 200, 30, 12.0, "SYNTHETIC_OUTPUT"))
        root = base + "/review-runs/" + run["id"]
        case = (await client.get(root + "/cases/1")).json()
        assert (await client.post(root + "/cases/1/reviews", json={"case_hash": case["case_hash"], "expected_revision": 0, "decision": decision, "note": "Synthetic note", "confirmed": True})).status_code == 200
        summary = (await client.get(root + "/summary")).json()
        refs.append({"run_id": summary["run_id"], "summary_hash": summary["summary_hash"]})
    return {"baseline": refs[0], "retest": refs[1], "confirmed": True}


@pytest.mark.asyncio
async def test_archive_permissions_owner_and_immutable_reads(api, monkeypatch):
    client, app, base, _ = api
    payload = await setup_pair(api, monkeypatch)
    path = base + "/retest-archives/" + uuid4().hex
    response = await client.put(path, json=payload)
    assert response.status_code == 200 and "no-store" in response.headers["cache-control"]
    saved = response.json()
    assert saved["transitions"]["fail_to_pass"] == 1 and saved["acceptance"] == "not_approved"
    assert "SYNTHETIC_OUTPUT" not in response.text and "SYNTHETIC_GOLD" not in response.text
    assert (await client.get(path)).json() == saved
    assert (await client.put(path, json=payload)).json() == saved
    assert len((await client.get(base + "/retest-archives")).json()["comparisons"]) == 1
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(path)).json() == saved
    assert (await client.put(path, json=payload)).json() == saved
    assert (await client.put(base + "/retest-archives/" + uuid4().hex, json=payload)).status_code == 503
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(path)).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
    assert (await client.get(path)).status_code == 200
    assert (await client.put(path, json=payload)).status_code == 403
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    assert (await client.get(base + "/retest-archives")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_validation_conflicts_and_no_update_delete_routes(api, monkeypatch):
    client, _, base, _ = api
    payload = await setup_pair(api, monkeypatch)
    path = base + "/retest-archives/" + uuid4().hex
    for bad in ({**payload, "confirmed": 1}, {**payload, "metrics": {"rate": 1}}, {**payload, "retest": {"run_id": "SYNTHETIC_PRIVATE", "summary_hash": "x"}}):
        response = await client.put(path, json=bad)
        assert response.status_code == 422 and "SYNTHETIC_PRIVATE" not in response.text
        assert "no-store" in response.headers["cache-control"]
    assert (await client.get(base + "/retest-archives/not-valid")).status_code == 422
    assert (await client.put(path, json={**payload, "retest": payload["baseline"]})).status_code == 409
    assert (await client.put(path, json=payload)).status_code == 200
    assert (await client.put(path, json={**payload, "baseline": payload["retest"], "retest": payload["baseline"]})).status_code == 409
    for method in ("patch", "delete", "post"):
        assert (await getattr(client, method)(path)).status_code == 405
