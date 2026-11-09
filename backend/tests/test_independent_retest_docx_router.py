"""Human-owner, no-store, historical independent retest Word export HTTP contract."""

import io
import threading
import zipfile
from uuid import uuid4

import pytest
from sqlalchemy import update
from test_evaluation_registry_router import api as api
from test_qa_independent_archives_router import setup_archive
from test_qa_report_docx_router import saved_archive as legacy_archive

from app.evaluation import tables as t
from app.evaluation.independent_retest_docx import RENDERER_ID
from app.evaluation.qa_independent_archives import IndependentRetestRepository
from app.evaluation.report_docx import DOCX_MIME, ReportExportError
from app.gateway.authz import Permissions


async def saved_archive(api, monkeypatch):
    payload = await setup_archive(api, monkeypatch, pair=True)
    path = api[2] + "/independent-retest-archives/" + uuid4().hex
    response = await api[0].put(path, json=payload)
    assert response.status_code == 200, response.text
    doc = response.json()
    return path, doc, path + "/exports/" + RENDERER_ID + "?archive_hash=" + doc["archive_hash"]


@pytest.mark.asyncio
async def test_off_loop_frozen_only_no_current_sources_keys_or_templates(api, monkeypatch):
    client, app, _, _ = api
    path, doc, url = await saved_archive(api, monkeypatch)
    from app.gateway.routers import evaluation_projects as routes

    thread, render = threading.get_ident(), routes.render_independent_retest_docx
    decode = IndependentRetestRepository._decode

    def off_loop_decode(row):
        assert threading.get_ident() != thread
        return decode(row)

    def off_loop_render(value):
        assert threading.get_ident() != thread and value == doc
        return render(value)

    def forbidden(*args, **kwargs):
        raise AssertionError("Must not open current tasks, evidence, templates or assessments")

    monkeypatch.setattr(IndependentRetestRepository, "_decode", staticmethod(off_loop_decode))
    monkeypatch.setattr(IndependentRetestRepository, "_source_snapshot", forbidden)
    monkeypatch.setattr(routes, "render_independent_retest_docx", off_loop_render)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    response = await client.get(url)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == DOCX_MIME
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-devpilot-renderer"] == RENDERER_ID
    assert response.headers["content-disposition"] == f'attachment; filename="independent-retest-{doc["id"]}.docx"'
    assert (await client.get(url)).content == response.content
    assert (await client.get(path)).json() == doc
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        xml = package.read("word/document.xml").decode()
    assert doc["archive_hash"] in xml and doc["baseline"]["assessment_ref"]["assessment_id"] in xml
    assert all(s not in xml for s in ["SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "SYNTHETIC_INDEPENDENT_NOTE", "encrypted_payload"])


@pytest.mark.asyncio
async def test_get_only_pinned_human_owner_permissions_receipt_and_namespace(api, monkeypatch):
    client, app, base, _ = api
    path, doc, url = await saved_archive(api, monkeypatch)
    for suffix in ("", "?archive_hash=bad"):
        assert (await client.get(url.split("?")[0] + suffix)).status_code == 422
    assert (await client.get(url.replace(doc["archive_hash"], "0" * 64))).status_code == 409
    assert (await client.get(url.replace(RENDERER_ID, "qa-docx-v1"))).status_code == 404
    assert (await client.get(url.replace(RENDERER_ID, "independent-retest-docx-v2"))).status_code == 404
    assert (await client.post(url, json={"markdown": "UNTRUSTED"})).status_code == 405
    assert (await client.get(base + "/report-archives/" + doc["id"] + "/exports/qa-docx-v1?archive_hash=" + doc["archive_hash"])).status_code == 404
    assert (await client.get(url.replace(doc["id"], "invalid"))).status_code == 422
    for permissions in ([Permissions.EVALUATION_PROJECTS_READ], [Permissions.EVALUATION_PROJECTS_REVIEW], [Permissions.EVALUATION_PROJECTS_WRITE]):
        app.state.permissions = permissions
        assert (await client.get(url)).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(url)).status_code == 200
    app.state.internal = True
    assert (await client.get(url)).status_code == 403
    app.state.internal = False
    for actor, status in ((2, 404), (0, 401)):
        app.state.actor = actor
        assert (await client.get(url)).status_code == status


@pytest.mark.asyncio
async def test_integrity_and_renderer_errors_generic_no_attachment_or_retries(api, monkeypatch):
    client, app, _, _ = api
    _, doc, url = await saved_archive(api, monkeypatch)
    async with app.state.evaluation_repo.sf.begin() as session:
        await session.execute(update(t.independent_retest_archives).where(t.independent_retest_archives.c.id == doc["id"]).values(archive_hash="0" * 64))
    response = await client.get(url)
    assert response.status_code == 503 and "no-store" in response.headers["cache-control"]
    assert "content-disposition" not in response.headers
    async with app.state.evaluation_repo.sf.begin() as session:
        await session.execute(update(t.independent_retest_archives).where(t.independent_retest_archives.c.id == doc["id"]).values(archive_hash=doc["archive_hash"]))
    from app.gateway.routers import evaluation_projects as routes

    calls = []

    def failed(value):
        calls.append(value["id"])
        raise ReportExportError("SYNTHETIC_PRIVATE_ERROR")

    monkeypatch.setattr(routes, "render_independent_retest_docx", failed)
    response = await client.get(url)
    assert response.status_code == 422 and "SYNTHETIC" not in response.text
    assert "no-store" in response.headers["cache-control"] and "content-disposition" not in response.headers
    assert calls == [doc["id"]]


@pytest.mark.asyncio
async def test_legacy_download_stays_unchanged_and_cannot_use_independent_renderer(api, monkeypatch):
    client, _, _, _ = api
    path, _, url = await legacy_archive(api, monkeypatch)
    before = await client.get(url)
    assert before.status_code == 200 and before.headers["x-devpilot-renderer"] == "qa-docx-v1"
    assert (await client.get(path + "/exports/" + RENDERER_ID + "?archive_hash=" + "a" * 64)).status_code == 404
    assert (await client.get(url)).content == before.content
