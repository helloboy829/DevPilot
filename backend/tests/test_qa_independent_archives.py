"""Explicit immutable independent sources, never owner-summary substitution."""

import asyncio
import copy
import json
import threading
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select, update
from test_dispatch_journal import prepared as prepared
from test_qa_assessments import complete
from test_qa_assessments import payload as assessment_payload
from test_qa_evidence import captured as captured
from test_qa_evidence import observation
from test_review_tasks import ARB, TASK, A, B, command, decision
from test_review_tasks import tasks as tasks

from app.evaluation import tables as t
from app.evaluation.dispatch_journal import JournalLimits
from app.evaluation.plans import AcceptancePlanCreate, PlanCreate
from app.evaluation.qa_assessments import AssessmentRepository
from app.evaluation.qa_independent_archives import AssessmentSource, IndependentArchiveCreate, IndependentReportRepository, IndependentRetestCreate, IndependentRetestRepository
from app.evaluation.qa_reports import ReportArchiveRepository
from app.evaluation.qa_retests import RetestRepository
from app.evaluation.registry import fingerprint
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError
from app.evaluation.review_tasks import ReviewTaskRepository, TaskCreate, TaskReopen


def source(archive):
    return dict(run_id=archive["run_id"], summary_hash=archive["assessment"]["summary_hash"], assessment_id=archive["id"], assessment_revision=archive["revision"], assessment_hash=archive["assessment_hash"])


def report(archive, **changes):
    return IndependentArchiveCreate.model_validate(dict(title="Synthetic independent draft", template_id="independent-qa-project-en", template_version="1.0.0", sources=[source(archive)], confirmed=True) | changes)


async def frozen(tasks, **changes):
    repo = await complete(tasks, **changes)
    project, run = tasks[3], tasks[4]
    summary = await repo.get_preview("owner", project, run["id"])
    return await repo.create_assessment("owner", project, run["id"], uuid4().hex, assessment_payload(summary))


async def second_archive(tasks, label="Synthetic v2", outcomes=("pass", "pass"), **changes):
    _, evidence, _, project, original, clock, _, _ = tasks
    plan = await evidence.get_plan("owner", project, original["plan_id"])
    settings = {k: v for k, v in plan["definition"].items() if k in PlanCreate.model_fields}
    model = AcceptancePlanCreate if "acceptance_criteria" in changes else PlanCreate
    plan = await evidence.create_plan("owner", project, plan["component_id"], model.model_validate({**settings, "version_label": label, "confirmed": True, **changes}))
    clock["ms"] += 1000
    run = await evidence.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    reviewer = ReviewTaskRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=evidence.clock_ms)
    for ordinal, value in enumerate(outcomes, 1):
        ticket = await evidence.record_dispatch("owner", project, run["id"], ordinal, body_bytes=30)
        await evidence.record_attempt("owner", project, run["id"], ticket, observation())
        case = await evidence.open_case("owner", project, run["id"], ordinal)
        key = uuid4().hex
        await reviewer.create_task("owner", project, key, TaskCreate(run_id=run["id"], ordinal=ordinal, case_hash=case["case_hash"], reviewer_ids=[A, B], arbitrator_id=ARB, share_reference=True, confirmed=True))
        for actor in (A, B):
            claimed = await reviewer.claim(actor, key, command(await reviewer.get_task(actor, key)))
            await reviewer.open_task(actor, key)
            await reviewer.submit_decision(actor, key, decision(claimed, value))
    repository = AssessmentRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=evidence.clock_ms)
    preview = await repository.get_preview("owner", project, run["id"])
    return await repository.create_assessment("owner", project, run["id"], uuid4().hex, assessment_payload(preview))


