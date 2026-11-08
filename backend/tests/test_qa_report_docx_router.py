"""Private frozen-archive DOCX HTTP download, synthetic inputs only."""

import hashlib
import io
import threading
import zipfile
from uuid import uuid4

import pytest
from sqlalchemy import update
from test_evaluation_registry_router import api as api
from test_qa_report_archives_router import source

from app.evaluation import tables as t
from app.evaluation.report_docx import DOCX_MIME, RENDERER_ID
from app.gateway.authz import Permissions


async def saved_archive(api, monkeypatch):
    payload = await source(api, monkeypatch)
    path = api[2] + "/report-archives/" + uuid4().hex
    saved = (await api[0].put(path, json=payload)).json()
    return path, saved, path + "/exports/" + RENDERER_ID + "?archive_hash=" + saved["archive_hash"]


@pytest.mark.asyncio
async def test_binary_frozen_download_without_key_or_current_template_and_off_loop(api, monkeypatch):
    client, _, _, _ = api
    path, saved, url = await saved_archive(api, monkeypatch)
    from app.evaluation import qa_reports
    from app.gateway.routers import evaluation_projects as routes

    thread = threading.get_ident()
    real = routes.render_archived_docx
    real_decode = qa_reports.ReportArchiveRepository._decode

    def decode(row):
        assert threading.get_ident() != thread
        return real_decode(row)

    monkeypatch.setattr(qa_reports.ReportArchiveRepository, "_decode", staticmethod(decode))

    def render(doc):
        assert threading.get_ident() != thread
        assert doc == saved
        return real(doc)

    monkeypatch.setattr(routes, "render_archived_docx", render)
    monkeypatch.setattr(qa_reports, "archive_templates", lambda: [])
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    response = await client.get(url)
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX_MIME
    assert "private" in response.headers["cache-control"] and "no-store" in response.headers["cache-control"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-devpilot-renderer"] == RENDERER_ID
    assert response.headers["content-disposition"] == 'attachment; filename="qa-report-' + saved["id"] + '-r1.docx"'
    assert (await client.get(url)).content == response.content
    assert (await client.get(path)).json() == saved
    with zipfile.ZipFile(io.BytesIO(response.content)) as package:
        xml = package.read("word/document.xml").decode()
    assert saved["archive_hash"] in xml and hashlib.sha256(saved["markdown"].encode()).hexdigest() in xml
    assert all(text not in xml for text in ["SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD"])


@pytest.mark.asyncio
async def test_human_owner_review_permissions_get_only_and_bad_receipts(api, monkeypatch):
    client, app, base, _ = api
    path, _, url = await saved_archive(api, monkeypatch)
    assert (await client.get(path + "/exports/" + RENDERER_ID)).status_code == 422
    assert (await client.get(url.split("?")[0] + "?archive_hash=" + "0" * 64)).status_code == 409
    assert (await client.get(url.replace(RENDERER_ID, "qa-docx-v2"))).status_code == 404
    assert (await client.get(base + "/report-archives/invalid/exports/" + RENDERER_ID + "?archive_hash=" + "a" * 64)).status_code == 422
    assert (await client.post(url, json={"markdown": "UNTRUSTED"})).status_code == 405
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ]
    assert (await client.get(url)).status_code == 403
    app.state.permissions.append(Permissions.EVALUATION_PROJECTS_REVIEW)
    assert (await client.get(url)).status_code == 200  # Export does not need write permission.
    app.state.internal = True
    assert (await client.get(url)).status_code == 403
    app.state.internal = False
    app.state.actor = 2
    assert (await client.get(url)).status_code == 404
    app.state.actor = 0
    assert (await client.get(url)).status_code == 401


@pytest.mark.asyncio
async def test_corrupt_archive_or_unexportable_xml_never_downloads_a_fake_success(api, monkeypatch):
    client, app, _, _ = api
    _, saved, url = await saved_archive(api, monkeypatch)
    sf = app.state.evaluation_repo.sf
    async with sf.begin() as session:
        await session.execute(update(t.report_archives).where(t.report_archives.c.id == saved["id"]).values(archive_hash="0" * 64))
    response = await client.get(url)
    assert response.status_code == 503 and "no-store" in response.headers["cache-control"]
    assert "attachment" not in response.headers.get("content-disposition", "")
    async with sf.begin() as session:
        await session.execute(update(t.report_archives).where(t.report_archives.c.id == saved["id"]).values(archive_hash=saved["archive_hash"]))
    from app.evaluation.report_docx import ReportExportError
    from app.gateway.routers import evaluation_projects as routes

    def reject(_doc):
        raise ReportExportError("SENSITIVE_FAKE_EXCEPTION")

    monkeypatch.setattr(routes, "render_archived_docx", reject)
    response = await client.get(url)
    assert response.status_code == 422 and "no-store" in response.headers["cache-control"]
    assert "SENSITIVE_FAKE_EXCEPTION" not in response.text


@pytest.mark.asyncio
async def test_archive_decode_off_loop_for_repeated_receipts_and_revision_parents(api, monkeypatch):
    from app.evaluation.qa_reports import ReportArchiveRepository

    thread = threading.get_ident()
    real_decode = ReportArchiveRepository._decode
    decoded = []

    def decode(row):
        assert threading.get_ident() != thread
        decoded.append(row["id"])
        return real_decode(row)

    monkeypatch.setattr(ReportArchiveRepository, "_decode", staticmethod(decode))
    payload = await source(api, monkeypatch)
    client, _, base, _ = api
    first_id = uuid4().hex
    path = base + "/report-archives/" + first_id
    first = await client.put(path, json=payload)
    assert first.status_code == 200
    repeated = await client.put(path, json=payload)
    assert repeated.status_code == 200 and repeated.json() == first.json()
    revision = await client.put(base + "/report-archives/" + uuid4().hex, json={**payload, "supersedes_id": first_id})
    assert revision.status_code == 200 and revision.json()["revision"] == 2
    assert decoded.count(first_id) >= 2
