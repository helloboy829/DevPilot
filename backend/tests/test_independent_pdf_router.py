"""GET-only viewed historical PDFs; integrity/rendering off-loop, no sources/keys."""

import io
import threading

import pytest
from pdfminer.high_level import extract_text
from sqlalchemy import update
from test_evaluation_registry_router import api as api
from test_independent_report_docx_router import saved_archive as report
from test_independent_retest_docx_router import saved_archive as retest

from app.evaluation import tables as t
from app.evaluation.qa_independent_archives import IndependentReportRepository, IndependentRetestRepository
from app.evaluation.report_docx import ReportExportError
from app.gateway.authz import Permissions


@pytest.fixture(params=[("report", report, IndependentReportRepository, "independent-qa-pdf-v1"), ("retest", retest, IndependentRetestRepository, "independent-retest-pdf-v1")])
def target(request):
    return request.param


@pytest.mark.asyncio
async def test_frozen_get_receipt_off_loop_no_current_source_key_or_mutation(api, monkeypatch, target):
    kind, create, repository, renderer = target
    client, _, _, _ = api
    path, doc, word_url = await create(api, monkeypatch)
    url = word_url.replace("docx-v1", "pdf-v1")
    from app.gateway.routers import evaluation_projects as routes

    function = "render_independent_" + kind + "_pdf"
    render, decode, thread = getattr(routes, function), repository._decode, threading.get_ident()

    def checked_render(value):
        assert threading.get_ident() != thread and value == doc
        return render(value)

    def checked_decode(value):
        assert threading.get_ident() != thread
        return decode(value)

    def forbidden(*args, **kwargs):
        raise AssertionError("No current tasks, sources, evidence, keys or templates")

    monkeypatch.setattr(routes, function, checked_render)
    monkeypatch.setattr(repository, "_decode", staticmethod(checked_decode))
    monkeypatch.setattr(repository, "_source_snapshot", forbidden)
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY")
    result = await client.get(url)
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "application/pdf"
    assert result.headers["x-devpilot-renderer"] == renderer
    assert result.headers["cache-control"] == "private, no-store" and result.headers["x-content-type-options"] == "nosniff"
    expected = f"independent-qa-report-{doc['id']}-r{doc['revision']}.pdf" if kind == "report" else f"independent-retest-{doc['id']}.pdf"
    assert result.headers["content-disposition"] == f'attachment; filename="{expected}"'
    assert doc["archive_hash"] in "".join(extract_text(io.BytesIO(result.content)).split())
    assert (await client.get(url)).content == result.content
    assert (await client.get(path)).json() == doc


@pytest.mark.asyncio
async def test_human_owner_authz_receipt_version_namespace_and_get_only(api, monkeypatch, target):
    kind, create, _, renderer = target
    client, app, _, _ = api
    _, doc, word_url = await create(api, monkeypatch)
    url = word_url.replace("docx-v1", "pdf-v1")
    assert (await client.get(url.split("?")[0])).status_code == 422
    assert (await client.get(url.replace(doc["archive_hash"], "0" * 64))).status_code == 409
    assert (await client.get(url.replace(renderer, renderer.replace("v1", "v2")))).status_code == 404
    assert (await client.get(url.replace(renderer, "qa-pdf-v1"))).status_code == 404
    other = "independent-retest-pdf-v1" if kind == "report" else "independent-qa-pdf-v1"
    assert (await client.get(url.replace(renderer, other))).status_code == 404
    assert (await client.post(url, json={"markdown": "UNTRUSTED"})).status_code == 405
    for permissions in ([Permissions.EVALUATION_PROJECTS_READ], [Permissions.EVALUATION_PROJECTS_REVIEW], [Permissions.EVALUATION_PROJECTS_WRITE]):
        app.state.permissions = permissions
        assert (await client.get(url)).status_code == 403
    app.state.permissions = [Permissions.EVALUATION_PROJECTS_READ, Permissions.EVALUATION_PROJECTS_REVIEW]
    assert (await client.get(url)).status_code == 200
    app.state.internal = True
    assert (await client.get(url)).status_code == 403
    app.state.internal = False
    for actor, status in [(2, 404), (0, 401)]:
        app.state.actor = actor
        assert (await client.get(url)).status_code == status


@pytest.mark.asyncio
async def test_tampered_receipts_generic_failure_and_no_retry(api, monkeypatch, target):
    kind, create, _, _ = target
    client, app, _, _ = api
    _, doc, word_url = await create(api, monkeypatch)
    url = word_url.replace("docx-v1", "pdf-v1")
    table = t.independent_report_archives if kind == "report" else t.independent_retest_archives
    async with app.state.evaluation_repo.sf.begin() as session:
        await session.execute(update(table).where(table.c.id == doc["id"]).values(archive_hash="0" * 64))
    result = await client.get(url)
    assert result.status_code == 503 and "content-disposition" not in result.headers
    async with app.state.evaluation_repo.sf.begin() as session:
        await session.execute(update(table).where(table.c.id == doc["id"]).values(archive_hash=doc["archive_hash"]))
    from app.gateway.routers import evaluation_projects as routes

    calls = []

    def failed(value):
        calls.append(value["id"])
        raise ReportExportError("SYNTHETIC_PRIVATE")

    monkeypatch.setattr(routes, "render_independent_" + kind + "_pdf", failed)
    result = await client.get(url)
    assert result.status_code == 422 and "SYNTHETIC" not in result.text
    assert "no-store" in result.headers["cache-control"] and "content-disposition" not in result.headers
    assert calls == [doc["id"]]