@pytest.mark.asyncio
async def test_report_binds_exact_frozen_revision_without_owner_or_sensitive_reads(tasks, monkeypatch):
    archive = await frozen(tasks, second_decision="fail")
    _, evidence, engine, project, _, _, _, _ = tasks
    repo = IndependentReportRepository(evidence.sf)
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    key = uuid4().hex
    saved = await repo.create_archive("owner", project, key, report(archive))
    event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert saved["schema"] == "qa-independent-project-report-archive.v1"
    assert saved["scope"] == "immutable_independent_qa_report_draft" and saved["acceptance"] == "not_approved"
    assert saved["components"][0]["human_pass_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert saved["components"][0]["assessment_ref"] == {k: source(archive)[k] for k in ("assessment_id", "assessment_revision", "assessment_hash")}
    assert archive["id"] in saved["markdown"] and archive["assessment_hash"] in saved["markdown"]
    assert "50.00%" in saved["markdown"] and "NOT APPROVED" in saved["markdown"]
    assert not any(name in sql for sql in statements for name in ("evaluation_case_reviews", "evaluation_output_evidence", "evaluation_qa_references", "evaluation_request_versions", "evaluation_review_task_decisions"))
    assert not any(secret in json.dumps(saved) for secret in (A, B, "SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_INDEPENDENT_NOTE", "encrypted_payload"))
    assert await repo.create_archive("owner", project, key, report(archive)) == saved
    assert await ReportArchiveRepository(evidence.sf).list_archives("owner", project) == []
    assert len(await repo.list_archives("owner", project)) == 1
    monkeypatch.setattr("app.evaluation.qa_independent_archives.independent_templates", lambda: [])
    assert await repo.get_archive("owner", project, key) == saved


@pytest.mark.asyncio
async def test_historical_revision_is_explicit_not_silently_current(tasks):
    archive = await frozen(tasks)
    task_repo, evidence, _, project, run, _, _, _ = tasks
    task = await task_repo.get_task("owner", TASK)
    await task_repo.reopen("owner", TASK, TaskReopen(**command(task).model_dump(), reason="SYNTHETIC_REOPEN"))
    repo = IndependentReportRepository(evidence.sf)
    saved = await repo.create_archive("owner", project, uuid4().hex, report(archive))
    assert saved["components"][0]["counts"]["pass"] == 2
    assessment = AssessmentRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection)
    current = await assessment.get_preview("owner", project, run["id"])
    provisional = await assessment.create_assessment("owner", project, run["id"], uuid4().hex, assessment_payload(current, 1))
    with pytest.raises(Conflict):
        await repo.create_archive("owner", project, uuid4().hex, report(provisional))
    revised = await repo.create_archive("owner", project, uuid4().hex, report(archive, supersedes_id=saved["id"]))
    assert revised["revision"] == 2 and revised["root_id"] == saved["id"]
    with pytest.raises(Conflict):
        await repo.create_archive("owner", project, uuid4().hex, report(archive, supersedes_id=saved["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("assessment_id", "0" * 32), ("assessment_revision", 2), ("assessment_hash", "0" * 64), ("summary_hash", "0" * 64), ("run_id", "0" * 32)])
async def test_viewed_source_binding_is_exact(tasks, field, value):
    archive = await frozen(tasks)
    repository = IndependentReportRepository(tasks[1].sf)
    payload = report(archive)
    setattr(payload.sources[0], field, value)
    with pytest.raises((Conflict, NotFound)):
        await repository.create_archive("owner", tasks[3], uuid4().hex, payload)


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": "true"}, {"metrics": {}}, {"sources": []}])
def test_strict_create_contract(changes):
    document = dict(run_id="a" * 32, id="b" * 32, revision=1, assessment_hash="c" * 64, assessment={"summary_hash": "d" * 64})
    payload = report(document).model_dump()
    with pytest.raises(ValidationError):
        IndependentArchiveCreate.model_validate({**payload, **changes})
    legacy = {k: v for k, v in source(document).items() if k in {"run_id", "summary_hash"}}
    with pytest.raises(ValidationError):
        AssessmentSource.model_validate(legacy)


@pytest.mark.asyncio
async def test_independent_retest_uses_selected_resolutions_and_all_samples(tasks):
    first = await frozen(tasks, second_decision="fail")
    second = await second_archive(tasks)
    evidence, project = tasks[1], tasks[3]
    repo = IndependentRetestRepository(evidence.sf)
    payload = IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True)
    key = uuid4().hex
    saved = await repo.create_retest("owner", project, key, payload)
    assert saved["schema"] == "qa-independent-retest-archive.v1" and saved["scope"] == "same_benchmark_independent_comparison"
    assert saved["transitions"] == {"fail_to_pass": 1, "pass_to_fail": 0, "pass_to_pass": 1, "fail_to_fail": 0}
    assert saved["pass_rate_delta"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert {c["sample_id"] for c in saved["cases"]} == {"a", "z"}
    assert saved["baseline"]["assessment_ref"]["assessment_id"] == first["id"]
    assert saved["benchmark"]["independent_policy"] == first["assessment"]["policy"]
    assert saved["cases"][1]["baseline_tasks"] == first["assessment"]["cases"][1]["tasks"]
    assert saved["acceptance"] == "not_approved"
    assert await repo.create_retest("owner", project, key, payload) == saved
    with pytest.raises(Conflict):
        await repo.create_retest("owner", project, uuid4().hex, payload)
    assert await RetestRepository(evidence.sf).list_retests("owner", project) == []
    assert len(await repo.list_retests("owner", project)) == 1
    with pytest.raises(NotFound):
        await repo.get_retest("other", project, key)


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["assessment_hash", "document", "plan", "run_hash"])
async def test_tampered_sources_rejected(tasks, damage):
    archive = await frozen(tasks)
    engine, project = tasks[2], tasks[3]
    async with engine.begin() as conn:
        if damage == "assessment_hash":
            await conn.execute(update(t.run_assessments).values(assessment_hash="0" * 64))
        elif damage == "document":
            doc = copy.deepcopy(archive)
            doc.pop("assessment_hash")
            doc["assessment"]["counts"]["pass"] = 1
            await conn.execute(update(t.run_assessments).values(document=doc))
        elif damage == "plan":
            await conn.execute(update(t.plans).values(definition_hash="0" * 64))
        else:
            await conn.execute(update(t.dispatch_runs).values(plan_hash="0" * 64))
    with pytest.raises((Conflict, RequestProtectionError)):
        await IndependentReportRepository(tasks[1].sf).create_archive("owner", project, uuid4().hex, report(archive))


@pytest.mark.asyncio
async def test_final_source_reread_and_atomic_audit_rollback(tasks, monkeypatch):
    archive = await frozen(tasks)
    repo, engine, project = IndependentReportRepository(tasks[1].sf), tasks[2], tasks[3]
    original = repo._source_snapshot
    calls = 0

    async def changed(*args, **kwargs):
        nonlocal calls
        snapshot = await original(*args, **kwargs)
        calls += 1
        if calls > 1:
            snapshot["assessment"]["assessment_hash"] = "0" * 64
        return snapshot

    monkeypatch.setattr(repo, "_source_snapshot", changed)
    with pytest.raises(Conflict):
        await repo.create_archive("owner", project, uuid4().hex, report(archive))
    monkeypatch.setattr(repo, "_source_snapshot", original)

    async def fail(*args, **kwargs):
        raise RuntimeError("SYNTHETIC_AUDIT_FAILURE")

    monkeypatch.setattr(repo, "_journal_event", fail)
    with pytest.raises(RuntimeError):
        await repo.create_archive("owner", project, uuid4().hex, report(archive))
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.independent_report_archives))).scalar_one() == 0


