"""External technical metadata is immutable quarantine, never platform evidence."""

import asyncio
import copy
import hashlib
import io
import json
import socket
import threading
import zipfile
from uuid import uuid4

import pytest
from devpilot.local_qa_cli import LocalOutboundPolicy, execute_local, preflight
from devpilot.local_qa_reconcile import reconcile
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from test_authorized_qa_exports import OWNER, open_url, setup_export
from test_evaluation_registry_router import api as api
from test_local_qa_cli import mock_wire

from app.evaluation import external_qa_quarantine as quarantine
from app.evaluation import tables as t
from app.evaluation.external_qa_quarantine import ExternalQAIntakeCreate, ExternalQAIntakeRepository
from app.gateway.authz import Permissions
from app.gateway.routers import evaluation_external_qa


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def declared_pair(source, *, run_id=None, state="collected"):
    """A coherent FORGERY must be accepted only as untrusted technical metadata."""
    common = {
        "scope": "external_unverified_technical_only",
        "verdict": "NOT_EVALUATED",
        "run_id": run_id or str(uuid4()),
        "frozen_input_count": source["all_frozen_samples"],
        "frozen_request_count": 1,
        "platform_provenance_verified": False,
        "resend_permitted": False,
        "resume_permitted": False,
    }
    receipt = {**common, "schema": "local-qa-run-receipt.v1", "receipt_kind": "pre_dispatch_identity_only", "manifest_fingerprint": source["manifest_fingerprint"]}
    summary = {
        **common,
        "schema": "local-qa-reconciliation.v1",
        "declared_source_sha256": source["manifest_fingerprint"],
        "state": state,
        "output_content_verified": False,
        "reserved_attempt_count": 1,
        "unreserved_in_snapshot_count": 0,
        "covered_input_count": 1,
        "attempt_states": {"dispatched": 0, "observed": 1, "delivery_unknown": 0},
        "observation_kinds": {"delivery_unknown": 0, "http_error": 0, "invalid_output": 0, "output_collected": 1, "policy_rejected": 0, "response_limit": 0, "unsupported_response": 0},
        "reserved_request_bytes": 20,
        "reserved_response_bytes": 100,
    }
    return receipt, summary


def request_for(source, receipt, summary):
    # Raw whitespace is intentional: StrictDTO's normal stripping must NOT change it.
    raw_receipt, raw_summary = " \n" + encode(receipt) + "\n ", "\n" + encode(summary) + " \n"
    return {
        "export_id": source["id"],
        "viewed_export_receipt_hash": source["receipt_hash"],
        "original_run_id": receipt["run_id"],
        "manifest_fingerprint": source["manifest_fingerprint"],
        "receipt_json": raw_receipt,
        "receipt_sha256": sha(raw_receipt),
        "reconciliation_json": raw_summary,
        "reconciliation_sha256": sha(raw_summary),
        "confirmed": True,
        "technical_metadata_only_confirmed": True,
        "untrusted_source_acknowledged": True,
    }


async def source_for(api, monkeypatch, *, tier="baseline_inputs"):
    repo, path, request, plan = await setup_export(api, monkeypatch, tier=tier)
    response = await api[0].put(path, json=request)
    assert response.status_code == 200, response.text
    return repo, response.json(), plan


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


async def setup_intake(api, monkeypatch, *, tier="baseline_inputs"):
    export_repo, source, plan = await source_for(api, monkeypatch, tier=tier)
    app = api[1]
    repo = ExternalQAIntakeRepository(export_repo.sf, clock_ms=lambda: 20_000)
    app.state.evaluation_external_qa_repo = repo
    app.include_router(evaluation_external_qa.router)
    app.state.permissions.extend([Permissions.EVALUATION_EXTERNAL_QA_READ, Permissions.EVALUATION_EXTERNAL_QA_CREATE])
    return repo, source, plan


