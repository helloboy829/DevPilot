"""Synthetic authorized export API -> immutable encrypted receipt -> real local CLI."""

import asyncio
import copy
import hashlib
import io
import json
import socket
import threading
import zipfile
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from devpilot.local_qa_cli import LocalOutboundPolicy, execute_local, preflight
from devpilot.local_qa_reconcile import reconcile
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from test_evaluation_plans_router import setup_plan
from test_evaluation_registry_router import api as api
from test_local_qa_cli import mock_wire

from app.evaluation import authorized_exports as exports
from app.evaluation import tables as t
from app.evaluation.authorized_exports import ExportCreate, ExportPolicy, ExportProtection, ExportRepository
from app.evaluation.repository import Conflict
from app.evaluation.request_protection import RequestProtectionError
from app.gateway.authz import Permissions
from app.gateway.routers import evaluation_exports

OWNER = str(UUID(int=1))
RECIPIENT = str(UUID(int=3))
SOFTWARE = "a" * 64


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


async def setup_export(api, monkeypatch, *, tier="baseline_inputs"):
    client, app, base, _ = api
    path, payload = await setup_plan(api, monkeypatch)
    response = await client.post(path, json=payload)
    assert response.status_code == 200
    plan = response.json()
    grant = {
        "id": uuid4().hex,
        "owner_id": OWNER,
        "project_id": base.rsplit("/", 1)[1],
        "plan_id": plan["id"],
        "plan_hash": plan["definition_hash"],
        "recipient_id": RECIPIENT,
        "tier": tier,
        "expires_at_ms": 1_000_000,
        "target_origin": "https://example.test:443",
        "off_platform_authorized": True,
    }
    policy = ExportPolicy(enabled=True, software_archive_sha256=SOFTWARE, grants=[grant])
    repo = ExportRepository(app.state.evaluation_repo.sf, policy=policy, protection=ExportProtection(Fernet.generate_key()), clock_ms=lambda: 10_000)
    app.state.evaluation_export_repo = repo
    app.include_router(evaluation_exports.router)
    app.state.permissions.extend([Permissions.EVALUATION_EXPORTS_READ, Permissions.EVALUATION_EXPORTS_CREATE, Permissions.EVALUATION_EXPORTS_DOWNLOAD])
    request = {
        "plan_id": plan["id"],
        "plan_hash": plan["definition_hash"],
        "grant_id": grant["id"],
        "recipient_id": RECIPIENT,
        "tier": tier,
        "confirmed": True,
        "data_use_confirmed": True,
        "external_controls_acknowledged": True,
    }
    return repo, base + "/exports/" + uuid4().hex, request, plan


def open_url(path, receipt):
    return path + "/bundle?viewed_receipt_hash=" + receipt["receipt_hash"] + "&confirm_download=true"


