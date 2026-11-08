"""Synthetic same-benchmark retest archives; never target/model calls or approval."""

import asyncio
import json
import threading
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from test_dispatch_journal import prepared as prepared  # noqa: F401
from test_qa_evidence import captured as captured
from test_qa_evidence import review
from test_qa_report_archives import complete, completed_run

from app.evaluation import tables as t
from app.evaluation.plans import PlanCreate
from app.evaluation.qa_retests import RetestCreate, RetestRepository
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


def store(repo):
    return RetestRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)


async def pair(captured, **changes):
    first = await complete(captured)
    repo, _, project, plan, _, _, clock = captured
    settings = {key: plan["definition"][key] for key in PlanCreate.model_fields if key != "confirmed"}
    newer = await repo.create_plan("owner", project, plan["component_id"], PlanCreate.model_validate({**settings, "version_label": "Synthetic v2", "confirmed": True, **changes}))
    clock["ms"] += 1000
    second = await completed_run(repo, project, newer)
    return first, second


def request(first, second, **changes):
    return RetestCreate.model_validate({"baseline": {"run_id": first["run_id"], "summary_hash": first["summary_hash"]}, "retest": {"run_id": second["run_id"], "summary_hash": second["summary_hash"]}, "confirmed": True, **changes})


@pytest.mark.asyncio
async def test_frozen_per_sample_transitions_and_historical_receipt(captured):
    first, second = await pair(captured)
    repo, _, project, _, _, _, _ = captured
    repository, key = store(repo), uuid4().hex
    payload = request(first, second)
    saved = await repository.create_retest("owner", project, key, payload)
    assert saved["schema"] == "qa-retest-archive.v1"
    assert saved["scope"] == "same_benchmark_human_comparison" and saved["acceptance"] == "not_approved"
    assert saved["baseline"] == first and saved["retest"] == second
    assert saved["transitions"] == {"fail_to_pass": 1, "pass_to_fail": 0, "pass_to_pass": 1, "fail_to_fail": 0}
    assert saved["pass_rate_delta"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert len(saved["cases"]) == 2
    assert {row["sample_id"] for row in saved["cases"]} == {"a", "z"}
    assert all(len(row["baseline_case_hash"]) == 64 and row["baseline_revision"] == 1 for row in saved["cases"])
    assert not any(secret in json.dumps(saved) for secret in ("SYNTHETIC_INPUT", "SYNTHETIC_OUTPUT", "SYNTHETIC_GOLD", "SYNTHETIC_REVIEW_NOTE", "encrypted_payload", "reviewer_id"))
    assert await repository.create_retest("owner", project, key, payload) == saved
    case = await repo.open_case("owner", project, first["run_id"], 1)
    await repo.review_case("owner", project, first["run_id"], 1, review(case, decision="fail"))
    assert await repository.get_retest("owner", project, key) == saved
    assert await repository.create_retest("owner", project, key, payload) == saved
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, payload)
    listing = await repository.list_retests("owner", project)
    assert len(listing) == 1 and listing[0]["id"] == key
    assert not any(field in listing[0] for field in ("document", "cases", "baseline", "request_hash", "archive_hash", "owner_id"))


@pytest.mark.asyncio
async def test_regressions_and_all_samples_remain_in_denominator(captured):
    first, second = await pair(captured)
    repo, _, project, _, _, _, _ = captured
    for ordinal in (1, 2):
        case = await repo.open_case("owner", project, second["run_id"], ordinal)
        await repo.review_case("owner", project, second["run_id"], ordinal, review(case, decision="fail"))
    repository = store(repo)
    second = await repository.get_summary("owner", project, second["run_id"])
    saved = await repository.create_retest("owner", project, uuid4().hex, request(first, second))
    assert saved["transitions"] == {"fail_to_pass": 0, "pass_to_fail": 1, "pass_to_pass": 0, "fail_to_fail": 1}
    assert saved["pass_rate_delta"] == {"numerator": -1, "denominator": 2, "value": -0.5}
    assert saved["acceptance"] == "not_approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["binding", "dataset_purpose", "limits", "sample_order", "evaluation_policy", "preflight", "dataset_hash", "response_mode"])
async def test_benchmark_contract_is_exact(mismatch):
    # This pure comparison gate supplements full encrypted-source verification.
    from copy import deepcopy

    from app.evaluation.qa_retests import _same_benchmark

    definition = {
        key: {"synthetic": key} for key in ("project_id", "component_id", "dataset_id", "dataset_revision", "dataset_hash", "dataset_purpose", "binding", "limits", "response_mode", "sample_order", "evaluation_policy", "preflight")
    }
    other = deepcopy(definition)
    _same_benchmark(definition, other)
    other[mismatch] = "different"
    with pytest.raises(Conflict):
        _same_benchmark(definition, other)


