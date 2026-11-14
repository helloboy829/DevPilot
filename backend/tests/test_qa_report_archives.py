"""Synthetic immutable multi-component report drafts; no network or model calls."""

import asyncio
import json
import threading
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from test_dispatch_journal import prepared as prepared  # noqa: F401
from test_qa_evidence import captured as captured
from test_qa_evidence import observation, review

from app.evaluation import tables as t
from app.evaluation.qa_reports import ArchiveCreate, ReportArchiveRepository, archive_templates
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


def archives(repo):
    return ReportArchiveRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)


async def complete(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    second = await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=30)
    await repo.record_attempt("owner", project, run["id"], second, observation())
    for ordinal in (1, 2):
        case = await repo.open_case("owner", project, run["id"], ordinal)
        await repo.review_case("owner", project, run["id"], ordinal, review(case, decision="pass" if ordinal == 1 else "fail"))
    return await archives(repo).get_summary("owner", project, run["id"])


def payload(summary, **changes):
    return ArchiveCreate.model_validate(
        {"title": "Synthetic report", "template_id": "verified-qa-project-en", "template_version": "1.0.0", "sources": [{"run_id": summary["run_id"], "summary_hash": summary["summary_hash"]}], "confirmed": True, **changes}
    )


@pytest.mark.asyncio
async def test_server_results_are_frozen_not_recomputed_or_approved(captured):
    summary = await complete(captured)
    repo, _, project, _, run, _, _ = captured
    store, key = archives(repo), uuid4().hex
    request = payload(summary)
    saved = await store.create_archive("owner", project, key, request)
    assert saved["schema"] == "qa-project-report-archive.v1"
    assert saved["revision"] == 1 and saved["root_id"] == key and saved["supersedes_id"] is None
    assert saved["acceptance"] == "not_approved"
    assert saved["components"][0] == summary
    assert "50.00%" in saved["markdown"] and "DRAFT" in saved["markdown"]
    assert not any(word in json.dumps(saved) for word in ("SYNTHETIC_INPUT", "SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "SYNTHETIC_REVIEW_NOTE", "encrypted_payload", "reviewer_id"))
    assert await store.create_archive("owner", project, key, request) == saved
    case = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, review(case, decision="fail"))
    assert await store.get_archive("owner", project, key) == saved
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, request)
    revised = await store.get_summary("owner", project, run["id"])
    new = await store.create_archive("owner", project, uuid4().hex, payload(revised, supersedes_id=key, template_id="verified-qa-project-zh"))
    assert new["revision"] == 2 and new["root_id"] == key and new["supersedes_id"] == key
    assert new["components"][0]["human_pass_rate"]["numerator"] == 0
    assert saved["template"]["language"] == "en" and new["template"]["language"] == "zh"
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(revised, supersedes_id=key))
    assert await store.get_archive("owner", project, key) == saved
    listing = await store.list_archives("owner", project)
    assert len(listing) == 2 and all("markdown" not in item and "components" not in item for item in listing)


@pytest.mark.asyncio
async def test_explicit_sources_and_complete_review_are_required(captured):
    repo, _, project, _, run, _, _ = captured
    store = archives(repo)
    incomplete = await store.get_summary("owner", project, run["id"])
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(incomplete))
    summary = await complete(captured)
    case = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, review(case, decision="uncertain"))
    uncertain = await store.get_summary("owner", project, run["id"])
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(uncertain))
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(summary, template_version="99.0.0"))


@pytest.mark.asyncio
async def test_ownership_and_receipt_identity(captured):
    summary = await complete(captured)
    repo, _, project, _, _, _, _ = captured
    store, key = archives(repo), uuid4().hex
    saved = await store.create_archive("owner", project, key, payload(summary))
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, key, payload(summary, title="Different"))
    for action in (store.get_archive("stranger", project, key), store.list_archives("stranger", project), store.create_archive("stranger", project, uuid4().hex, payload(summary)), store.get_archive("owner", project, uuid4().hex)):
        with pytest.raises(NotFound):
            await action
    with pytest.raises(ValueError):
        await store.create_archive("owner", project, "../bad", payload(summary))
    assert await store.get_archive("owner", project, key) == saved


@pytest.mark.asyncio
async def test_template_changes_do_not_rerender_history(captured, monkeypatch):
    summary = await complete(captured)
    repo, _, project, _, _, _, _ = captured
    store, key = archives(repo), uuid4().hex
    saved = await store.create_archive("owner", project, key, payload(summary))
    monkeypatch.setattr("app.evaluation.qa_reports.archive_templates", lambda: [])
    assert await store.get_archive("owner", project, key) == saved
    assert await store.create_archive("owner", project, key, payload(summary)) == saved
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(summary))


@pytest.mark.asyncio
async def test_archive_integrity_check_rejects_modified_body(captured):
    summary = await complete(captured)
    repo, engine, project, _, _, _, _ = captured
    store, key = archives(repo), uuid4().hex
    await store.create_archive("owner", project, key, payload(summary))
    async with engine.begin() as conn:
        await conn.execute(update(t.report_archives).where(t.report_archives.c.id == key).values(document={"markdown": "SYNTHETIC_TAMPER"}))
    with pytest.raises(RequestProtectionError):
        await store.get_archive("owner", project, key)