@pytest.mark.asyncio
async def test_crypto_and_rendering_run_off_loop(tasks, monkeypatch):
    archive = await frozen(tasks)
    repo = IndependentReportRepository(tasks[1].sf)
    thread = threading.get_ident()
    original = repo._verify_sources

    def checked(*args):
        assert threading.get_ident() != thread
        return original(*args)

    monkeypatch.setattr(repo, "_verify_sources", checked)
    await repo.create_archive("owner", tasks[3], uuid4().hex, report(archive))


@pytest.mark.asyncio
async def test_frozen_criteria_not_met_is_reported_not_approved_or_silently_filtered(tasks):
    await frozen(tasks)
    criteria = {"schema": "qa-effectiveness-criteria.v1", "version_label": "Synthetic criteria", "min_pass_rate_bps": 10000}
    first = await second_archive(tasks, label="Synthetic v2 criteria", outcomes=("pass", "fail"), acceptance_criteria=criteria)
    second = await second_archive(tasks, label="Synthetic v3 criteria", acceptance_criteria=criteria)
    repo, project = IndependentReportRepository(tasks[1].sf), tasks[3]
    saved = await repo.create_archive("owner", project, uuid4().hex, report(first, template_id="independent-qa-project-zh"))
    assert saved["components"][0]["criteria_evaluation"]["status"] == "not_met"
    assert "not_met" in saved["markdown"] and "50.00%" in saved["markdown"] and "100.00%" in saved["markdown"]
    compared = await IndependentRetestRepository(tasks[1].sf).create_retest("owner", project, uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assert compared["baseline"]["criteria_evaluation"]["status"] == "not_met"
    assert compared["retest"]["criteria_evaluation"]["status"] == "met"
    assert compared["acceptance"] == "not_approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["report", "retest"])
async def test_same_id_concurrency_single_append_ordered_run_locks_and_audits(tasks, monkeypatch, kind):
    first = await frozen(tasks)
    second = await second_archive(tasks) if kind == "retest" else None
    cls = IndependentReportRepository if kind == "report" else IndependentRetestRepository
    repo, engine, project = cls(tasks[1].sf), tasks[2], tasks[3]
    create = repo.create_archive if kind == "report" else repo.create_retest
    payload = report(first) if kind == "report" else IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True)
    locks, original = [], repo._journal

    async def journal(*args, **kwargs):
        if kwargs.get("lock"):
            locks.append(args[3])
        return await original(*args, **kwargs)

    monkeypatch.setattr(repo, "_journal", journal)
    key = uuid4().hex
    left, right = await asyncio.gather(create("owner", project, key, payload), create("owner", project, key, payload))
    assert left == right
    assert locks == sorted([first["run_id"], second["run_id"]] if second else [first["run_id"]])
    table = t.independent_report_archives if kind == "report" else t.independent_retest_archives
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(table))).scalar_one() == 1
        assert (await conn.execute(select(func.count()).select_from(t.dispatch_audit).where(t.dispatch_audit.c.action == repo._audit_kind))).scalar_one() == (2 if second else 1)


