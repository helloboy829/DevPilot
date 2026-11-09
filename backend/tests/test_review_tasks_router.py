"""Synthetic authenticated independent task API; no real account/model/target I/O."""

import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import OperationalError
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence

from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.review_tasks import ReviewTaskRepository
from app.gateway.auth.models import User
from app.gateway.authz import Permissions
from app.gateway.routers import evaluation_review_tasks as routes

TASK = "a" * 32
A, B, ARB, OTHER = [str(UUID(int=i)) for i in range(2, 6)]
ROOT = "/api/evaluation/review-tasks"


async def ready(api, monkeypatch, *, create=True):
    client, app, base, _ = api
    app.include_router(routes.router)
    app.include_router(routes.project_router)
    source = await setup_evidence(api, monkeypatch)
    case = (await client.get(source + "/cases/1")).json()
    users = {key: User(id=UUID(key), email=f"reviewer{index}@example.com") for index, key in enumerate((A, B, ARB))}

    async def get_user(key):
        return users.get(key)

    monkeypatch.setattr(routes, "get_local_provider", lambda: SimpleNamespace(get_user=get_user))
    payload = {"run_id": source.rsplit("/", 1)[1], "ordinal": 1, "case_hash": case["case_hash"], "reviewer_ids": [A, B], "arbitrator_id": ARB, "share_reference": True, "confirmed": True}
    if create:
        response = await client.post(base + "/review-tasks/" + TASK, json=payload)
        assert response.status_code == 200, response.text
    return source, payload, users


def command(task):
    return {"expected_revision": task["revision"], "confirmed": True}


async def vote(client, app, actor, outcome):
    app.state.actor = actor
    task = (await client.get(ROOT + "/" + TASK)).json()
    claimed = await client.post(ROOT + "/" + TASK + "/claim", json=command(task))
    assert claimed.status_code == 200, claimed.text
    opened = await client.get(ROOT + "/" + TASK + "/case")
    assert opened.status_code == 200, opened.text
    assert "no-store" in opened.headers["cache-control"]
    assert "SYNTHETIC_GOLD" in opened.text and "SYNTHETIC_OUTPUT" in opened.text
    task = claimed.json()
    response = await client.post(ROOT + "/" + TASK + "/decisions", json={**command(task), "subject_hash": task["subject_hash"], "decision": outcome, "note": "SYNTHETIC_PRIVATE_NOTE"})
    assert response.status_code == 200, response.text
    return response.json(), opened.json()


@pytest.mark.asyncio
async def test_independent_http_flow_grants_no_project_membership_and_preserves_blindness(api, monkeypatch):
    client, app, base, _ = api
    source, payload, _ = await ready(api, monkeypatch)
    task = (await client.get(base + "/review-tasks")).json()["tasks"][0]
    assert task["role"] == "owner" and len(task["assignments"]) == 3
    assert (await client.post(base + "/review-tasks/" + TASK, json=payload)).json() == task
    first, opened = await vote(client, app, 2, "pass")
    assert opened["prior_decisions"] == [] and first["status"] == "in_review"
    assert (await client.get(source + "/cases/1")).status_code == 404
    assert (await client.get(base + "/datasets")).status_code == 404
    assert (await client.get(base + "/review-tasks")).status_code == 404
    assert (await client.get(ROOT + "/" + TASK + "/result")).status_code == 404
    app.state.actor = 3
    listing = await client.get(ROOT)
    assert listing.status_code == 200 and "no-store" in listing.headers["cache-control"]
    for secret in (A, ARB, "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_PRIVATE_NOTE", "encrypted_payload"):
        assert secret not in listing.text
    second, opened = await vote(client, app, 3, "fail")
    assert opened["prior_decisions"] == [] and second["status"] == "escalated"
    final, opened = await vote(client, app, 4, "fail")
    assert len(opened["prior_decisions"]) == 2 and final["status"] == "resolved"
    app.state.actor = 1
    result = await client.get(ROOT + "/" + TASK + "/result")
    assert result.status_code == 200 and result.json()["resolution"]["outcome"] == "fail"
    assert result.json()["resolution"]["approval"] == "not_approved"
    # New decisions do not rewrite legacy owner review records or summaries.
    assert (await client.get(source + "/cases/1")).json()["reviews"] == []
    reopened = await client.post(ROOT + "/" + TASK + "/reopen", json={**command(final), "reason": "SYNTHETIC_REOPEN"})
    assert reopened.status_code == 200 and reopened.json()["round"] == 2
    assert (await client.get(ROOT + "/" + TASK + "/result?round_number=1")).json() == result.json()
    assert (await client.post(ROOT + "/" + TASK + "/cancel", json=command(reopened.json()))).json()["status"] == "cancelled"
    app.state.actor = 2
    assert (await client.get(ROOT + "/" + TASK + "/case")).status_code == 409
    app.state.actor = 5
    assert (await client.get(ROOT)).json()["tasks"] == []
    assert (await client.get(ROOT + "/" + TASK)).status_code == 404


