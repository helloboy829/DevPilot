"""Synthetic owner/human assessment API; no network targets or live credentials."""

import pytest
from sqlalchemy.exc import OperationalError
from test_evaluation_registry_router import api as api
from test_qa_evidence_router import setup_evidence

from app.evaluation.dispatch_journal import JournalWriteUnconfirmed
from app.evaluation.qa_assessments import AssessmentRepository
from app.gateway.authz import Permissions

ID = "c" * 32


@pytest.mark.asyncio
async def test_explicit_preview_archive_same_id_receipt_and_private_metadata(api, monkeypatch):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    preview = await client.get(root + "/independent-assessment")
    assert preview.status_code == 200 and "no-store" in preview.headers["cache-control"]
    doc = preview.json()
    assert doc["counts"]["unreviewed"] == 1 and doc["acceptance"] == "not_approved"
    payload = {"summary_hash": doc["summary_hash"], "expected_previous_revision": 0, "confirmed": True}
    path = root + "/assessments/" + ID
    created = await client.post(path, json=payload)
    assert created.status_code == 200 and created.json()["revision"] == 1
    assert (await client.get(path)).json() == created.json()
    assert (await client.post(path, json=payload)).json() == created.json()
    listing = await client.get(root + "/assessments")
    assert listing.status_code == 200 and len(listing.json()) == 1
    assert "document" not in listing.text and "cases" not in listing.text
    for response in (preview, created, listing):
        assert "no-store" in response.headers["cache-control"]
        assert not any(secret in response.text for secret in ("SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_TOKEN", "encrypted_payload"))
    conflict = await client.post(path, json={**payload, "expected_previous_revision": 1})
    assert conflict.status_code == 409
    assert (await client.delete(path)).status_code == 405


@pytest.mark.asyncio
async def test_every_read_and_append_enforce_owner_human_permissions(api, monkeypatch):
    client, app, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    summary = (await client.get(root + "/independent-assessment")).json()
    payload = {"summary_hash": summary["summary_hash"], "expected_previous_revision": 0, "confirmed": True}
    path = root + "/assessments/" + ID
    assert (await client.post(path, json=payload)).status_code == 200
    reads = [root + "/independent-assessment", root + "/assessments", path]
    original = app.state.permissions
    for permissions, get_status, post_status in (([Permissions.EVALUATION_PROJECTS_READ], 403, 403), ([Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW], 200, 403)):
        app.state.permissions = permissions
        assert [(await client.get(p)).status_code for p in reads] == [get_status] * 3
        assert (await client.post(path, json=payload)).status_code == post_status
    app.state.permissions = original
    app.state.internal = True
    assert [(await client.get(p)).status_code for p in reads] == [403] * 3
    assert (await client.post(path, json=payload)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert [(await client.get(p)).status_code for p in reads] == [404] * 3
    assert (await client.post(path, json=payload)).status_code == 404
    app.state.actor = 0
    assert [(await client.get(p)).status_code for p in reads] == [401] * 3
    assert (await client.post(path, json=payload)).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_unknown_append_only_reconciles_same_id_and_generic_errors(api, monkeypatch, committed):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    summary = (await client.get(root + "/independent-assessment")).json()
    payload = {"summary_hash": summary["summary_hash"], "expected_previous_revision": 0, "confirmed": True}
    path = root + "/assessments/" + ID
    original = AssessmentRepository.create_assessment

    async def committed_but_unconfirmed(self, *args, **kwargs):
        if committed:
            await original(self, *args, **kwargs)
        raise JournalWriteUnconfirmed("SYNTHETIC_SECRET")

    monkeypatch.setattr(AssessmentRepository, "create_assessment", committed_but_unconfirmed)
    result = await client.post(path, json=payload)
    assert result.status_code == 503 and "SYNTHETIC" not in result.text and "no-store" in result.headers["cache-control"]
    found = await client.get(path)
    assert found.status_code == (200 if committed else 404)
    if committed:
        assert found.json()["revision"] == 1
    assert len((await client.get(root + "/assessments")).json()) == int(committed)

    async def sql_failure(self, *args, **kwargs):
        raise OperationalError("SYNTHETIC_SQL", {"secret": "SYNTHETIC_SECRET"}, Exception("SYNTHETIC_EXCEPTION"))

    monkeypatch.setattr(AssessmentRepository, "get_preview", sql_failure)
    failed = await client.get(root + "/independent-assessment")
    assert failed.status_code == 503 and "SYNTHETIC" not in failed.text


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"summary_hash": "SYNTHETIC_SECRET"}, {"counts": {"pass": 999}}, {"expected_previous_revision": True}])
async def test_validation_redacts_all_client_values(api, monkeypatch, changes):
    client, _, _, _ = api
    root = await setup_evidence(api, monkeypatch)
    result = await client.post(root + "/assessments/" + ID, json={"summary_hash": "a" * 64, "expected_previous_revision": 0, "confirmed": True, **changes})
    assert result.status_code == 422 and "SYNTHETIC_SECRET" not in result.text and "no-store" in result.headers["cache-control"]
