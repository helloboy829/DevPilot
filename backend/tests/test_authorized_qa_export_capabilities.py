"""Owner-only policy discovery is metadata, never execution/export authority."""

import copy

import pytest
from sqlalchemy import event
from test_authorized_qa_exports import OWNER, RECIPIENT, SOFTWARE, setup_export
from test_authorized_qa_exports import api as api

from app.evaluation.authorized_exports import ExportPolicy, ExportRepository
from app.gateway.authz import Permissions


@pytest.mark.asyncio
async def test_capabilities_scope_expiry_no_sensitive_reads_or_key(api, monkeypatch):
    client, app, base, _ = api
    repo, _, _, plan = await setup_export(api, monkeypatch)
    own = repo._policy.grants[0].model_dump()
    grants = [own]
    for field, value in [("owner_id", RECIPIENT), ("project_id", "other"), ("expires_at_ms", 10_000)]:
        other = {**own, field: value, "id": str(len(grants)) * 32}
        grants.append(other)
    policy = ExportPolicy(enabled=True, software_archive_sha256=SOFTWARE, grants=grants)
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=policy, clock_ms=lambda: 10_000)
    statements = []
    engine = repo.sf.kw["bind"]

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)
    try:
        response = await client.get(base + "/export-capabilities")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc == {
        "schema": "platform-qa-export-capabilities.v1",
        "project_id": plan["project_id"],
        "checked_at_ms": 10_000,
        "enabled": True,
        "software_archive_sha256": SOFTWARE,
        "max_response_bytes": 65_536,
        "max_total_response_bytes": 67_108_864,
        "grants": [own],
        "execution_authorized": False,
        "approval": False,
        "verdict": "NOT_EVALUATED",
    }
    assert "no-store" in response.headers["cache-control"]
    assert statements and all("evaluation_projects" in sql for sql in statements)
    assert not any(word in response.text for word in ("Synthetic Q", "SYNTHETIC_GOLD", "encrypted_bundle", "ciphertext"))
    assert own["owner_id"] == OWNER


@pytest.mark.asyncio
async def test_disabled_capabilities_hide_retained_grants_and_pin(api, monkeypatch):
    client, app, base, _ = api
    repo, _, _, _ = await setup_export(api, monkeypatch)
    policy = copy.deepcopy(repo._policy.model_dump())
    policy["enabled"] = False
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=policy, clock_ms=lambda: 10_000)
    response = await client.get(base + "/export-capabilities")
    assert response.status_code == 200
    assert response.json()["grants"] == []
    assert response.json()["software_archive_sha256"] is None
    assert response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_capabilities_human_owner_and_exact_read_permissions(api, monkeypatch):
    client, app, base, _ = api
    await setup_export(api, monkeypatch)
    original = list(app.state.permissions)
    for permission in (Permissions.EVALUATION_EXPORTS_READ, Permissions.EVALUATION_PROJECTS_READ):
        app.state.permissions = [p for p in original if p != permission]
        assert (await client.get(base + "/export-capabilities")).status_code == 403
    app.state.permissions = original
    app.state.internal = True
    assert (await client.get(base + "/export-capabilities")).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(base + "/export-capabilities")).status_code == 404
    app.state.actor = 0
    assert (await client.get(base + "/export-capabilities")).status_code == 401


@pytest.mark.asyncio
async def test_download_pins_exporter_and_viewed_receipt(api, monkeypatch):
    client, _, _, _ = api
    _, path, payload, _ = await setup_export(api, monkeypatch)
    receipt = (await client.put(path, json=payload)).json()
    response = await client.get(path + "/bundle", params={"viewed_receipt_hash": receipt["receipt_hash"], "confirm_download": "true"})
    assert response.status_code == 200
    assert response.headers["x-devpilot-exporter"] == "platform-local-qa-config.v1"
    assert response.headers["x-devpilot-receipt-hash"] == receipt["receipt_hash"]
    assert len(response.content) == receipt["bundle_bytes"]


@pytest.mark.asyncio
async def test_capability_read_drains_repeated_cancellation_before_session_release(api, monkeypatch):
    import asyncio

    _, _, base, _ = api
    repo, _, _, _ = await setup_export(api, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    original = repo._project

    async def pause(*args):
        result = await original(*args)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(repo, "_project", pause)
    task = asyncio.create_task(repo.capabilities(OWNER, base.rsplit("/", 1)[1]))
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
    assert (await repo.capabilities(OWNER, base.rsplit("/", 1)[1]))["enabled"] is True


@pytest.mark.asyncio
async def test_api_generated_browser_bundle_and_stored_fixture_contract(api, monkeypatch):
    import base64
    import hashlib
    import io
    import json
    import os
    import zipfile
    from pathlib import Path

    from app.evaluation.authorized_exports import ExportCreate, ExportReceipt
    from app.evaluation.registry import fingerprint

    client, app, base, _ = api
    repo, path, payload, plan = await setup_export(api, monkeypatch)
    policy = repo._policy.model_dump()
    policy["grants"][0]["expires_at_ms"] = 253_000_000_000_000
    app.state.evaluation_export_repo = ExportRepository(repo.sf, policy=policy, protection=repo._export_protection, clock_ms=lambda: 10_000)
    receipt = (await client.put(path, json=payload)).json()
    bundle = await client.get(path + "/bundle", params={"viewed_receipt_hash": receipt["receipt_hash"], "confirm_download": "true"})
    assert bundle.status_code == 200
    fixture = {"receipt": receipt, "plan": plan, "request": payload, "capabilities": (await client.get(base + "/export-capabilities")).json(), "bundle_base64": base64.b64encode(bundle.content).decode("ascii")}
    fixture_path = Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/synthetic-authorized-export.json"
    fixtures = [fixture]
    if fixture_path.is_file():
        fixtures.append(json.loads(fixture_path.read_text(encoding="utf-8")))
    for item in fixtures:
        r = dict(item["receipt"])
        receipt_hash = r.pop("receipt_hash")
        assert ExportReceipt.model_validate(r).model_dump(by_alias=True) == r
        request_hash = fingerprint(ExportCreate.model_validate(item["request"]).model_dump())
        assert receipt_hash == fingerprint({"owner_id": r["grant"]["owner_id"], "request_hash": request_hash, "document": r})
        data = base64.b64decode(item["bundle_base64"], validate=True)
        assert len(data) == r["bundle_bytes"]
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert sorted(archive.namelist()) == ["README.en.md", "README.zh.md", "export.json", "inputs.json", "manifest.json", "values.example.json"]
            package = json.loads(archive.read("export.json"))
            assert package["export_id"] == r["id"] and package["plan_hash"] == r["plan_hash"]
            assert package["manifest_fingerprint"] == r["manifest_fingerprint"]
            assert package["all_frozen_samples"] == r["all_frozen_samples"]
            for name, want in package["files"].items():
                assert hashlib.sha256(archive.read(name)).hexdigest() == want
    destination = os.getenv("TEST_EXPORT_BROWSER_FIXTURE")
    if destination:
        assert destination == "/tmp/export-ui-generated-fixture.json"
        Path(destination).write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