@pytest.mark.parametrize("mode", ["missing", "needs_setup", "owner", "duplicate", "reference_not_shared"])
@pytest.mark.asyncio
async def test_explicit_distinct_ready_human_accounts_and_reference_grant_required(api, monkeypatch, mode):
    client, app, base, _ = api
    _, payload, users = await ready(api, monkeypatch, create=False)
    if mode == "missing":
        users.pop(A)
    elif mode == "needs_setup":
        users[A].needs_setup = True
    elif mode == "owner":
        payload["reviewer_ids"][0] = str(UUID(int=1))
    elif mode == "duplicate":
        payload["arbitrator_id"] = A
    else:
        payload["share_reference"] = False
    response = await client.post(base + "/review-tasks/" + TASK, json=payload)
    assert response.status_code == (422 if mode in {"duplicate", "reference_not_shared"} else 409)
    assert "SYNTHETIC" not in response.text and "example.com" not in response.text
    assert (await client.get(ROOT)).json()["tasks"] == []


@pytest.mark.asyncio
async def test_task_routes_auth_human_permissions_and_owner_actions_are_separate(api, monkeypatch):
    client, app, base, _ = api
    _, payload, _ = await ready(api, monkeypatch)
    task = (await client.get(ROOT + "/" + TASK)).json()
    app.state.actor = 2
    task = (await client.get(ROOT + "/" + TASK)).json()
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(ROOT)).status_code == 200
    assert (await client.post(ROOT + "/" + TASK + "/claim", json=command(task))).status_code == 403
    assert (await client.get(ROOT + "/" + TASK + "/case")).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    claimed = await client.post(ROOT + "/" + TASK + "/claim", json=command(task))
    assert claimed.status_code == 200
    assert (await client.get(ROOT + "/" + TASK + "/case")).status_code == 200
    assert (await client.post(ROOT + "/" + TASK + "/cancel", json=command(claimed.json()))).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_WRITE)
    assert (await client.post(ROOT + "/" + TASK + "/cancel", json=command(claimed.json()))).status_code == 404
    app.state.internal = True
    for path in (ROOT, ROOT + "/" + TASK, ROOT + "/" + TASK + "/case", base + "/review-tasks"):
        assert (await client.get(path)).status_code == 403
    assert (await client.post(base + "/review-tasks/" + "b" * 32, json=payload)).status_code == 403
    assert (await client.post(ROOT + "/" + TASK + "/claim", json=command(claimed.json()))).status_code == 403
    app.state.internal = False
    app.state.actor = 0
    assert (await client.get(ROOT)).status_code == 401