@pytest.mark.asyncio
async def test_http_export_real_local_cli_and_original_id(api, monkeypatch, tmp_path):
    client, _, _, _ = api
    repo, path, payload, plan = await setup_export(api, monkeypatch)
    created = await client.put(path, json=payload)
    assert created.status_code == 200, created.text
    receipt = created.json()
    assert receipt["scope"] == "authorized_external_configuration_only"
    assert receipt["verdict"] == "NOT_EVALUATED"
    assert receipt["plan_hash"] == plan["definition_hash"]
    assert receipt["all_frozen_samples"] == 1
    assert "SYNTHETIC" not in created.text and "Synthetic Q" not in created.text
    downloaded = await client.get(open_url(path, receipt))
    assert downloaded.status_code == 200, downloaded.text
    assert "no-store" in downloaded.headers["cache-control"]
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        names = set(archive.namelist())
        assert names == {"export.json", "manifest.json", "values.example.json", "inputs.json", "README.zh.md", "README.en.md"}
        raw = {name: archive.read(name) for name in names}
    contents = b"".join(raw.values())
    assert b"Synthetic Q" in contents
    for forbidden in (b"SYNTHETIC_GOLD", b"SYNTHETIC_SECRET", b"SYNTHETIC_PATH", b"SYNTHETIC_BODY", b"SYNTHETIC_QUERY", b"authorization_basis", b"source_ref"):
        assert forbidden not in contents
    package = json.loads(raw["export.json"])
    assert package["software_archive_sha256"] == SOFTWARE
    assert package["export_id"] == path.rsplit("/", 1)[1]
    for name, digest in package["files"].items():
        assert hashlib.sha256(raw[name]).hexdigest() == digest
    for name, data in raw.items():
        (tmp_path / name).write_bytes(data)
    values = {"schema": "local-qa-values.v1", "bindings": {"DEVPILOT_REQUEST_URL": "https://example.test/local", "DEVPILOT_REQUEST_BODY": '{"q":""}', "DEVPILOT_REQUEST_HEADER_1": "SYNTHETIC_LOCAL_ONLY"}}
    (tmp_path / "values.json").write_text(json.dumps(values), encoding="utf-8")
    prepared = preflight(tmp_path / "manifest.json", tmp_path / "values.json", tmp_path / "inputs.json")
    assert prepared.inputs == ("Synthetic Q",)
    sent, closed = mock_wire(monkeypatch, tmp_path / "results")
    snapshot = await execute_local(prepared, tmp_path / "results", policy=LocalOutboundPolicy(("example.test",)), confirm_send=prepared.manifest.fingerprint, confirm_input_use=True, confirm_plaintext_output=True)
    assert len(sent) == len(closed) == 1
    assert json.loads(sent[0].content) == {"q": "Synthetic Q"}
    assert snapshot.state == "collected"
    local_receipt = json.loads((tmp_path / "results" / "run-receipt.json").read_bytes())
    assert local_receipt["run_id"] == snapshot.definition.run_id
    checked = await asyncio.to_thread(reconcile, tmp_path / "results" / "journal.sqlite", local_receipt["run_id"])
    assert checked["verdict"] == "NOT_EVALUATED"
    assert checked["frozen_input_count"] == checked["reserved_attempt_count"] == 1
    assert checked["platform_provenance_verified"] is False
    assert checked["resend_permitted"] is False
    assert (await client.get(path)).json() == receipt
    assert (await client.get(open_url(path, receipt))).content == downloaded.content
    events = await repo.audit(OWNER, receipt["project_id"], receipt["id"])
    assert [e["action"] for e in events] == ["export_created", "bundle_opened", "bundle_opened"]


@pytest.mark.asyncio
async def test_skeleton_is_explicitly_incomplete_and_never_reads_sensitive_tables(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch, tier="skeleton")
    statements = []
    engine = repo.sf.kw["bind"]

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await client.put(path, json=payload)
        assert response.status_code == 200, response.text
        downloaded = await client.get(open_url(path, response.json()))
        assert downloaded.status_code == 200
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    selects = [s for s in statements if s.lstrip().startswith("select")]
    assert not any("evaluation_samples" in s or "evaluation_references" in s or "encrypted_payload" in s for s in selects)
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert json.loads(archive.read("inputs.json")) == {"schema": "local-qa-inputs.v1", "inputs": []}
        assert json.loads(archive.read("export.json"))["ready_for_preflight"] is False
        assert b"INCOMPLETE" in archive.read("README.en.md")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("confirmed", 1), ("data_use_confirmed", False), ("external_controls_acknowledged", "true"), ("recipient_id", "invalid"), ("tier", "references"), ("plan_hash", "bad"), ("extra", "SYNTHETIC_PRIVATE")]
)
async def test_strict_private_http_contract(api, monkeypatch, field, value):
    client, _, _, _ = api
    _, path, payload, _ = await setup_export(api, monkeypatch)
    response = await client.put(path, json={**payload, field: value})
    assert response.status_code == 422
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert (await client.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_no_blanket_review_permission_no_agent_no_cross_owner(api, monkeypatch):
    client, app, _, _ = api
    _, path, payload, _ = await setup_export(api, monkeypatch)
    saved = list(app.state.permissions)
    app.state.permissions = [p for p in saved if not p.startswith("evaluation_exports:")]
    assert (await client.put(path, json=payload)).status_code == 403
    app.state.permissions = saved
    app.state.internal = True
    assert (await client.put(path, json=payload)).status_code == 403
    app.state.internal = False
    created = await client.put(path, json=payload)
    assert created.status_code == 200
    app.state.internal = True
    assert (await client.get(path)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(path)).status_code == 404
    assert (await client.get(open_url(path, created.json()))).status_code == 404
    app.state.actor = 0
    assert (await client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_immutable_put_requires_same_id_get_and_never_resends(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    first = await client.put(path, json=payload)
    assert first.status_code == 200
    assert (await client.put(path, json=payload)).status_code == 409
    assert (await client.put(path, json={**payload, "recipient_id": str(UUID(int=4))})).status_code == 409
    assert (await client.get(path)).json() == first.json()
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.exports)) == 1
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 1


@pytest.mark.asyncio
async def test_default_disabled_expiry_revocation_and_metadata_reconciliation(api, monkeypatch):
    client, app, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    original = app.state.evaluation_export_repo
    app.state.evaluation_export_repo = ExportRepository(repo.sf, clock_ms=lambda: 10_000)
    assert (await client.put(path, json=payload)).status_code == 503
    app.state.evaluation_export_repo = original
    response = await client.put(path, json=payload)
    assert response.status_code == 200
    repo.clock_ms = lambda: 1_000_000
    assert (await client.get(open_url(path, response.json()))).status_code == 503
    assert (await client.get(path)).json() == response.json()
    app.state.evaluation_export_repo = ExportRepository(repo.sf)
    assert (await client.get(path)).json() == response.json()
    assert (await client.get(open_url(path, response.json()))).status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["recipient", "grant", "hash", "acceptance", "samples", "request", "budget"])
