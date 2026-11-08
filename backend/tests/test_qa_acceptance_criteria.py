"""Pre-run frozen effectiveness criteria, synthetic data only; never approval."""

import asyncio
import copy
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from markitdown import MarkItDown
from pydantic import ValidationError
from sqlalchemy import update
from test_dispatch_journal import prepared as prepared  # noqa: F401
from test_qa_evidence import observation, review

from app.evaluation import tables as t
from app.evaluation.criteria import EffectivenessCriteria, assess_criteria
from app.evaluation.dispatch_journal import JournalLimits
from app.evaluation.evidence_protection import EvidenceProtection
from app.evaluation.execution import ExecutionCreate, ExecutionPolicy, ExecutionRepository, QAExecutionWorker
from app.evaluation.plans import AcceptancePlanCreate, PlanCreate
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.qa_reports import ArchiveCreate, ReportArchiveRepository
from app.evaluation.qa_retests import _same_benchmark
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.report_docx import render_archived_docx
from app.evaluation.repository import Conflict


def criteria(**changes):
    return {"schema": "qa-effectiveness-criteria.v1", "version_label": "Synthetic criteria v1", "min_pass_rate_bps": 5000, **changes}


@pytest.mark.parametrize(
    "change",
    [
        {"min_pass_rate_bps": True},
        {"min_pass_rate_bps": "5000"},
        {"min_pass_rate_bps": 0.5},
        {"min_pass_rate_bps": -1},
        {"min_pass_rate_bps": 10001},
        {"version_label": "bad\nlabel"},
        {"version_label": "   "},
        {"version_label": "\ud800"},
        {"automatic_approval": True},
        {"max_ttft_ms": 1},
    ],
)
def test_strict_versioned_effectiveness_only_contract(change):
    with pytest.raises(ValidationError):
        EffectivenessCriteria.model_validate(criteria(**change))


@pytest.mark.parametrize(
    "threshold,numerator,denominator,blockers,status",
    [(3333, 1, 3, [], "met"), (3334, 1, 3, [], "not_met"), (10000, 2, 2, [], "met"), (0, 0, 2, [], "met"), (0, 0, 2, ["unreviewed"], "incomplete"), (0, 0, 2, ["technical_incomplete"], "incomplete")],
)
def test_integer_comparison_never_rounds_or_treats_incomplete_as_met(threshold, numerator, denominator, blockers, status):
    result = assess_criteria(criteria(min_pass_rate_bps=threshold), numerator, denominator, blockers)
    assert result["status"] == status
    assert result["scope"] == "effectiveness_threshold_only"
    assert result["criteria"]["min_pass_rate_bps"] == threshold
    assert result["blockers"] == blockers
    assert result["approval"] == "not_approved"


@pytest_asyncio.fixture
async def assessed(prepared):
    original, engine, project, old, clock = prepared
    repo = SummaryRepository(original.sf, protection=original.protection, evidence_protection=EvidenceProtection(Fernet.generate_key()), clock_ms=lambda: clock["ms"])
    fields = {key: old["definition"][key] for key in PlanCreate.model_fields if key != "confirmed"}
    payload = AcceptancePlanCreate.model_validate({**fields, "version_label": "Synthetic criteria plan", "acceptance_criteria": criteria(), "confirmed": True})
    plan = await repo.create_plan("owner", project, old["component_id"], payload)
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    yield repo, engine, project, old, plan, run, payload


@pytest.mark.asyncio
async def test_legacy_hashes_unchanged_and_new_criteria_bound_to_plan_before_run(assessed):
    repo, engine, project, old, plan, _, payload = assessed
    assert plan["definition"]["schema"] == "qa-json-plan.v2"
    assert plan["definition"]["acceptance_criteria"] == criteria()
    assert await repo.get_plan("owner", project, old["id"]) == old
    assert "acceptance_criteria" not in old["definition"]
    with pytest.raises(ValidationError):
        AcceptancePlanCreate.model_validate({**payload.model_dump(), "limits": {**payload.limits.model_dump(), "mode": "performance"}})
    other = await repo.create_plan("owner", project, plan["component_id"], payload.model_copy(update={"version_label": "Synthetic next plan", "acceptance_criteria": EffectivenessCriteria.model_validate(criteria(min_pass_rate_bps=9000))}))
    assert other["definition_hash"] != plan["definition_hash"]
    for changed in (other["definition"], old["definition"]):
        with pytest.raises(Conflict):
            _same_benchmark(plan["definition"], changed)
    assert _same_benchmark(plan["definition"], copy.deepcopy(plan["definition"]))["acceptance_criteria"] == criteria()
    async with engine.begin() as session:
        altered = copy.deepcopy(plan["definition"])
        altered["acceptance_criteria"]["min_pass_rate_bps"] = 0
        await session.execute(update(t.plans).where(t.plans.c.id == plan["id"]).values(definition=altered))
    with pytest.raises(Conflict):
        await repo.get_summary("owner", project, (await repo.list_runs("owner", project))[0]["id"])