@pytest.mark.asyncio
async def test_revision_race_rejects_stale_sources_before_atomic_archive(captured, monkeypatch):
    summary = await complete(captured)
    repo, engine, project, _, run, _, _ = captured
    store = archives(repo)
    entered, release = threading.Event(), threading.Event()
    original = SummaryRepository._verify_summary

    def verify(*args):
        assert threading.current_thread() is not threading.main_thread()
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(SummaryRepository, "_verify_summary", staticmethod(verify))
    task = asyncio.create_task(store.create_archive("owner", project, uuid4().hex, payload(summary)))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        case = await repo.open_case("owner", project, run["id"], 1)
        await repo.review_case("owner", project, run["id"], 1, review(case, decision="fail"))
    finally:
        release.set()
    with pytest.raises(Conflict):
        await task
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.report_archives))).scalar_one() == 0
        assert (await conn.execute(select(func.count()).select_from(t.dispatch_audit).where(t.dispatch_audit.c.action == "report_archived"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_archive_and_journal_audit_roll_back_together(captured, monkeypatch):
    summary = await complete(captured)
    repo, engine, project, _, _, _, _ = captured
    store = archives(repo)

    async def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    monkeypatch.setattr(store, "_journal_event", fail)
    with pytest.raises(RuntimeError):
        await store.create_archive("owner", project, uuid4().hex, payload(summary))
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.report_archives))).scalar_one() == 0


@pytest.mark.parametrize("changes", [{"confirmed": False}, {"confirmed": 1}, {"metrics": {"accuracy": 1}}, {"sources": []}, {"sources": [{"run_id": "x", "summary_hash": "a" * 64}]}, {"title": " "}, {"supersedes_id": "../other"}])
def test_strict_contract_never_accepts_client_metrics_or_implicit_consent(changes):
    with pytest.raises(ValidationError):
        payload({"run_id": "a" * 32, "summary_hash": "b" * 64}, **changes)


def test_catalog_has_both_versioned_language_templates():
    templates = archive_templates()
    assert {item["language"] for item in templates} == {"zh", "en"}
    assert {(item["language"], item["version"]) for item in templates} == {(language, version) for language in ("en", "zh") for version in ("1.0.0", "1.1.0")}
    assert all(item["layout"] for item in templates)


async def completed_run(repo, project, plan):
    from app.evaluation.dispatch_journal import JournalLimits

    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    for ordinal in (1, 2):
        ticket = await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=30)
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
        case = await repo.open_case("owner", project, run["id"], ordinal)
        await repo.review_case("owner", project, run["id"], ordinal, review(case))
    return await archives(repo).get_summary("owner", project, run["id"])


@pytest.mark.asyncio
async def test_multiple_components_keep_independent_verified_results(captured):
    from app.evaluation.plans import PlanCreate
    from app.evaluation.registry import ComponentLinkCreate
    from app.evaluation.request_versions import RequestVersionCreate
    from deerflow.persistence.models import ComponentRow

    first = await complete(captured)
    repo, _, project, plan, _, _, _ = captured
    async with repo.sf.begin() as session:
        session.add(ComponentRow(id="second", user_id="owner", name="Synthetic second", transport="http_post", api_url="https://example.test", validation_type="manual_review"))
    component = await repo.link_component("owner", project, ComponentLinkCreate(source_component_id="second", kind="llm"))
    version = await repo.create_request_version(
        "owner", project, component["id"], RequestVersionCreate(version_label="Second", confirmed=True, request={"url": "https://example.test", "method": "POST", "headers": [], "body": '{"q":"placeholder"}'})
    )
    definition = {key: value for key, value in plan["definition"].items() if key in PlanCreate.model_fields}
    definition.update(request_version_id=version["id"], request_protected_hash=version["protected_hash"], version_label="Second", confirmed=True)
    second_plan = await repo.create_plan("owner", project, component["id"], PlanCreate.model_validate(definition))
    second = await completed_run(repo, project, second_plan)
    store = archives(repo)
    sources = [{"run_id": item["run_id"], "summary_hash": item["summary_hash"]} for item in (first, second)]
    saved = await store.create_archive("owner", project, uuid4().hex, payload(first, sources=sources))
    assert {item["component_id"] for item in saved["components"]} == {first["component_id"], second["component_id"]}
    assert {item["human_pass_rate"]["value"] for item in saved["components"]} == {0.5, 1.0}
    assert "50.00%" in saved["markdown"] and "100.00%" in saved["markdown"]
    assert "human_pass_rate" not in saved
    duplicate_component = await completed_run(repo, project, plan)
    with pytest.raises(Conflict):
        await store.create_archive("owner", project, uuid4().hex, payload(first, sources=[sources[0], {"run_id": duplicate_component["run_id"], "summary_hash": duplicate_component["summary_hash"]}]))
    another = (await repo.create_project("owner", "Synthetic other"))["id"]
    with pytest.raises(NotFound):
        await store.create_archive("owner", another, uuid4().hex, payload(first))


@pytest.mark.parametrize("prepared", ["eval_0007"], indirect=True)
@pytest.mark.asyncio
async def test_deployed_0007_additive_upgrade_preserves_data_and_harness(captured):
    from sqlalchemy import inspect, text

    from app.evaluation.schema import upgrade_evaluation_schema

    first = await complete(captured)
    repo, engine, project, _, _, _, _ = captured
    preserved = (t.projects, t.request_versions, t.plans, t.output_evidence, t.case_reviews, t.dispatches, t.dispatch_runs, t.executions, t.execution_guard)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('synthetic_harness')"))
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0007"
        before = {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in preserved}
    await upgrade_evaluation_schema(engine)
    await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        after = {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in preserved}
        assert after == before
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0015"
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "synthetic_harness"
        columns = await conn.run_sync(lambda c: inspect(c).get_columns(t.report_archives.name))
        assert {column["name"] for column in columns} == set(t.report_archives.c.keys())
    assert (await archives(repo).create_archive("owner", project, uuid4().hex, payload(first)))["components"] == [first]


def test_duplicate_run_sources_rejected():
    source = {"run_id": "a" * 32, "summary_hash": "b" * 64}
    with pytest.raises(ValidationError):
        payload(source, sources=[source, source])