def untrusted(document):
    assert document["verdict"] == "NOT_EVALUATED"
    for key in ("evidence_admitted", "approval_granted", "dispatch_authorized", "resend_permitted", "resume_permitted"):
        assert document[key] is False
    inspection = document["inspection"]
    assert inspection["verdict"] == "NOT_EVALUATED"
    for key in ("platform_provenance_verified", "per_ordinal_evidence_verified", "output_content_verified", "evidence_admitted", "approval_granted", "dispatch_authorized", "resend_permitted", "resume_permitted"):
        assert inspection[key] is False


async def counts(repo):
    async with repo.sf() as session:
        return {table.name: await session.scalar(select(func.count()).select_from(table)) for table in t.metadata.sorted_tables}


@pytest.mark.asyncio
async def test_http_persistent_quarantine_and_coherent_forgery(api, monkeypatch):
    repo, source, _ = await setup_intake(api, monkeypatch)
    payload = request_for(source, *declared_pair(source))
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    response = await api[0].put(path, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["scope"] == "external_technical_metadata_quarantine_only"
    assert response.json()["verdict"] == "NOT_EVALUATED"
    document = response.json()
    untrusted(document)
    assert document["inspection"]["frozen_input_count"] == document["inspection"]["frozen_request_count"] == 1
    assert document["source"]["export_receipt"] == source
    assert document["inspection"]["declared_raw_sha256"] == {"receipt": payload["receipt_sha256"], "reconciliation": payload["reconciliation_sha256"]}
    assert document["canonical_source_sha256"]["receipt"] != payload["receipt_sha256"]
    assert (await api[0].get(path)).json() == document
    assert (await api[0].put(path, json=payload)).status_code == 409
    for method in ("post", "patch", "delete"):
        assert (await api[0].request(method, path, json=payload)).status_code == 405
    audit = (await api[0].get(path + "/audit?limit=1")).json()
    assert audit["next_after_sequence"] == 1
    assert [e["action"] for e in audit["events"]] == ["metadata_quarantined"]
    assert (await api[0].get(path + "/audit?after_sequence=1")).json()["events"] == []
    async with repo.sf() as session:
        row = dict((await session.execute(select(t.external_qa_intakes))).mappings().one())
    assert row["canonical_receipt"] != payload["receipt_json"]
    assert sha(row["canonical_receipt"]) == document["canonical_source_sha256"]["receipt"]
    assert "canonical_receipt" not in document and "receipt_json" not in document
    assert "receipt_json=" not in repr(ExternalQAIntakeCreate.model_validate(payload))


@pytest.mark.asyncio
async def test_no_sensitive_reads_keys_or_mutations_and_no_current_grant_lookup(api, monkeypatch):
    repo, source, _ = await setup_intake(api, monkeypatch)
    before = await counts(repo)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())

    def forbidden(*_args, **_kwargs):
        raise AssertionError("No secret or current-grant lookup allowed")

    export_repo = api[1].state.evaluation_export_repo
    monkeypatch.setattr(export_repo, "_protection", forbidden)
    monkeypatch.setattr(export_repo, "_grant", forbidden)
    export_repo.clock_ms = lambda: 2_000_000  # Historical export remains usable.
    engine = repo.sf.kw["bind"]
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    try:
        response = await api[0].put(path, json=request_for(source, *declared_pair(source)))
        assert response.status_code == 200, response.text
        assert (await api[0].get(path)).json() == response.json()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    for statement in statements:
        for forbidden_name in ("encrypted_bundle", "encrypted_request", "evaluation_qa_samples", "evaluation_qa_references", "evaluation_output_evidence", "evaluation_human_reviews"):
            assert forbidden_name not in statement
    after = await counts(repo)
    assert {key: value for key, value in after.items() if key not in {t.external_qa_intakes.name, t.external_qa_intake_audit.name}} == {
        key: value for key, value in before.items() if key not in {t.external_qa_intakes.name, t.external_qa_intake_audit.name}
    }
    assert after[t.external_qa_intakes.name] == after[t.external_qa_intake_audit.name] == 1
    for text in ("SYNTHETIC_GOLD", "Synthetic Q", "SYNTHETIC_SECRET", "SYNTHETIC_BODY"):
        assert text not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["confirmed", "technical_metadata_only_confirmed", "untrusted_source_acknowledged"])
