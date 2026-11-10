"""Verify public browser fixtures against real quarantine/source algorithms and API.

Technical claims may be coherent forgeries. No fixture is platform evidence.
"""

import json
import os
from pathlib import Path
from uuid import UUID

import pytest
from test_evaluation_registry_router import api as api
from test_external_qa_quarantine import declared_pair, request_for, setup_intake, untrusted
from test_external_qa_quarantine import no_network as no_network

from app.evaluation import external_qa_quarantine as quarantine
from app.evaluation.authorized_exports import ExportCreate
from app.evaluation.registry import fingerprint

FIXTURE = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/synthetic-external-qa.json"


def verify_fixture(item):
    receipt = item["export_receipt"]
    source_request = ExportCreate.model_validate(
        {
            "plan_id": receipt["plan_id"],
            "plan_hash": receipt["plan_hash"],
            "grant_id": receipt["grant"]["id"],
            "recipient_id": receipt["recipient_id"],
            "tier": receipt["tier"],
            "confirmed": True,
            "data_use_confirmed": True,
            "external_controls_acknowledged": True,
        }
    )
    export_doc = {key: value for key, value in receipt.items() if key != "receipt_hash"}
    snapshot = {
        "project": {"id": receipt["project_id"]},
        "plan": item["plan"],
        "export": {
            **{key: receipt[key] for key in ("id", "project_id", "plan_id", "created_at_ms", "receipt_hash")},
            "owner_id": receipt["grant"]["owner_id"],
            "document": export_doc,
            "request_hash": fingerprint(source_request.model_dump()),
        },
    }
    payload = quarantine.ExternalQAIntakeCreate.model_validate(item["request"])
    source, inspection, canonical, lengths = quarantine._prepare(snapshot, payload)
    want = item["receipt"]
    document = quarantine._document(want["id"], receipt["project_id"], want["created_at_ms"], source, inspection, canonical, lengths)
    archive_hash = fingerprint({"owner_id": receipt["grant"]["owner_id"], "request_hash": quarantine._request_hash(source, inspection, lengths), "document": document})
    assert want == {**document, "archive_hash": archive_hash}
    untrusted(want)
    assert inspection["frozen_input_count"] == receipt["all_frozen_samples"]
    assert inspection["frozen_request_count"] == item["plan"]["definition"]["limits"]["request_count"]
    assert all(want["canonical_source_sha256"][name] != inspection["declared_raw_sha256"][name] for name in canonical)
    assert payload.receipt_json.startswith(" \n") and payload.reconciliation_json.endswith(" \n")
    for forbidden in ("SYNTHETIC_GOLD", "SYNTHETIC_SECRET", "SYNTHETIC_PATH", "SYNTHETIC_BODY", "bundle_base64", "ciphertext"):
        assert forbidden not in json.dumps(item)


def test_committed_browser_fixture_matches_backend_source_parser_and_archive_hashes():
    # Required, never silently skipped when an artifact drifts or goes missing.
    verify_fixture(json.loads(FIXTURE.read_text(encoding="utf-8")))


@pytest.mark.asyncio
async def test_generate_synthetic_browser_fixture_from_actual_intake_api(api, monkeypatch):
    _, source, plan = await setup_intake(api, monkeypatch)
    client, _, base, _ = api
    payload = request_for(source, *declared_pair(source, run_id=str(UUID(int=4))))
    path = base + "/external-qa-intakes/" + "e" * 32
    response = await client.put(path, json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert (await client.get(path)).json() == receipt
    audit = await client.get(path + "/audit?after_sequence=0&limit=50")
    assert audit.status_code == 200 and audit.json()["next_after_sequence"] is None
    assert [e["action"] for e in audit.json()["events"]] == ["metadata_quarantined"]
    item = {"export_receipt": source, "plan": plan, "request": payload, "receipt": receipt, "audit": audit.json()}
    verify_fixture(item)
    assert (await client.put(path, json=payload)).status_code == 409
    destination = os.getenv("TEST_EXTERNAL_QA_BROWSER_FIXTURE")
    if destination:
        assert destination == "/tmp/extqa-ui-generated-fixture.json"
        Path(destination).write_text(json.dumps(item, indent=2) + "\n", encoding="utf-8")