@pytest.mark.asyncio
async def test_rejects_same_run_reversed_direction_same_plan_and_uncertain(captured):
    first, second = await pair(captured)
    repo, _, project, plan, _, _, clock = captured
    repository = store(repo)
    for payload in (request(first, first), request(second, first)):
        with pytest.raises(Conflict):
            await repository.create_retest("owner", project, uuid4().hex, payload)
    clock["ms"] += 1000
    same_plan = await completed_run(repo, project, plan)
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(first, same_plan))
    case = await repo.open_case("owner", project, second["run_id"], 1)
    await repo.review_case("owner", project, second["run_id"], 1, review(case, decision="uncertain"))
    second = await repository.get_summary("owner", project, second["run_id"])
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(first, second))


@pytest.mark.asyncio
async def test_owner_integrity_and_conflicting_id(captured):
    first, second = await pair(captured)
    repo, engine, project, _, _, _, _ = captured
    repository, key = store(repo), uuid4().hex
    await repository.create_retest("owner", project, key, request(first, second))
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, key, request(second, first))
    for action in (repository.get_retest("other", project, key), repository.list_retests("other", project), repository.create_retest("other", project, uuid4().hex, request(first, second))):
        with pytest.raises(NotFound):
            await action
    with pytest.raises(ValueError):
        await repository.get_retest("owner", project, "../bad")
    async with engine.begin() as conn:
        await conn.execute(update(t.retest_archives).where(t.retest_archives.c.id == key).values(document={"acceptance": "approved"}))
    with pytest.raises(RequestProtectionError):
        await repository.get_retest("owner", project, key)


@pytest.mark.asyncio
async def test_review_race_rechecks_both_runs_and_does_not_append(captured, monkeypatch):
    first, second = await pair(captured)
    repo, engine, project, _, _, _, _ = captured
    repository = store(repo)
    entered, release = threading.Event(), threading.Event()
    original = SummaryRepository._verify_summary

    def verify(*args):
        assert threading.current_thread() is not threading.main_thread()
        result = original(*args)
        entered.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(SummaryRepository, "_verify_summary", staticmethod(verify))
    task = asyncio.create_task(repository.create_retest("owner", project, uuid4().hex, request(first, second)))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        case = await repo.open_case("owner", project, second["run_id"], 1)
        await repo.review_case("owner", project, second["run_id"], 1, review(case, decision="fail"))
    finally:
        release.set()
    with pytest.raises(Conflict):
        await task
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.retest_archives))).scalar_one() == 0
        assert (await conn.execute(select(func.count()).select_from(t.dispatch_audit).where(t.dispatch_audit.c.action == "retest_archived"))).scalar_one() == 0


@pytest.mark.asyncio
async def test_audits_and_comparison_are_atomic(captured, monkeypatch):
    first, second = await pair(captured)
    repo, engine, project, _, _, _, _ = captured
    repository = store(repo)
    original = repository._journal_event
    calls = []

    async def fail(session, run, action, at, **kwargs):
        calls.append(run["id"])
        await original(session, run, action, at, **kwargs)
        if len(calls) == 2:
            raise Conflict

    monkeypatch.setattr(repository, "_journal_event", fail)
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(first, second))
    assert calls == sorted([first["run_id"], second["run_id"]])
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.retest_archives))).scalar_one() == 0
        assert (await conn.execute(select(func.count()).select_from(t.dispatch_audit).where(t.dispatch_audit.c.action == "retest_archived"))).scalar_one() == 0


@pytest.mark.parametrize("changes", [{"confirmed": 1}, {"confirmed": False}, {"metrics": {"pass_rate": 1}}, {"baseline": {"run_id": "bad", "summary_hash": "a" * 64}}])
def test_strict_input(changes):
    with pytest.raises(ValidationError):
        request({"run_id": "a" * 32, "summary_hash": "b" * 64}, {"run_id": "c" * 32, "summary_hash": "d" * 64}, **changes)


@pytest.mark.parametrize("prepared", ["eval_0008"], indirect=True)
@pytest.mark.asyncio
async def test_additive_upgrade_preserves_reports_all_prior_rows_and_harness(captured):
    from test_qa_report_archives import archives, payload

    from app.evaluation.schema import upgrade_evaluation_schema

    first = await complete(captured)
    repo, engine, project, _, _, _, _ = captured
    saved = await archives(repo).create_archive("owner", project, uuid4().hex, payload(first))
    preserved = [table for table in t.metadata.sorted_tables if table is not t.retest_archives]
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('synthetic_harness')"))
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0008"
        before = {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in preserved}
    await upgrade_evaluation_schema(engine)
    await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        assert {table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()] for table in preserved} == before
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0009"
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "synthetic_harness"
    assert await archives(repo).get_archive("owner", project, saved["id"]) == saved