@pytest.mark.parametrize("value", [False, 1, "true", None])
async def test_each_independent_consent_is_exact_true(api, monkeypatch, field, value):
    repo, source, _ = await setup_intake(api, monkeypatch)
    payload = request_for(source, *declared_pair(source))
    payload[field] = value
    response = await api[0].put(api[2] + "/external-qa-intakes/" + uuid4().hex, json=payload)
    assert response.status_code == 422 and "no-store" in response.headers["cache-control"]
    assert (await counts(repo))[t.external_qa_intakes.name] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["raw_hash", "duplicate", "output", "pass", "utf8_bytes", "deep", "float", "original_id", "all_samples", "requests", "manifest", "viewed_hash"])
async def test_corrupt_untrusted_payloads_fail_privately(api, monkeypatch, change):
    repo, source, _ = await setup_intake(api, monkeypatch)
    receipt, summary = declared_pair(source)
    if change == "output":
        summary["output"] = "SENSITIVE_MUST_NOT_ECHO"
    elif change == "pass":
        summary["verdict"] = "PASS"
    elif change in {"all_samples", "requests"}:
        for document in (receipt, summary):
            document["frozen_request_count"] = 2
            if change == "all_samples":
                document["frozen_input_count"] = 2
    elif change == "float":
        summary["reserved_request_bytes"] = 20.0
    elif change == "manifest":
        receipt["manifest_fingerprint"] = summary["declared_source_sha256"] = "f" * 64
    if change in {"all_samples", "requests"}:
        summary["state"] = "running"
        summary["unreserved_in_snapshot_count"] = 1
    payload = request_for(source, receipt, summary)
    if change in {"all_samples", "requests"}:
        # This case must pass structural inspection and fail historical-source
        # alignment, not accidentally stop at an incoherent aggregate.
        quarantine.inspect_local_metadata(
            payload["receipt_json"].encode("utf-8"),
            payload["reconciliation_json"].encode("utf-8"),
            original_run_id=payload["original_run_id"],
            manifest_fingerprint=payload["manifest_fingerprint"],
            receipt_sha256=payload["receipt_sha256"],
            reconciliation_sha256=payload["reconciliation_sha256"],
        )
    if change == "raw_hash":
        payload["receipt_sha256"] = "0" * 64
    elif change == "duplicate":
        payload["receipt_json"] = encode(receipt)[:-1] + ',"verdict":"NOT_EVALUATED"}'
    elif change == "utf8_bytes":
        payload["receipt_json"] = " " * 8191 + "中"
    elif change == "deep":
        payload["receipt_json"] = '{"x":' * 10 + "0" + "}" * 10
    elif change == "original_id":
        payload["original_run_id"] = str(uuid4())
    elif change == "viewed_hash":
        payload["viewed_export_receipt_hash"] = "0" * 64
    if change in {"duplicate", "utf8_bytes", "deep"}:
        payload["receipt_sha256"] = sha(payload["receipt_json"])
    response = await api[0].put(api[2] + "/external-qa-intakes/" + uuid4().hex, json=payload)
    assert response.status_code == (409 if change in {"all_samples", "requests", "viewed_hash"} else 422), response.text
    assert "SENSITIVE_MUST_NOT_ECHO" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert (await counts(repo))[t.external_qa_intakes.name] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source_manifest", "body_budget"])