@pytest.mark.asyncio
async def test_verified_summary_and_report_keep_frozen_criteria_not_approval(assessed):
    repo, _, project, _, plan, run, _ = assessed
    before = await repo.get_summary("owner", project, run["id"])
    assert before["criteria_evaluation"]["status"] == "incomplete"
    for ordinal in (1, 2):
        ticket = await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=30)
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
        case = await repo.open_case("owner", project, run["id"], ordinal)
        await repo.review_case("owner", project, run["id"], ordinal, review(case, decision="pass" if ordinal == 1 else "fail"))
    summary = await repo.get_summary("owner", project, run["id"])
    assert summary["criteria_evaluation"]["status"] == "met"
    assert summary["criteria_evaluation"]["criteria"] == plan["definition"]["acceptance_criteria"]
    assert summary["acceptance"] == "not_approved"
    assert summary["summary_hash"] != before["summary_hash"]
    archive = ReportArchiveRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)
    fields = dict(title="Synthetic", template_id="verified-qa-project-en", template_version="1.0.0", sources=[{"run_id": run["id"], "summary_hash": summary["summary_hash"]}], confirmed=True)
    with pytest.raises(Conflict):
        await archive.create_archive("owner", project, uuid4().hex, ArchiveCreate.model_validate(fields))
    key = uuid4().hex
    saved = await archive.create_archive("owner", project, key, ArchiveCreate.model_validate({**fields, "template_version": "1.1.0"}))
    assert "Frozen effectiveness criteria" in saved["markdown"]
    assert "50.00%" in saved["markdown"] and "met" in saved["markdown"]
    assert saved["components"][0]["criteria_evaluation"] == summary["criteria_evaluation"]

    def independently_read_docx():
        data = render_archived_docx(saved)
        return MarkItDown().convert_stream(io.BytesIO(data), file_extension=".docx").text_content

    rendered = await asyncio.to_thread(independently_read_docx)
    for text in ("Frozen effectiveness criteria", "Synthetic criteria v1", "50.00%", "met", "not formal approval", "1.1.0"):
        assert text in rendered
    case = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, review(case, decision="fail"))
    latest = await repo.get_summary("owner", project, run["id"])
    assert latest["criteria_evaluation"]["status"] == "not_met"
    assert await archive.get_archive("owner", project, key) == saved


@pytest.mark.asyncio
async def test_v2_criteria_survive_separate_admission_worker_and_human_review(assessed, monkeypatch):
    summary_repo, _, project, _, plan, _, _ = assessed
    repo = ExecutionRepository(
        summary_repo.sf,
        policy=ExecutionPolicy(enabled=True, max_response_bytes=128),
        protection=summary_repo.protection,
        evidence_protection=summary_repo.evidence_protection,
        config_getter=lambda: SimpleNamespace(evaluation_http={"allowed_hosts": ["example.test"]}),
        clock_ms=summary_repo.clock_ms,
    )
    await repo.initialize()
    payload = ExecutionCreate.model_validate({"plan_id": plan["id"], "plan_hash": plan["definition_hash"], "confirmed": True, "target_authorized": True})
    admitted = await repo.admit("owner", project, uuid4().hex, payload)
    calls = []

    async def collect(request, *args):
        calls.append(request.to_request().body)
        assert "SYNTHETIC_INPUT" in calls[-1] and "GOLD" not in calls[-1]
        assert "acceptance_criteria" not in calls[-1]
        return AttemptObservation("output_collected", 200, 30, 1.0, "SYNTHETIC_ACTUAL")

    monkeypatch.setattr("app.evaluation.execution.collect_json_attempt", collect)
    assert await QAExecutionWorker(repo, repo.config_getter).run_once()
    state = await repo.get_execution("owner", project, admitted["id"])
    assert state["state"] == "collected" and len(calls) == 2
    before = await summary_repo.get_summary("owner", project, state["run_id"])
    assert before["criteria_evaluation"]["status"] == "incomplete"
    assert before["counts"]["unreviewed"] == 2
    for ordinal in (1, 2):
        case = await repo.open_case("owner", project, state["run_id"], ordinal)
        await repo.review_case("owner", project, state["run_id"], ordinal, review(case, decision="pass"))
    after = await summary_repo.get_summary("owner", project, state["run_id"])
    assert after["criteria_evaluation"]["status"] == "met"
    assert after["criteria_evaluation"]["criteria"] == plan["definition"]["acceptance_criteria"]
    assert after["acceptance"] == "not_approved"
    assert not await QAExecutionWorker(repo, repo.config_getter).run_once()