@pytest.mark.asyncio
async def test_changed_run_budgets_clock_and_stale_viewed_hash_are_rejected(captured):
    first, second = await pair(captured)
    repo, engine, project, _, _, _, _ = captured
    repository = store(repo)
    stale = {**first, "summary_hash": "0" * 64}
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(stale, second))
    async with engine.begin() as conn:
        row = dict((await conn.execute(select(t.dispatch_runs).where(t.dispatch_runs.c.id == second["run_id"]))).mappings().one())
        await conn.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == row["id"]).values(max_total_response_bytes=row["max_total_response_bytes"] + 1))
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(first, second))
    async with engine.begin() as conn:
        baseline_run = dict((await conn.execute(select(t.dispatch_runs).where(t.dispatch_runs.c.id == first["run_id"]))).mappings().one())
        await conn.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == row["id"]).values(max_total_response_bytes=row["max_total_response_bytes"], started_at_ms=baseline_run["finished_at_ms"]))
    with pytest.raises(Conflict):
        await repository.create_retest("owner", project, uuid4().hex, request(first, second))


@pytest.mark.asyncio
async def test_distinct_component_or_frozen_dataset_never_comparable(captured):
    from app.evaluation.datasets import QASample, SourceDeclaration
    from app.evaluation.registry import ComponentLinkCreate
    from app.evaluation.request_versions import RequestVersionCreate

    first, _ = await pair(captured)
    repo, _, project, plan, _, _, clock = captured
    repository = store(repo)
    from deerflow.persistence.models import ComponentRow

    async with repo.sf.begin() as session:
        session.add(ComponentRow(id="source-other", user_id="owner", name="Synthetic other", transport="http_post", api_url="https://example.test", validation_type="manual_review"))
    component = await repo.link_component("owner", project, ComponentLinkCreate(source_component_id="source-other", kind="cv"))
    version = await repo.create_request_version(
        "owner", project, component["id"], RequestVersionCreate(version_label="Synthetic other", confirmed=True, request={"url": "https://example.test/other", "method": "POST", "headers": [], "body": '{"q":"placeholder"}'})
    )
    dataset = await repo.create_dataset("owner", project, "Synthetic other data", "acceptance", SourceDeclaration(label="Synthetic", reference="synthetic://local", authorization_basis="Synthetic", attested=True))
    dataset = await repo.replace_samples("owner", project, dataset["id"], dataset["revision"], [QASample(sample_id=key, input="SYNTHETIC_INPUT", expected="SYNTHETIC_GOLD", source_ref="synthetic://local") for key in ("a", "z")])
    dataset = await repo.freeze("owner", project, dataset["id"], dataset["revision"], dataset["content_hash"])
    settings = {key: plan["definition"][key] for key in PlanCreate.model_fields if key != "confirmed"}
    for comp, changes in (
        (component["id"], {"request_version_id": version["id"], "request_protected_hash": version["protected_hash"]}),
        (plan["component_id"], {"dataset_id": dataset["id"], "dataset_revision": dataset["revision"], "dataset_hash": dataset["content_hash"]}),
    ):
        other = await repo.create_plan("owner", project, comp, PlanCreate.model_validate({**settings, **changes, "version_label": "Synthetic other", "confirmed": True}))
        clock["ms"] += 1000
        summary = await completed_run(repo, project, other)
        with pytest.raises(Conflict):
            await repository.create_retest("owner", project, uuid4().hex, request(first, summary))


@pytest.mark.asyncio
async def test_database_error_is_unconfirmed_and_no_partial_append(captured, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

    first, second = await pair(captured)
    repo, engine, project, _, _, _, _ = captured
    repository = store(repo)

    async def fail(*args, **kwargs):
        raise OperationalError("SYNTHETIC_PRIVATE_SQL", {}, Exception("SYNTHETIC_PRIVATE_DATABASE"))

    monkeypatch.setattr(repository, "_journal_event", fail)
    with pytest.raises(JournalWriteUnconfirmed) as failure:
        await repository.create_retest("owner", project, uuid4().hex, request(first, second))
    assert "SYNTHETIC_PRIVATE" not in str(failure.value)
    async with engine.connect() as conn:
        assert (await conn.execute(select(func.count()).select_from(t.retest_archives))).scalar_one() == 0