async def test_coherent_pair_still_requires_historical_source_alignment(api, monkeypatch, change):
    repo, source, plan = await setup_intake(api, monkeypatch)
    receipt, summary = declared_pair(source)
    if change == "source_manifest":
        receipt["manifest_fingerprint"] = summary["declared_source_sha256"] = "f" * 64
    else:
        summary["reserved_request_bytes"] = plan["definition"]["limits"]["max_total_body_bytes"] + 1
    payload = request_for(source, receipt, summary)
    if change == "source_manifest":
        payload["manifest_fingerprint"] = "f" * 64
    inspection = quarantine.inspect_local_metadata(
        payload["receipt_json"].encode("utf-8"),
        payload["reconciliation_json"].encode("utf-8"),
        original_run_id=payload["original_run_id"],
        manifest_fingerprint=payload["manifest_fingerprint"],
        receipt_sha256=payload["receipt_sha256"],
        reconciliation_sha256=payload["reconciliation_sha256"],
    ).to_dict()
    assert inspection["aggregate_coherence_checked"] is True
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    response = await api[0].put(path, json=payload)
    assert response.status_code == 409, response.text
    assert "no-store" in response.headers["cache-control"]
    assert (await api[0].get(path)).status_code == 404
    after = await counts(repo)
    assert after[t.external_qa_intakes.name] == after[t.external_qa_intake_audit.name] == 0


@pytest.mark.asyncio
async def test_stream_bound_before_buffering_and_duplicate_envelope_rejection(api, monkeypatch):
    repo, source, _ = await setup_intake(api, monkeypatch)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    seen = []

    async def too_large():
        for chunk in (b" " * 32_768, b"SENSITIVE_LIMIT_MARKER", b"MUST_NOT_READ"):
            seen.append(chunk)
            yield chunk

    response = await api[0].put(path, content=too_large(), headers={"content-type": "application/json"})
    assert response.status_code == 413 and len(seen) == 2
    assert "SENSITIVE_LIMIT_MARKER" not in response.text
    assert "no-store" in response.headers["cache-control"]
    payload = request_for(source, *declared_pair(source))
    raw = encode(payload)[:-1] + ',"confirmed":true}'
    response = await api[0].put(path, content=raw, headers={"content-type": "application/json"})
    assert response.status_code == 422
    payload["output"] = "SENSITIVE_NO_OUTPUT_ROUTE"
    response = await api[0].put(path, json=payload)
    assert response.status_code == 422 and "SENSITIVE_NO_OUTPUT_ROUTE" not in response.text
    assert (await counts(repo))[t.external_qa_intakes.name] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW, Permissions.EVALUATION_EXPORTS_READ, Permissions.EVALUATION_EXTERNAL_QA_CREATE])
async def test_create_requires_each_permission(api, monkeypatch, permission):
    _, source, _ = await setup_intake(api, monkeypatch)
    api[1].state.permissions.remove(permission)
    response = await api[0].put(api[2] + "/external-qa-intakes/" + uuid4().hex, json=request_for(source, *declared_pair(source)))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_project_human_and_read_permission_boundaries(api, monkeypatch):
    _, source, _ = await setup_intake(api, monkeypatch)
    client, app, base, _ = api
    path = base + "/external-qa-intakes/" + uuid4().hex
    payload = request_for(source, *declared_pair(source))
    created = await client.put(path, json=payload)
    assert created.status_code == 200
    app.state.permissions.remove(Permissions.EVALUATION_EXTERNAL_QA_READ)
    assert (await client.get(path)).status_code == (await client.get(path + "/audit")).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_EXTERNAL_QA_READ)
    app.state.permissions.remove(Permissions.EVALUATION_PROJECTS_READ)
    assert (await client.get(path)).status_code == (await client.get(path + "/audit")).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_READ)
    app.state.actor = 2
    for url in (path, path + "/audit"):
        assert (await client.get(url)).status_code == 404
    assert (await client.put(base + "/external-qa-intakes/" + uuid4().hex, json=payload)).status_code == 404
    app.state.actor = 1
    other = (await client.post("/api/evaluation/projects", json={"name": "Other synthetic project"})).json()
    assert (await client.put("/api/evaluation/projects/" + other["id"] + "/external-qa-intakes/" + uuid4().hex, json=payload)).status_code == 404
    app.state.internal = True
    assert (await client.get(path)).status_code == (await client.get(path + "/audit")).status_code == 403
    assert (await client.put(path, json=payload)).status_code == 403
    app.state.internal = False
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_skeleton_and_unknown_source_cannot_be_intaken(api, monkeypatch):
    repo, source, _ = await setup_intake(api, monkeypatch, tier="skeleton")
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    payload = request_for(source, *declared_pair(source))
    assert (await api[0].put(path, json=payload)).status_code == 409
    payload["export_id"] = uuid4().hex
    assert (await api[0].put(path, json=payload)).status_code == 404
    assert (await api[0].get(path)).status_code == 404
    assert (await counts(repo))[t.external_qa_intakes.name] == 0