async def test_export_grant_and_source_coherence_fail_closed(api, monkeypatch, mutation):
    client, _, _, dataset = api
    repo, path, payload, plan = await setup_export(api, monkeypatch)
    async with repo.sf.begin() as session:
        if mutation == "recipient":
            payload["recipient_id"] = str(UUID(int=4))
        elif mutation == "grant":
            payload["grant_id"] = uuid4().hex
        elif mutation == "hash":
            payload["plan_hash"] = "b" * 64
        elif mutation == "acceptance":
            await session.execute(update(t.datasets).where(t.datasets.c.id == dataset["id"]).values(purpose="acceptance"))
        elif mutation == "samples":
            await session.execute(update(t.samples).values(input="TAMPERED_SYNTHETIC"))
        elif mutation == "request":
            await session.execute(update(t.request_versions).values(protected_hash="b" * 64))
        else:
            definition = copy.deepcopy(plan["definition"])
            definition["limits"]["wall_time_ms"] = 100
            await session.execute(update(t.plans).values(definition=definition))
    response = await client.put(path, json=payload)
    assert response.status_code in {409, 503}
    assert (await client.get(path)).status_code == 404
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.exports)) == 0
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 0


@pytest.mark.asyncio
async def test_encrypted_retention_metadata_no_ciphertext_and_viewed_receipt_fence(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    created = await client.put(path, json=payload)
    receipt = created.json()
    async with repo.sf() as session:
        row = (await session.execute(select(t.exports))).mappings().one()
        assert "Synthetic Q" not in str(dict(row)) and "SYNTHETIC_GOLD" not in str(dict(row))
        assert row["encrypted_bundle"] not in created.text
    for suffix in ("/bundle", "/bundle?viewed_receipt_hash=" + "f" * 64 + "&confirm_download=true", "/bundle?viewed_receipt_hash=" + receipt["receipt_hash"]):
        assert (await client.get(path + suffix)).status_code in {409, 422}
    async with repo.sf.begin() as session:
        await session.execute(update(t.exports).values(encrypted_bundle="corrupt"))
    rejected = await client.get(open_url(path, receipt))
    assert rejected.status_code == 503
    assert "Synthetic Q" not in rejected.text


@pytest.mark.asyncio
async def test_crypto_bundle_build_off_loop_and_final_snapshot_recheck(api, monkeypatch):
    import app.evaluation.authorized_exports as exports

    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    loop_thread = threading.get_ident()
    seen = []
    original = exports._build_bundle

    def build(*args, **kwargs):
        seen.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(exports, "_build_bundle", build)
    response = await client.put(path, json=payload)
    assert response.status_code == 200
    assert seen and all(thread != loop_thread for thread in seen)


@pytest.mark.parametrize("change", [{"enabled": 1}, {"enabled": True}, {"software_archive_sha256": "bad"}, {"max_response_bytes": True}, {"max_response_bytes": 1_048_577}, {"grants": [{}]}, {"allow_gold": True}])
def test_policy_is_strict_default_off_and_requires_exact_grants(change):
    with pytest.raises(ValidationError):
        ExportPolicy.model_validate(change)
    assert ExportPolicy().enabled is False


def test_create_dto_and_policy_do_not_grant_execution():
    assert ExportPolicy().grants == []
    with pytest.raises(ValidationError):
        ExportCreate.model_validate({})


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["source_read", "atomic_write", "metadata_read", "download_write"])
async def test_repeated_cancellation_drains_read_write_then_same_id_get(api, monkeypatch, phase):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    project, export_id = path.split("/")[-3], path.split("/")[-1]
    dto = ExportCreate.model_validate(payload)
    receipt = None
    if phase in {"metadata_read", "download_write"}:
        receipt = await repo.create(OWNER, project, export_id, dto)
    entered, release = asyncio.Event(), asyncio.Event()
    name = {"source_read": "_snapshot", "atomic_write": "_event", "metadata_read": "_row", "download_write": "_event"}[phase]
    original = getattr(repo, name)
    blocked = False

    async def pause(*args, **kwargs):
        nonlocal blocked
        result = await original(*args, **kwargs)
        if not blocked:
            blocked = True
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(repo, name, pause)
    if phase == "metadata_read":
        operation = repo.get(OWNER, project, export_id)
    elif phase == "download_write":
        operation = repo.open_bundle(OWNER, project, export_id, receipt["receipt_hash"])
    else:
        operation = repo.create(OWNER, project, export_id, dto)
    task = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    reconciled = await repo.get(OWNER, project, export_id)
    assert reconciled["id"] == export_id
    assert (await client.put(path, json=payload)).status_code == 409
    events = await repo.audit(OWNER, project, export_id)
    assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
    assert [e["action"] for e in events] == (["export_created", "bundle_opened"] if phase == "download_write" else ["export_created"])


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["project", "input", "grant_expiry"])
async def test_source_and_grant_change_between_preflight_and_final_lock(api, monkeypatch, mutation):
    client, _, _, _ = api
    repo, path, payload, plan = await setup_export(api, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = exports._build_bundle

    def pause(*args):
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(exports, "_build_bundle", pause)
    task = asyncio.create_task(client.put(path, json=payload))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        if mutation == "grant_expiry":
            repo.clock_ms = lambda: 1_000_000
        else:
            async with repo.sf.begin() as session:
                if mutation == "project":
                    await session.execute(update(t.projects).values(name="Changed after preflight"))
                else:
                    await session.execute(update(t.samples).values(input="Changed after preflight"))
    finally:
        release.set()
    response = await task
    assert response.status_code == (503 if mutation == "grant_expiry" else 409), response.text
    assert (await client.get(path)).status_code == 404
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 0


@pytest.mark.asyncio
async def test_simultaneous_same_id_writes_have_one_immutable_receipt_and_audit(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    responses = await asyncio.gather(*(client.put(path, json=payload) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    receipt = next(r.json() for r in responses if r.status_code == 200)
    assert (await client.get(path)).json() == receipt
    assert len(await repo.audit(OWNER, receipt["project_id"], receipt["id"])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["create", "download"])
async def test_audit_failure_rolls_back_write_and_never_releases_zip(api, monkeypatch, action):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json() if action == "download" else None
    original = repo._event

    async def fail_after_insert(*args):
        await original(*args)
        raise SQLAlchemyError("SYNTHETIC_PRIVATE_DATABASE_DETAIL")

    monkeypatch.setattr(repo, "_event", fail_after_insert)
    response = await client.get(open_url(path, receipt)) if receipt else await client.put(path, json=payload)
    assert response.status_code == 503
    assert "SYNTHETIC_PRIVATE" not in response.text and not response.content.startswith(b"PK")
    assert "no-store" in response.headers["cache-control"]
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.exports)) == (1 if receipt else 0)
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == (1 if receipt else 0)


@pytest.mark.asyncio
async def test_bounded_stream_and_private_permission_failures_before_source_reads(api, monkeypatch):
    client, app, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    reads = []
    original = repo._snapshot

    async def capture(*args):
        reads.append(True)
        return await original(*args)

    monkeypatch.setattr(repo, "_snapshot", capture)
    streamed = []

    async def body():
        for chunk in (b"x" * 10_000, b"x" * 10_000, b"SHOULD_NOT_BE_BUFFERED"):
            streamed.append(chunk)
            yield chunk

    response = await client.put(path, content=body(), headers={"content-type": "application/json"})
    assert response.status_code == 413 and len(streamed) == 2 and not reads
    assert "no-store" in response.headers["cache-control"]
    for permission in (Permissions.EVALUATION_PROJECTS_WRITE, Permissions.EVALUATION_PROJECTS_REVIEW, Permissions.EVALUATION_EXPORTS_CREATE):
        saved = app.state.permissions
        app.state.permissions = [p for p in saved if p != permission]
        response = await client.put(path, json=payload)
        assert response.status_code == 403 and "no-store" in response.headers["cache-control"]
        app.state.permissions = saved
    assert not reads


@pytest.mark.asyncio
async def test_metadata_sql_never_selects_ciphertext_inputs_or_reference_answers(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    created = await client.put(path, json=payload)
    assert created.status_code == 200
    statements = []
    engine = repo.sf.kw["bind"]

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        assert (await client.get(path)).status_code == 200
        assert (await client.get(path + "/audit")).status_code == 200
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert statements
    assert not any(word in sql for sql in statements for word in ("encrypted_bundle", "encrypted_payload", "evaluation_samples", "evaluation_references"))


@pytest.mark.asyncio
async def test_historical_bundle_does_not_rerender_changed_source_or_policy(api, monkeypatch):
    client, app, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json()
    first = await client.get(open_url(path, receipt))
    assert first.status_code == 200
    async with repo.sf.begin() as session:
        await session.execute(update(t.samples).values(input="MUST_NOT_REWRITE_HISTORY"))
        await session.execute(update(t.projects).values(name="Renamed project"))
    assert (await client.get(open_url(path, receipt))).content == first.content
    policy = repo._policy.model_copy(deep=True)
    policy.max_response_bytes += 1
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=policy, protection=repo._export_protection, clock_ms=repo.clock_ms)
    assert (await client.get(open_url(path, receipt))).status_code == 503
    assert (await client.get(path)).json() == receipt


@pytest.mark.parametrize("field", ["owner_id", "project_id", "export_id", "plan_hash", "grant_hash"])
def test_protection_rejects_context_transplants_and_does_not_echo(field):
    key = Fernet.generate_key()
    protection = ExportProtection(key)
    context = {name: "a" * 32 for name in ("owner_id", "project_id", "export_id", "plan_hash", "grant_hash")}
    token = protection.seal(b"SYNTHETIC_PRIVATE_PACKAGE", context)
    assert protection.open(token, context) == b"SYNTHETIC_PRIVATE_PACKAGE"
    with pytest.raises(RequestProtectionError) as error:
        protection.open(token, {**context, field: "b" * 32})
    assert "SYNTHETIC" not in str(error.value) and error.value.__context__ is None
    with pytest.raises(RequestProtectionError):
        ExportProtection(Fernet.generate_key()).open(token, context)
    forged = Fernet(key).encrypt(json.dumps({"schema": "protected-request.v1", "binding": context, "bundle_sha256": "a" * 64, "bundle_hex": "ab"}).encode()).decode()
    with pytest.raises(RequestProtectionError):
        protection.open(forged, context)


@pytest.mark.asyncio
async def test_grant_origin_offplatform_consent_and_policy_copy_are_explicit(api, monkeypatch):
    client, app, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    policy = repo._policy.model_dump()
    frozen = ExportRepository(repo.sf, policy=policy, protection=repo._export_protection, clock_ms=repo.clock_ms)
    policy["grants"][0]["tier"] = "skeleton"
    app.state.evaluation_export_repo = frozen
    assert (await client.put(path, json=payload)).status_code == 200
    for change in ({"off_platform_authorized": 1}, {"off_platform_authorized": False}, {"target_origin": "https://example.test/path"}, {"target_origin": "https://example.test"}):
        invalid = frozen._policy.model_dump()
        invalid["grants"][0].update(change)
        with pytest.raises(ValidationError):
            ExportPolicy.model_validate(invalid)
    mismatched = frozen._policy.model_dump()
    mismatched["grants"][0]["target_origin"] = "https://other.test:443"
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=mismatched, protection=repo._export_protection, clock_ms=repo.clock_ms)
    new_path = path.rsplit("/", 1)[0] + "/" + uuid4().hex
    assert (await client.put(new_path, json=payload)).status_code == 409


@pytest.mark.asyncio
async def test_audit_explicit_cursor_keeps_equal_timestamp_order_and_bounded_pages(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json()
    for _ in range(3):
        assert (await client.get(open_url(path, receipt))).status_code == 200
    page = (await client.get(path + "/audit?limit=2")).json()
    assert [e["sequence"] for e in page["events"]] == [1, 2]
    assert page["next_after_sequence"] == 2
    page = (await client.get(path + "/audit?limit=2&after_sequence=2")).json()
    assert [e["sequence"] for e in page["events"]] == [3, 4]
    assert len({e["at_ms"] for e in page["events"]}) == 1
    assert (await client.get(path + "/audit?limit=2&after_sequence=4")).json() == {"events": [], "next_after_sequence": None}
    for query in ("limit=0", "limit=201", "after_sequence=-1", "after_sequence=2147483648"):
        assert (await client.get(path + "/audit?" + query)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("encrypted_bundle", "invalid"), ("encrypted_bundle", "\u2603"), ("document", {}), ("receipt_hash", "0" * 64)])
async def test_corruption_fails_private_without_zip_or_new_audit(api, monkeypatch, field, value):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json()
    async with repo.sf.begin() as session:
        await session.execute(update(t.exports).values(**{field: value}))
    response = await client.get(open_url(path, receipt))
    assert response.status_code == 503 and not response.content.startswith(b"PK")
    assert "no-store" in response.headers["cache-control"]
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 1


@pytest.mark.asyncio
async def test_download_grant_expiring_during_crypto_does_not_release_body_or_audit(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json()
    entered, release = threading.Event(), threading.Event()
    original = repo._export_protection.open

    def pause(*args):
        bundle = original(*args)
        entered.set()
        assert release.wait(5)
        return bundle

    monkeypatch.setattr(repo._export_protection, "open", pause)
    task = asyncio.create_task(client.get(open_url(path, receipt)))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        repo.clock_ms = lambda: 1_000_000
    finally:
        release.set()
    assert (await task).status_code == 503
    assert len(await repo.audit(OWNER, receipt["project_id"], receipt["id"])) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["acceptance", "http", "performance", "count", "duration", "response_budget", "input_hash", "size"])
async def test_bundle_rejects_unsupported_or_incoherent_sources_and_limits(api, monkeypatch, mutation):
    from devpilot.request_templates import RequestTemplate

    _, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    dto = ExportCreate.model_validate(payload)
    project, export_id = path.split("/")[-3], path.split("/")[-1]
    async with repo.sf() as session:
        snapshot = await repo._snapshot(session, OWNER, project, dto)
    snapshot = copy.deepcopy(snapshot)
    grant = repo._grant(OWNER, project, dto)
    policy = repo._policy.model_copy(deep=True)
    definition = snapshot["plan"]["definition"]
    if mutation == "acceptance":
        snapshot["dataset"]["purpose"] = definition["dataset_purpose"] = "acceptance"
    elif mutation == "http":
        template = RequestTemplate("POST", "http://example.test:80", ("Authorization",))
        snapshot["version"]["request_template"] = template.to_dict()
        definition["request_template_fingerprint"] = template.fingerprint
        grant.target_origin = template.origin
    elif mutation == "performance":
        definition["limits"]["mode"] = "performance"
    elif mutation == "count":
        snapshot["dataset"]["sample_count"] = definition["preflight"]["sample_count"] = 501
        # Skeleton still rejects unsupported count, without reading input tables.
        dto.tier = grant.tier = "skeleton"
    elif mutation == "duration":
        definition["limits"]["wall_time_ms"] = 999
    elif mutation == "response_budget":
        policy.max_total_response_bytes = 2
    elif mutation == "input_hash":
        snapshot["samples"][0]["input"] = "Corrupted input"
    else:
        monkeypatch.setattr(exports, "MAX_BUNDLE_BYTES", 32)
    with pytest.raises(Conflict):
        await asyncio.to_thread(exports._build_bundle, snapshot, dto, export_id, grant, policy)


@pytest.mark.asyncio
@pytest.mark.parametrize("template", [{}, {"schema": "request-template.v1", "origin": "SYNTHETIC_PRIVATE_CORRUPTION"}])
async def test_corrupt_request_metadata_rejected_without_private_exception_or_write(api, monkeypatch, template):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    async with repo.sf.begin() as session:
        await session.execute(update(t.request_versions).values(request_template=template))
    response = await client.put(path, json=payload)
    assert response.status_code == 409
    assert "SYNTHETIC_PRIVATE_CORRUPTION" not in response.text
    assert "no-store" in response.headers["cache-control"]
    assert (await client.get(path)).status_code == 404
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.exports)) == 0
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 0


@pytest.mark.asyncio
async def test_expiry_between_grant_check_and_receipt_timestamp_is_private(api, monkeypatch):
    client, _, _, _ = api
    repo, path, payload, _ = await setup_export(api, monkeypatch)
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return 10_000 if calls < 3 else 1_000_000

    repo.clock_ms = clock
    response = await client.put(path, json=payload)
    assert response.status_code == 503
    assert "Synthetic Q" not in response.text
    assert (await client.get(path)).status_code == 404
    async with repo.sf() as session:
        assert await session.scalar(select(func.count()).select_from(t.exports)) == 0
        assert await session.scalar(select(func.count()).select_from(t.export_audit)) == 0
