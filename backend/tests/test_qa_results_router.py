"""Owner-scoped effectiveness result HTTP contract; synthetic records only."""

import pytest
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence

from app.evaluation.qa_result_cursor import StaleResultCursor
from app.evaluation.qa_results import ResultRepository


@pytest.mark.asyncio
async def test_effectiveness_result_routes_are_private_metadata_only(api, monkeypatch):
    client, _, base, _ = api
    legacy_root = await setup_evidence(api, monkeypatch)
    run_id = legacy_root.rsplit("/", 1)[1]
    result_root = base + "/runs/" + run_id

    responses = [
        await client.get(base + "/runs"),
        await client.get(result_root),
        await client.get(result_root + "/cases"),
        await client.get(result_root + "/cases/q1"),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert all(response.headers["cache-control"] == "private, no-store" for response in responses)
    assert responses[0].json()["items"][0]["run_id"] == run_id
    assert responses[2].json()["items"][0]["case_id"] == "q1"
    assert (await client.get(result_root + "/cases/not-a-case")).status_code == 404
    rejected_filters = [
        await client.get(base + "/runs", params={"free_text": "SYNTHETIC_GOLD"}),
        await client.get(base + "/runs", params={"status": ""}),
        await client.get(result_root + "/cases", params={"reference": "SYNTHETIC_GOLD"}),
        await client.get(result_root + "/cases", params={"kind": ""}),
    ]
    assert [response.status_code for response in rejected_filters] == [422, 422, 422, 422]
    assert all(response.headers["cache-control"] == "private, no-store" for response in rejected_filters)
    assert all("SYNTHETIC_GOLD" not in response.text for response in rejected_filters)
    combined = " ".join(response.text for response in responses)
    for secret in (
        "Synthetic Q",
        "SYNTHETIC_GOLD",
        "SYNTHETIC_OUTPUT",
        "SYNTHETIC_RAW_RESPONSE",
        "SYNTHETIC_REQUEST",
        "SYNTHETIC_NOTE",
        "reviewer",
    ):
        assert secret not in combined


@pytest.mark.asyncio
async def test_effectiveness_result_routes_enforce_auth_owner_and_cursor_errors(api, monkeypatch):
    client, app, base, _ = api
    legacy_root = await setup_evidence(api, monkeypatch)
    run_id = legacy_root.rsplit("/", 1)[1]
    run_root = base + "/runs/" + run_id

    assert (await client.get(base + "/runs/missing")).status_code == 404
    invalid = await client.get(run_root + "/cases", params={"cursor": "not-a-cursor"})
    assert invalid.status_code == 422
    assert invalid.headers["cache-control"] == "private, no-store"
    assert (await client.get(run_root + "/cases", params={"limit": 0})).status_code == 422

    app.state.actor = 2
    assert (await client.get(run_root)).status_code == 404
    assert (await client.get(run_root + "/cases")).status_code == 404
    app.state.actor = 0
    unauthenticated = await client.get(base + "/runs")
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "private, no-store"

    async def stale_cursor(*_args, **_kwargs):
        raise StaleResultCursor

    monkeypatch.setattr(ResultRepository, "list_cases", stale_cursor)
    app.state.actor = 1
    stale = await client.get(run_root + "/cases", params={"cursor": "signed-but-stale"})
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "private, no-store"