@pytest.mark.asyncio
async def test_semantic_duplicates_rejected_but_new_untrusted_snapshot_preserves_history(api, monkeypatch):
    _, source, _ = await setup_intake(api, monkeypatch)
    pair = declared_pair(source)
    payload = request_for(source, *pair)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    first = await api[0].put(path, json=payload)
    assert first.status_code == 200
    for name in ("receipt", "reconciliation"):
        payload[name + "_json"] += "  "
        payload[name + "_sha256"] = sha(payload[name + "_json"])
    second_path = api[2] + "/external-qa-intakes/" + uuid4().hex
    assert (await api[0].put(second_path, json=payload)).status_code == 409
    assert (await api[0].get(second_path)).status_code == 404
    pair[1]["observation_kinds"]["output_collected"] = 0
    pair[1]["observation_kinds"]["http_error"] = 1
    second = await api[0].put(second_path, json=request_for(source, *pair))
    assert second.status_code == 200
    untrusted(second.json())
    assert first.json()["original_run_id"] == second.json()["original_run_id"]
    assert (await api[0].get(path)).json() == first.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("same_id", [True, False])
async def test_races_create_one_archive_and_one_atomic_audit(api, monkeypatch, same_id):
    repo, source, _ = await setup_intake(api, monkeypatch)
    payload = request_for(source, *declared_pair(source))
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    other = path if same_id else api[2] + "/external-qa-intakes/" + uuid4().hex
    results = await asyncio.gather(api[0].put(path, json=payload), api[0].put(other, json=payload))
    assert sorted(r.status_code for r in results) == [200, 409]
    after = await counts(repo)
    assert after[t.external_qa_intakes.name] == after[t.external_qa_intake_audit.name] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["source_read", "atomic_write", "metadata_read", "audit_read", "thread"])
