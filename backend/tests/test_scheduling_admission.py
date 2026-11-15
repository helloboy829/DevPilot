"""QA scheduling admission is a fixed diagnostic; it never dispatches or releases."""

import json

import httpx
import pytest
from test_execution_operations_router import administrator, policy
from test_qa_authenticated_workflow_api import ORIGIN
from test_qa_authenticated_workflow_api import api as api
from test_qa_authenticated_workflow_api import workflow as workflow

from app.evaluation.scheduling_safety import scheduling_admission

PATH = "/api/evaluation/operations/scheduling-admission"


def test_projection_is_fixed_and_never_authorizes():
    result = scheduling_admission()
    assert result == {
        "schema": "qa-scheduling-admission.v1",
        "scope": "qa_scheduling_admission_diagnostic_only",
        "scheduler_scope": "component_tests_only",
        "qa_chain_admitted": False,
        "dispatch_authorized": False,
        "release_authorized": False,
        "blockers": [
            "no_versioned_admission_contract",
            "scheduler_not_bound_to_qa_execution",
            "worker_liveness_not_established",
        ],
    }
    json.dumps(result)


def test_mutating_the_result_does_not_change_later_calls():
    first = scheduling_admission()
    first["blockers"].append("synthetic")
    first["dispatch_authorized"] = True
    assert scheduling_admission()["blockers"] == [
        "no_versioned_admission_contract",
        "scheduler_not_bound_to_qa_execution",
        "worker_liveness_not_established",
    ]
    assert scheduling_admission()["dispatch_authorized"] is False


@pytest.mark.asyncio
async def test_authenticated_admin_with_explicit_permission_reads_private_snapshot(workflow):
    admin = await administrator(workflow.app)
    result = await admin.get(PATH)
    assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
    assert result.json()["qa_chain_admitted"] is False and result.json()["dispatch_authorized"] is False
    assert "SYNTHETIC" not in result.text
    assert (await admin.post(PATH)).status_code == 405


@pytest.mark.asyncio
async def test_admin_without_permission_or_internal_caller_is_denied(workflow):
    admin = await administrator(workflow.app)
    identities = workflow.app.state.test_accounts
    identities.policy["value"] = policy(allowed=False)
    denied = await admin.get(PATH)
    assert denied.status_code == 403 and denied.headers["cache-control"] == "private, no-store"
    identities.policy["value"] = policy()
    internal = await admin.get(PATH, headers={"X-DeerFlow-Internal-Token": "synthetic-test-only-internal-token"})
    assert internal.status_code == 403 and internal.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_non_admin_and_anonymous_are_denied(workflow):
    await administrator(workflow.app)
    identities = workflow.app.state.test_accounts
    for actor in ("reviewer_a", "reviewer_b", "arbitrator"):
        response = await identities.clients[actor].get(PATH)
        assert response.status_code == 403
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=workflow.app), base_url=ORIGIN) as anonymous:
        denied = await anonymous.get(PATH)
    assert denied.status_code == 401