@pytest.mark.asyncio
async def test_independent_two_run_audits_and_archive_rollback_together(tasks, monkeypatch):
    first = await frozen(tasks)
    second = await second_archive(tasks)
    repo, engine, project = IndependentRetestRepository(tasks[1].sf), tasks[2], tasks[3]
    calls, original = [], repo._journal_event

    async def fail(session, run, action, at, **kwargs):
        calls.append(run["id"])
        await original(session, run, action, at, **kwargs)
        if len(calls) == 2:
            raise Conflict

    monkeypatch.setattr(repo, "_journal_event", fail)
    with pytest.raises(Conflict):
        await repo.create_retest("owner", project, uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assert calls == sorted([first["run_id"], second["run_id"]])
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.independent_retest_archives))).scalar_one() == 0
        assert (await conn.execute(select(func.count()).select_from(t.dispatch_audit).where(t.dispatch_audit.c.action == repo._audit_kind))).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["denominator", "boolean_count", "component_type", "extra_key", "case_order", "duplicate_task", "sample_order", "policy", "technical", "criteria_type"])
async def test_frozen_commitments_are_strict_even_with_internally_consistent_checksums(tasks, damage):
    await frozen(tasks)
    criteria = {"schema": "qa-effectiveness-criteria.v1", "version_label": "Synthetic", "min_pass_rate_bps": 1}
    archive = await second_archive(tasks, acceptance_criteria=criteria)
    repo = IndependentReportRepository(tasks[1].sf)
    async with repo.sf() as session:
        snapshot = await repo._source_snapshot(session, "owner", tasks[3], AssessmentSource(**source(archive)))
    raw = snapshot["assessment"]
    summary = raw["document"]["assessment"]
    if damage == "denominator":
        summary["human_pass_rate"]["denominator"] = 1
    elif damage == "boolean_count":
        summary["counts"]["unreviewed"] = False
    elif damage == "component_type":
        summary["component_name"] = {"not": "a bounded label"}
    elif damage == "extra_key":
        summary["unexpected"] = "value"
    elif damage == "case_order":
        summary["cases"].reverse()
    elif damage == "duplicate_task":
        summary["cases"][1]["tasks"] = copy.deepcopy(summary["cases"][0]["tasks"])
    elif damage == "sample_order":
        snapshot["dispatches"].reverse()
    elif damage == "policy":
        summary["policy"]["timing"] = "pre_run_authorization"
    elif damage == "technical":
        summary["technical_counts"]["other"] = 1
    else:
        summary["criteria_evaluation"]["criteria"]["min_pass_rate_bps"] = True
    summary["summary_hash"] = fingerprint({k: v for k, v in summary.items() if k != "summary_hash"})
    raw["summary_hash"] = summary["summary_hash"]
    raw["request_hash"] = fingerprint(assessment_payload(summary, raw["revision"] - 1).model_dump())
    raw["assessment_hash"] = fingerprint({"owner_id": "owner", "request_hash": raw["request_hash"], "document": raw["document"]})
    snapshot["viewed"].update(summary_hash=raw["summary_hash"], assessment_hash=raw["assessment_hash"])
    with pytest.raises((Conflict, RequestProtectionError)):
        repo._verify_frozen_source("owner", snapshot)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["report", "retest"])