async def test_repeated_cancellation_drains_then_get_same_id_only(api, monkeypatch, phase):
    repo, source, _ = await setup_intake(api, monkeypatch)
    payload = ExternalQAIntakeCreate.model_validate(request_for(source, *declared_pair(source)))
    intake_id = uuid4().hex
    project = source["project_id"]
    if phase in {"metadata_read", "audit_read"}:
        await repo.create(OWNER, project, intake_id, payload)
    entered, release = asyncio.Event(), asyncio.Event()
    thread_entered, thread_release = threading.Event(), threading.Event()
    name = {"source_read": "_source", "atomic_write": "_event", "metadata_read": "_row", "audit_read": "_row"}.get(phase)
    blocked = False
    if phase == "thread":
        original = quarantine._prepare

        def pause_thread(*args):
            result = original(*args)
            thread_entered.set()
            assert thread_release.wait(5)
            return result

        monkeypatch.setattr(quarantine, "_prepare", pause_thread)
    else:
        original = getattr(repo, name)

        async def pause(*args, **kwargs):
            nonlocal blocked
            result = await original(*args, **kwargs)
            if not blocked:
                blocked = True
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(repo, name, pause)
    operation = repo.get(OWNER, project, intake_id) if phase == "metadata_read" else repo.audit(OWNER, project, intake_id) if phase == "audit_read" else repo.create(OWNER, project, intake_id, payload)
    task = asyncio.create_task(operation)
    try:
        if phase == "thread":
            assert await asyncio.to_thread(thread_entered.wait, 5)
        else:
            await asyncio.wait_for(entered.wait(), 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
    finally:
        release.set()
        thread_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    receipt = await repo.get(OWNER, project, intake_id)
    assert receipt["id"] == intake_id
    response = await api[0].put(api[2] + "/external-qa-intakes/" + intake_id, json=payload.model_dump())
    assert response.status_code == 409
    assert len(await repo.audit(OWNER, project, intake_id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["project", "export", "plan"])
async def test_whole_source_snapshot_rechecked_under_final_lock(api, monkeypatch, mutation):
    repo, source, _ = await setup_intake(api, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = quarantine._prepare

    def pause(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(quarantine, "_prepare", pause)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    task = asyncio.create_task(api[0].put(path, json=request_for(source, *declared_pair(source))))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async with repo.sf.begin() as session:
            if mutation == "project":
                await session.execute(update(t.projects).values(name="Changed during preflight"))
            elif mutation == "export":
                await session.execute(update(t.exports).values(receipt_hash="0" * 64))
            else:
                await session.execute(update(t.plans).values(definition_hash="0" * 64))
    finally:
        release.set()
    assert (await task).status_code == 409
    assert (await counts(repo))[t.external_qa_intakes.name] == (await counts(repo))[t.external_qa_intake_audit.name] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["canonical_receipt", "canonical_reconciliation", "archive_hash", "request_hash", "snapshot_hash", "original_run_id", "source", "all_samples", "flag", "integer_flag", "raw_hash", "raw_length", "extra", "plan", "export"]
)
async def test_read_time_reinspection_rejects_corrupt_storage_privately(api, monkeypatch, change):
    repo, source, _ = await setup_intake(api, monkeypatch)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    response = await api[0].put(path, json=request_for(source, *declared_pair(source)))
    assert response.status_code == 200
    async with repo.sf.begin() as session:
        row = dict((await session.execute(select(t.external_qa_intakes))).mappings().one())
        if change in {"canonical_receipt", "canonical_reconciliation"}:
            await session.execute(update(t.external_qa_intakes).values(**{change: '{"secret":"SENSITIVE_STORED_MARKER"}'}))
        elif change in {"archive_hash", "request_hash", "snapshot_hash"}:
            await session.execute(update(t.external_qa_intakes).values(**{change: "0" * 64}))
        elif change == "original_run_id":
            await session.execute(update(t.external_qa_intakes).values(original_run_id=str(uuid4())))
        elif change == "plan":
            await session.execute(update(t.plans).values(definition_hash="0" * 64))
        elif change == "export":
            await session.execute(update(t.exports).values(receipt_hash="0" * 64))
        else:
            document = copy.deepcopy(row["document"])
            if change == "source":
                document["source"]["export_receipt"]["plan_hash"] = "0" * 64
            elif change == "all_samples":
                document["inspection"]["frozen_input_count"] = 0
            elif change == "flag":
                document["inspection"]["evidence_admitted"] = True
            elif change == "integer_flag":
                document["approval_granted"] = 0
            elif change == "raw_hash":
                document["inspection"]["declared_raw_sha256"]["receipt"] = "invalid"
            elif change == "raw_length":
                document["raw_document_bytes"]["receipt"] = True
            else:
                document["extra"] = "SENSITIVE_STORED_MARKER"
            await session.execute(update(t.external_qa_intakes).values(document=document))
    for suffix in ("", "/audit"):
        rejected = await api[0].get(path + suffix)
        assert rejected.status_code == 503, rejected.text
        assert "SENSITIVE_STORED_MARKER" not in rejected.text
        assert "no-store" in rejected.headers["cache-control"]


@pytest.mark.asyncio
async def test_atomic_rollback_and_unknown_committed_outcome_get_only(api, monkeypatch):
    repo, source, _ = await setup_intake(api, monkeypatch)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    payload = request_for(source, *declared_pair(source))
    original_event = repo._event

    async def fail_event(*args):
        await original_event(*args)
        raise SQLAlchemyError("SENSITIVE_DATABASE_MARKER")

    monkeypatch.setattr(repo, "_event", fail_event)
    response = await api[0].put(path, json=payload)
    assert response.status_code == 503 and "SENSITIVE_DATABASE_MARKER" not in response.text
    assert (await api[0].get(path)).status_code == 404
    assert (await counts(repo))[t.external_qa_intakes.name] == (await counts(repo))[t.external_qa_intake_audit.name] == 0
    monkeypatch.setattr(repo, "_event", original_event)
    # A NEW independently confirmed intent, not an automatic repeat of unknown PUT.
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    original_create = repo._create

    async def uncertain(*args):
        await original_create(*args)
        raise SQLAlchemyError("SENSITIVE_LOST_ACK")

    monkeypatch.setattr(repo, "_create", uncertain)
    response = await api[0].put(path, json=payload)
    assert response.status_code == 503 and "SENSITIVE_LOST_ACK" not in response.text
    reconciled = await api[0].get(path)
    assert reconciled.status_code == 200
    untrusted(reconciled.json())
    assert len((await api[0].get(path + "/audit")).json()["events"]) == 1
    monkeypatch.setattr(repo, "_create", original_create)
    assert (await api[0].put(path, json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_inspection_and_reinspection_are_off_loop(api, monkeypatch):
    _, source, _ = await setup_intake(api, monkeypatch)
    loop_thread, seen = threading.get_ident(), []
    original = quarantine.inspect_local_metadata

    def capture(*args, **kwargs):
        seen.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(quarantine, "inspect_local_metadata", capture)
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    assert (await api[0].put(path, json=request_for(source, *declared_pair(source)))).status_code == 200
    assert (await api[0].get(path)).status_code == 200
    assert len(seen) == 3 and all(value != loop_thread for value in seen)


@pytest.mark.asyncio
async def test_real_export_cli_receipt_reconciliation_to_quarantine(api, monkeypatch, tmp_path):
    _, source, _ = await setup_intake(api, monkeypatch)
    export_path = api[2] + "/exports/" + source["id"]
    downloaded = await api[0].get(open_url(export_path, source))
    assert downloaded.status_code == 200
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        for name in ("manifest.json", "inputs.json"):
            (tmp_path / name).write_bytes(archive.read(name))
    values = {"schema": "local-qa-values.v1", "bindings": {"DEVPILOT_REQUEST_URL": "https://example.test/local", "DEVPILOT_REQUEST_BODY": '{"q":""}', "DEVPILOT_REQUEST_HEADER_1": "SYNTHETIC_LOCAL_ONLY"}}
    (tmp_path / "values.json").write_text(json.dumps(values), encoding="utf-8")
    prepared = preflight(tmp_path / "manifest.json", tmp_path / "values.json", tmp_path / "inputs.json")
    sent, closed = mock_wire(monkeypatch, tmp_path / "results")
    result = await execute_local(prepared, tmp_path / "results", policy=LocalOutboundPolicy(("example.test",)), confirm_send=prepared.manifest.fingerprint, confirm_input_use=True, confirm_plaintext_output=True)
    assert len(sent) == len(closed) == 1
    receipt_bytes = (tmp_path / "results" / "run-receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    summary = await asyncio.to_thread(reconcile, tmp_path / "results" / "journal.sqlite", receipt["run_id"])
    payload = request_for(source, receipt, summary)
    payload["receipt_json"] = receipt_bytes.decode("utf-8")
    payload["receipt_sha256"] = sha(payload["receipt_json"])
    path = api[2] + "/external-qa-intakes/" + uuid4().hex
    response = await api[0].put(path, json=payload)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["original_run_id"] == result.definition.run_id
    assert document["inspection"]["observation_kinds"]["output_collected"] == 1
    assert document["source"]["export_receipt"]["manifest_fingerprint"] == prepared.manifest.fingerprint
    assert "Synthetic Q" not in response.text and "SYNTHETIC_LOCAL_ONLY" not in response.text
    untrusted(document)
    assert (await api[0].get(path)).json() == document


def test_create_dto_is_strict_and_hides_raw_documents():
    with pytest.raises(ValidationError):
        ExternalQAIntakeCreate.model_validate({"receipt_json": "SENSITIVE_RAW_DOCUMENT"})
