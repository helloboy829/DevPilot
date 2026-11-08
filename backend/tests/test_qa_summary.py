"""Verified fixed-denominator human summaries; synthetic data only."""

import asyncio
import json

import pytest
from sqlalchemy import delete, select, update
from test_dispatch_journal import prepared as prepared  # noqa: F401
from test_qa_evidence import captured as captured
from test_qa_evidence import observation, review

from app.evaluation import tables as t
from app.evaluation.qa_summary import SummaryRepository
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


def summaries(repo):
    return SummaryRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)


async def decide(repo, project, run, ordinal=1, decision="pass"):
    case = await repo.open_case("owner", project, run["id"], ordinal)
    await repo.review_case("owner", project, run["id"], ordinal, review(case, decision=decision))


@pytest.mark.asyncio
async def test_fixed_denominator_includes_unreviewed_and_no_silent_pass(captured):
    repo, _, project, plan, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    await decide(repo, project, run)
    summary = await summaries(repo).get_summary("owner", project, run["id"])
    assert summary["schema"] == "qa-human-summary.v1"
    assert summary["counts"] == {"pass": 1, "fail": 0, "uncertain": 0, "unreviewed": 1}
    assert summary["human_pass_rate"] == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert summary["readiness"] == "provisional"
    assert summary["technical_counts"] == {"collected": 1, "other": 1}
    assert summary["plan_hash"] == plan["definition_hash"]
    assert summary["acceptance"] == "not_approved"
    assert not any(word in json.dumps(summary) for word in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "SYNTHETIC_REVIEW_NOTE", "encrypted_payload", "reviewer_id", "ttft"))
    assert (await summaries(repo).get_summary("owner", project, run["id"]))["summary_hash"] == summary["summary_hash"]


@pytest.mark.asyncio
async def test_latest_revision_only_uncertain_never_excluded_and_hash_changes(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    await decide(repo, project, run)
    first = await summaries(repo).get_summary("owner", project, run["id"])
    await decide(repo, project, run, decision="uncertain")
    changed = await summaries(repo).get_summary("owner", project, run["id"])
    assert changed["counts"] == {"pass": 0, "fail": 0, "uncertain": 1, "unreviewed": 1}
    assert changed["human_pass_rate"]["denominator"] == 2
    assert changed["human_pass_rate"]["value"] == 0
    assert first["summary_hash"] != changed["summary_hash"]


@pytest.mark.asyncio
async def test_complete_review_is_not_acceptance_or_a_stored_report(captured):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    second = await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=30)
    await repo.record_attempt("owner", project, run["id"], second, observation())
    await decide(repo, project, run)
    await decide(repo, project, run, 2, "fail")
    result = await summaries(repo).get_summary("owner", project, run["id"])
    assert result["run_status"] == "recording_finished"
    assert result["readiness"] == "review_complete"
    assert result["human_pass_rate"]["value"] == 0.5
    assert result["acceptance"] == "not_approved"
    async with engine.connect() as conn:
        actions = list((await conn.execute(select(t.dispatch_audit.c.action))).scalars())
    assert actions.count("human_summary_opened") == 1


@pytest.mark.parametrize("damage", ["output", "decision", "review_gap", "dispatch_gap", "dataset", "ordinal", "forged_pass"])
@pytest.mark.asyncio
async def test_tampered_sources_never_contribute_to_summary(captured, damage):
    repo, engine, project, plan, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    await decide(repo, project, run)
    async with engine.begin() as conn:
        if damage == "output":
            await conn.execute(update(t.output_evidence).values(encrypted_payload="SYNTHETIC_CORRUPTION"))
        elif damage == "decision":
            await conn.execute(update(t.case_reviews).values(decision="fail"))
        elif damage == "review_gap":
            await conn.execute(update(t.case_reviews).values(revision=2))
        elif damage == "dispatch_gap":
            await conn.execute(delete(t.dispatches).where(t.dispatches.c.ordinal == 2))
        elif damage == "dataset":
            await conn.execute(update(t.references).values(expected="SYNTHETIC_CHANGED_GOLD"))
        elif damage == "ordinal":
            await conn.execute(update(t.dispatches).where(t.dispatches.c.ordinal == 2).values(sample_id="a"))
        else:
            await conn.execute(delete(t.output_evidence))
    with pytest.raises((Conflict, RequestProtectionError)):
        await summaries(repo).get_summary("owner", project, run["id"])