async def test_archive_receipt_tampering_is_rejected_on_open(tasks, kind):
    first = await frozen(tasks)
    second = await second_archive(tasks) if kind == "retest" else None
    repo = IndependentReportRepository(tasks[1].sf) if kind == "report" else IndependentRetestRepository(tasks[1].sf)
    key, project = uuid4().hex, tasks[3]
    create, get, table, payload = (
        (repo.create_archive, repo.get_archive, t.independent_report_archives, report(first))
        if kind == "report"
        else (repo.create_retest, repo.get_retest, t.independent_retest_archives, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    )
    await create("owner", project, key, payload)
    async with tasks[2].begin() as conn:
        await conn.execute(update(table).where(table.c.id == key).values(archive_hash="0" * 64))
    with pytest.raises(RequestProtectionError):
        await get("owner", project, key)


@pytest.mark.asyncio
async def test_all_report_hashing_verification_and_rendering_are_off_loop(tasks, monkeypatch):
    from app.evaluation import qa_independent_archives, qa_reports

    archive = await frozen(tasks)
    thread, seen = threading.get_ident(), set()

    def wrap(name, fn):
        def checked(*args, **kwargs):
            assert threading.get_ident() != thread
            seen.add(name)
            return fn(*args, **kwargs)

        return checked

    monkeypatch.setattr(qa_reports, "fingerprint", wrap("hash", qa_reports.fingerprint))
    monkeypatch.setattr(qa_independent_archives, "fingerprint", wrap("source_hash", qa_independent_archives.fingerprint))
    monkeypatch.setattr(IndependentReportRepository, "_render", staticmethod(wrap("render", IndependentReportRepository._render)))
    repo = IndependentReportRepository(tasks[1].sf)
    saved = await repo.create_archive("owner", tasks[3], uuid4().hex, report(archive))
    assert await repo.get_archive("owner", tasks[3], saved["id"]) == saved
    assert seen == {"hash", "source_hash", "render"}


@pytest.mark.parametrize("field,value", [("assessment_revision", True), ("assessment_revision", "1"), ("assessment_revision", 0), ("assessment_revision", 1001), ("assessment_hash", "x" * 64), ("metrics", {})])
def test_source_references_are_strict_and_do_not_accept_client_metrics(field, value):
    values = dict(run_id="a" * 32, summary_hash="b" * 64, assessment_id="c" * 32, assessment_revision=1, assessment_hash="d" * 64)
    with pytest.raises(ValidationError):
        AssessmentSource.model_validate({**values, field: value})


@pytest.mark.asyncio
async def test_retest_can_explicitly_bind_a_different_historical_revision_not_latest_pointer(tasks):
    first = await frozen(tasks, second_decision="fail")
    second = await second_archive(tasks)
    evidence, project = tasks[1], tasks[3]
    repo = IndependentRetestRepository(evidence.sf)
    original = await repo.create_retest("owner", project, uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assessments = AssessmentRepository(evidence.sf, protection=evidence.protection, evidence_protection=evidence.evidence_protection, clock_ms=evidence.clock_ms)
    preview = await assessments.get_preview("owner", project, first["run_id"])
    revised = await assessments.create_assessment("owner", project, first["run_id"], uuid4().hex, assessment_payload(preview, 1))
    newer = await repo.create_retest("owner", project, uuid4().hex, IndependentRetestCreate(baseline=source(revised), retest=source(second), confirmed=True))
    assert newer["baseline"]["assessment_ref"]["assessment_revision"] == 2
    assert newer["baseline"]["assessment_ref"]["assessment_id"] == revised["id"]
    assert await repo.get_retest("owner", project, original["id"]) == original
    assert len(await repo.list_retests("owner", project)) == 2


@pytest.mark.asyncio
async def test_multi_component_report_preserves_each_population_and_sorted_lock_order(tasks, monkeypatch):
    from app.evaluation.registry import ComponentLinkCreate
    from app.evaluation.request_versions import RequestVersionCreate
    from deerflow.persistence.component_tests.model import ComponentRow

    first = await frozen(tasks, second_decision="fail")
    evidence, project = tasks[1], tasks[3]
    async with evidence.sf.begin() as session:
        session.add(ComponentRow(id="other_source", user_id="owner", name="Synthetic second component", transport="http_post", api_url="https://example.invalid", validation_type="manual_review"))
    component = await evidence.link_component("owner", project, ComponentLinkCreate(source_component_id="other_source", kind="llm"))
    request = await evidence.create_request_version(
        "owner", project, component["id"], RequestVersionCreate(version_label="Synthetic other", confirmed=True, request={"url": "https://example.invalid", "method": "POST", "headers": [], "body": '{"q":"placeholder"}'})
    )
    plan = await evidence.get_plan("owner", project, tasks[4]["plan_id"])
    settings = {key: value for key, value in plan["definition"].items() if key in PlanCreate.model_fields}
    plan = await evidence.create_plan(
        "owner", project, component["id"], PlanCreate.model_validate({**settings, "request_version_id": request["id"], "request_protected_hash": request["protected_hash"], "version_label": "Synthetic second component", "confirmed": True})
    )
    other_tasks = list(tasks)
    other_tasks[4] = {**tasks[4], "plan_id": plan["id"]}
    second = await second_archive(other_tasks)
    repo = IndependentReportRepository(evidence.sf)
    locks, journal = [], repo._journal

    async def checked(*args, **kwargs):
        if kwargs.get("lock"):
            locks.append(args[3])
        return await journal(*args, **kwargs)

    monkeypatch.setattr(repo, "_journal", checked)
    saved = await repo.create_archive("owner", project, uuid4().hex, report(first, sources=[source(second), source(first)]))
    assert locks == sorted([first["run_id"], second["run_id"]])
    assert [s["component_id"] for s in saved["components"]] == sorted([first["assessment"]["component_id"], second["assessment"]["component_id"]])
    assert sorted(s["human_pass_rate"]["numerator"] for s in saved["components"]) == [1, 2]
    assert all(s["human_pass_rate"]["denominator"] == 2 for s in saved["components"])
    assert "50.00%" in saved["markdown"] and "100.00%" in saved["markdown"]
    assert "overall_pass_rate" not in saved
    same_component = await second_archive(tasks, label="Synthetic same component v3")
    with pytest.raises(Conflict):
        await repo.create_archive("owner", project, uuid4().hex, report(first, sources=[source(first), source(same_component)]))


@pytest.mark.asyncio
async def test_retest_final_reread_checks_both_historical_sources(tasks, monkeypatch):
    first = await frozen(tasks)
    second = await second_archive(tasks)
    repo = IndependentRetestRepository(tasks[1].sf)
    original, calls = repo._source_snapshot, 0

    async def changed(*args, **kwargs):
        nonlocal calls
        snapshot = await original(*args, **kwargs)
        calls += 1
        if calls == 4:
            snapshot["assessment"]["assessment_hash"] = "0" * 64
        return snapshot

    monkeypatch.setattr(repo, "_source_snapshot", changed)
    with pytest.raises(Conflict):
        await repo.create_retest("owner", tasks[3], uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assert calls == 4
    assert await repo.list_retests("owner", tasks[3]) == []


@pytest.mark.asyncio
async def test_retest_hashing_and_source_verification_off_loop(tasks, monkeypatch):
    from app.evaluation import qa_retests

    first = await frozen(tasks)
    second = await second_archive(tasks)
    thread, original = threading.get_ident(), qa_retests.fingerprint

    def checked(*args, **kwargs):
        assert threading.get_ident() != thread
        return original(*args, **kwargs)

    monkeypatch.setattr(qa_retests, "fingerprint", checked)
    repo = IndependentRetestRepository(tasks[1].sf)
    saved = await repo.create_retest("owner", tasks[3], uuid4().hex, IndependentRetestCreate(baseline=source(first), retest=source(second), confirmed=True))
    assert await repo.get_retest("owner", tasks[3], saved["id"]) == saved