@pytest.mark.parametrize("change", [{"confirmed": 1}, {"note": "SYNTHETIC_PRIVATE" * 2000}, {"expected_revision": True}, {"output": "SYNTHETIC_FORGED"}])
@pytest.mark.asyncio
async def test_validation_and_size_errors_do_not_echo_sensitive_values(api, monkeypatch, change):
    client, app, _, _ = api
    await ready(api, monkeypatch)
    app.state.actor = 2
    task = (await client.get(ROOT + "/" + TASK)).json()
    response = await client.post(ROOT + "/" + TASK + "/decisions", json={**command(task), "subject_hash": task["subject_hash"], "decision": "pass", "note": "SYNTHETIC_PRIVATE", **change})
    assert response.status_code in {413, 422} and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"]
    oversized = await client.post(ROOT + "/" + TASK + "/claim", content=json.dumps({"private": "SYNTHETIC_PRIVATE" * 4000}), headers={"Content-Type": "application/json"})
    assert oversized.status_code == 413 and "SYNTHETIC" not in oversized.text
    assert "no-store" in oversized.headers["cache-control"]


@pytest.mark.parametrize("failure", ["unconfirmed", "sql"])
@pytest.mark.asyncio
async def test_unknown_create_commit_only_reconciles_same_id_via_get(api, monkeypatch, failure):
    client, app, base, _ = api
    _, payload, _ = await ready(api, monkeypatch, create=False)
    original = ReviewTaskRepository.create_task
    calls = 0

    async def ambiguous(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        await original(self, *args, **kwargs)
        if failure == "unconfirmed":
            raise JournalWriteUnconfirmed("SYNTHETIC_PRIVATE")
        raise OperationalError("SYNTHETIC_PRIVATE", {}, Exception("SYNTHETIC_GOLD"))

    monkeypatch.setattr(ReviewTaskRepository, "create_task", ambiguous)
    response = await client.post(base + "/review-tasks/" + TASK, json=payload)
    assert response.status_code == 503 and "SYNTHETIC" not in response.text
    assert "never automatically resend" in response.text and calls == 1
    reconciled = await client.get(ROOT + "/" + TASK)
    assert reconciled.status_code == 200 and reconciled.json()["id"] == TASK
    assert len((await client.get(base + "/review-tasks")).json()["tasks"]) == 1 and calls == 1


@pytest.mark.asyncio
async def test_missing_encryption_key_keeps_only_metadata_available(api, monkeypatch):
    client, app, _, _ = api
    await ready(api, monkeypatch)
    app.state.actor = 2
    task = (await client.get(ROOT + "/" + TASK)).json()
    await client.post(ROOT + "/" + TASK + "/claim", json=command(task))
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    assert (await client.get(ROOT)).status_code == 200
    response = await client.get(ROOT + "/" + TASK + "/case")
    assert response.status_code == 503 and "SYNTHETIC" not in response.text


@pytest.mark.asyncio
async def test_unknown_decision_commit_reconciles_submitted_assignment_without_resend(api, monkeypatch):
    client, app, _, _ = api
    await ready(api, monkeypatch)
    app.state.actor = 2
    task = (await client.get(ROOT + "/" + TASK)).json()
    task = (await client.post(ROOT + "/" + TASK + "/claim", json=command(task))).json()
    assert (await client.get(ROOT + "/" + TASK + "/case")).status_code == 200
    original = ReviewTaskRepository.submit_decision
    calls = 0

    async def ambiguous(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        await original(self, *args, **kwargs)
        raise JournalWriteUnconfirmed("SYNTHETIC_PRIVATE")

    monkeypatch.setattr(ReviewTaskRepository, "submit_decision", ambiguous)
    payload = {**command(task), "subject_hash": task["subject_hash"], "decision": "pass", "note": "SYNTHETIC_PRIVATE"}
    response = await client.post(ROOT + "/" + TASK + "/decisions", json=payload)
    assert response.status_code == 503 and "SYNTHETIC" not in response.text
    receipt = await client.get(ROOT + "/" + TASK)
    assert receipt.status_code == 200 and receipt.json()["assignment"]["status"] == "submitted"
    assert calls == 1
    # Deliberately attempt an old duplicate to prove the server also fences replay.
    assert (await client.post(ROOT + "/" + TASK + "/decisions", json=payload)).status_code == 409