@pytest.mark.asyncio
async def test_owner_and_project_scope_and_unavailable_key(captured):
    repo, _, project, _, run, _, _ = captured
    with pytest.raises(NotFound):
        await summaries(repo).get_summary("other", project, run["id"])
    other = await repo.create_project("owner", "Synthetic other")
    with pytest.raises(NotFound):
        await summaries(repo).get_summary("owner", other["id"], run["id"])


@pytest.mark.asyncio
async def test_verification_runs_off_loop_and_concurrent_change_rejects_stale_snapshot(captured, monkeypatch):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    summary_repo = summaries(repo)
    original = summary_repo._verify_summary
    reached = asyncio.Event()
    release = asyncio.Event()
    actual_to_thread = asyncio.to_thread

    async def delayed(function, *args, **kwargs):
        if function == original:
            reached.set()
            await release.wait()
        return await actual_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", delayed)
    task = asyncio.create_task(summary_repo.get_summary("owner", project, run["id"]))
    await asyncio.wait_for(reached.wait(), 5)
    await decide(repo, project, run)
    release.set()
    with pytest.raises(Conflict):
        await task
    async with engine.connect() as conn:
        assert "human_summary_opened" not in list((await conn.execute(select(t.dispatch_audit.c.action))).scalars())


@pytest.mark.asyncio
async def test_technical_failure_and_missing_review_keep_full_denominator(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation(kind="http_error", http_status=500, body_bytes=0, output=None))
    second = await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=30)
    await repo.record_attempt("owner", project, run["id"], second, observation())
    await decide(repo, project, run, 1, "fail")
    result = await summaries(repo).get_summary("owner", project, run["id"])
    assert result["human_pass_rate"] == {"numerator": 0, "denominator": 2, "value": 0}
    assert result["technical_counts"] == {"collected": 1, "other": 1}
    assert result["readiness"] == "provisional"
    assert result["blockers"] == ["technical_incomplete", "unreviewed"]


@pytest.mark.asyncio
async def test_performance_repetitions_cannot_masquerade_as_effectiveness(captured):
    from app.evaluation.dispatch_journal import JournalLimits
    from app.evaluation.plans import PlanCreate

    repo, _, project, plan, _, _, _ = captured
    definition = plan["definition"]
    fields = {name: definition[name] for name in PlanCreate.model_fields if name != "confirmed"}
    fields.update(version_label="Synthetic performance", confirmed=True, limits={**definition["limits"], "mode": "performance", "request_count": 4})
    perf = await repo.create_plan("owner", project, plan["component_id"], PlanCreate.model_validate(fields))
    run = await repo.record_run("owner", project, perf["id"], perf["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=516))
    with pytest.raises(Conflict):
        await summaries(repo).get_summary("owner", project, run["id"])


@pytest.mark.asyncio
async def test_shared_gold_verification_is_once_per_summary_and_off_event_loop(captured, monkeypatch):
    import threading

    from app.evaluation import qa_evidence

    repo, _, project, _, run, _, _ = captured
    original = qa_evidence._verified_inputs
    loop_thread = threading.get_ident()
    calls = []

    def verify(*args):
        assert threading.get_ident() != loop_thread
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(qa_evidence, "_verified_inputs", verify)
    result = await summaries(repo).get_summary("owner", project, run["id"])
    assert calls == [1]
    assert result["counts"]["unreviewed"] == 2
