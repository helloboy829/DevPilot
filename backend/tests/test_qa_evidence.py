"""Synthetic-only encrypted output evidence and append-only human review."""

import asyncio
import json
from dataclasses import replace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError
from test_dispatch_journal import prepared  # noqa: F401

from app.evaluation import tables as t
from app.evaluation.dispatch_journal import JournalLimits, JournalWriteUnconfirmed
from app.evaluation.evidence_protection import EvidenceProtection
from app.evaluation.qa_attempts import AttemptObservation
from app.evaluation.qa_evidence import EvidenceRepository, ReviewCreate
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtectionError


@pytest_asyncio.fixture
async def captured(prepared):  # noqa: F811
    original, engine, project, plan, clock = prepared
    repo = EvidenceRepository(original.sf, protection=original.protection, evidence_protection=EvidenceProtection(Fernet.generate_key()), clock_ms=lambda: clock["ms"])
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=30)
    yield repo, engine, project, plan, run, ticket, clock


def observation(**changes):
    return replace(AttemptObservation("output_collected", 200, 35, 10.0, "SYNTHETIC_OUTPUT"), **changes)


def review(case, **changes):
    return ReviewCreate.model_validate({"case_hash": case["case_hash"], "expected_revision": case["review_revision"], "decision": "pass", "note": "SYNTHETIC_REVIEW_NOTE", "confirmed": True, **changes})


@pytest.mark.asyncio
async def test_atomic_capture_is_encrypted_immutable_and_not_a_verdict(captured):
    repo, engine, project, plan, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    async with engine.connect() as conn:
        evidence = dict((await conn.execute(select(t.output_evidence))).mappings().one())
        assert "SYNTHETIC_OUTPUT" not in json.dumps(evidence)
        assert "SYNTHETIC_GOLD" not in json.dumps(evidence)
    with pytest.raises(Conflict):
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    assert case["input"] == "SYNTHETIC_INPUT"
    assert case["expected"] == "SYNTHETIC_GOLD"
    assert case["output"] == "SYNTHETIC_OUTPUT"
    assert case["review_revision"] == 0 and case["reviews"] == []
    assert case["component_name"] == "Synthetic"
    assert case["technical"]["kind"] == "output_collected"
    assert case["scope"] == "human_review_only"
    assert case["evidence_hash"] == evidence["protected_hash"]
    assert not any(key in case for key in ("accuracy", "verdict", "ttft", "passed"))
    metadata = await repo.list_cases("owner", project, run["id"])
    assert not any(value in json.dumps(metadata) for value in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT", "encrypted_payload", "ticket_hash"))
    assert metadata["cases"][0]["has_output_evidence"]
    assert metadata["cases"][0]["review_decision"] is None
    assert (await repo.list_runs("owner", project))[0]["id"] == run["id"]


@pytest.mark.asyncio
async def test_capture_and_observation_roll_back_together(captured, monkeypatch):
    repo, engine, project, _, run, ticket, _ = captured
    original = repo._journal_event

    async def fail(session, row, action, at, **kwargs):
        if action == "observation_recorded":
            raise RuntimeError("SYNTHETIC_TRANSACTION_FAILURE")
        await original(session, row, action, at, **kwargs)

    monkeypatch.setattr(repo, "_journal_event", fail)
    with pytest.raises(RuntimeError):
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.output_evidence))).all()
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "dispatched"


@pytest.mark.parametrize(
    "changes",
    [
        {"output": None},
        {"output": ""},
        {"output": " "},
        {"output": "x" * 129},
        {"output": "\ud800"},
        {"kind": "http_error", "http_status": 500, "body_bytes": 0},
        {"kind": "delivery_unknown"},
        {"body_bytes": True},
        {"elapsed_ms": float("nan")},
    ],
)
@pytest.mark.asyncio
async def test_rejects_inconsistent_sensitive_attempts_without_writes(captured, changes):
    repo, engine, project, _, run, ticket, _ = captured
    with pytest.raises((ValueError, Conflict)):
        await repo.record_attempt("owner", project, run["id"], ticket, observation(**changes))
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.output_evidence))).all()


@pytest.mark.parametrize("kind,status", [("http_error", 500), ("delivery_unknown", None), ("policy_rejected", None), ("invalid_output", 200)])
@pytest.mark.asyncio
async def test_technical_failure_never_creates_output_or_allows_pass(captured, kind, status):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation(kind=kind, http_status=status, body_bytes=0, output=None))
    case = await repo.open_case("owner", project, run["id"], 1)
    assert case["output"] is None and case["evidence_hash"] is None
    with pytest.raises(Conflict):
        await repo.review_case("owner", project, run["id"], 1, review(case))
    result = await repo.review_case("owner", project, run["id"], 1, review(case, decision="uncertain"))
    assert result["revision"] == 1


@pytest.mark.asyncio
async def test_append_only_review_requires_current_revision_and_encrypts_notes(captured):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    first = await repo.review_case("owner", project, run["id"], 1, review(case))
    assert first["revision"] == 1
    with pytest.raises(Conflict):
        await repo.review_case("owner", project, run["id"], 1, review(case))
    latest = await repo.open_case("owner", project, run["id"], 1)
    assert latest["reviews"][0]["note"] == "SYNTHETIC_REVIEW_NOTE"
    assert latest["review_revision"] == 1
    await repo.review_case("owner", project, run["id"], 1, review(latest, decision="fail", note="SYNTHETIC_CORRECTION"))
    after = await repo.open_case("owner", project, run["id"], 1)
    assert [row["decision"] for row in after["reviews"]] == ["pass", "fail"]
    assert after["review_revision"] == 2
    async with engine.connect() as conn:
        rows = [dict(row) for row in (await conn.execute(select(t.case_reviews))).mappings()]
        assert len(rows) == 2 and "SYNTHETIC_REVIEW_NOTE" not in json.dumps(rows) and "SYNTHETIC_CORRECTION" not in json.dumps(rows)
    listing = await repo.list_cases("owner", project, run["id"])
    assert listing["cases"][0]["review_decision"] == "fail"
    assert listing["counts"] == {"pass": 0, "fail": 1, "uncertain": 0, "unreviewed": 1}
    assert not any(key in listing for key in ("accuracy", "verdict", "passed"))


@pytest.mark.asyncio
async def test_other_owner_and_wrong_project_cannot_read_or_write(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    for operation in [
        repo.list_runs("other", project),
        repo.list_cases("other", project, run["id"]),
        repo.open_case("other", project, run["id"], 1),
        repo.review_case("other", project, run["id"], 1, review(case)),
        repo.record_attempt("other", project, run["id"], ticket, observation()),
        repo.open_case("owner", "wrong", run["id"], 1),
    ]:
        with pytest.raises(NotFound):
            await operation


@pytest.mark.parametrize("target", ["gold", "input", "sample_id", "plan", "ciphertext", "observation", "review_note"])
@pytest.mark.asyncio
async def test_tampering_fails_closed_without_exposing_values(captured, target):
    repo, engine, project, plan, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    if target == "review_note":
        case = await repo.open_case("owner", project, run["id"], 1)
        await repo.review_case("owner", project, run["id"], 1, review(case))
    async with engine.begin() as conn:
        if target == "gold":
            await conn.execute(update(t.references).values(expected="SYNTHETIC_TAMPER"))
        elif target == "input":
            await conn.execute(update(t.samples).values(input="SYNTHETIC_TAMPER"))
        elif target == "sample_id":
            await conn.execute(update(t.dispatches).where(t.dispatches.c.ordinal == 1).values(sample_id="z"))
        elif target == "plan":
            await conn.execute(update(t.plans).values(definition_hash="0" * 64))
        elif target == "ciphertext":
            await conn.execute(update(t.output_evidence).values(encrypted_payload="SYNTHETIC_TAMPER"))
        elif target == "observation":
            await conn.execute(update(t.dispatches).where(t.dispatches.c.ordinal == 1).values(http_status=201))
        else:
            await conn.execute(update(t.case_reviews).values(encrypted_payload="SYNTHETIC_TAMPER"))
    with pytest.raises((Conflict, RequestProtectionError)) as exc:
        await repo.open_case("owner", project, run["id"], 1)
    assert "SYNTHETIC" not in str(exc.value)


@pytest.mark.asyncio
async def test_rejected_and_stale_ticket_does_not_leave_evidence(captured):
    repo, engine, project, _, run, ticket, clock = captured
    clock["ms"] = ticket.expires_at_ms
    with pytest.raises(Conflict):
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.output_evidence))).all()


@pytest.mark.asyncio
async def test_observation_without_payload_is_explicitly_missing_not_passable(captured):
    from app.evaluation.dispatch_journal import TechnicalObservation

    repo, _, project, _, run, ticket, _ = captured
    await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="output_collected", http_status=200, body_bytes=20, elapsed_ms=1.0))
    case = await repo.open_case("owner", project, run["id"], 1)
    assert case["output"] is None and case["evidence_hash"] is None
    with pytest.raises(Conflict):
        await repo.review_case("owner", project, run["id"], 1, review(case))


@pytest.mark.parametrize(
    "changes",
    [
        {"confirmed": 1},
        {"confirmed": False},
        {"expected_revision": True},
        {"expected_revision": 100},
        {"case_hash": "bad"},
        {"decision": "automatic_pass"},
        {"note": " "},
        {"note": "\ud800"},
        {"note": "x" * 2001},
        {"expected": "SYNTHETIC_GOLD"},
    ],
)
def test_review_dto_rejects_unconfirmed_or_unbounded_input(changes):
    with pytest.raises(ValidationError):
        ReviewCreate.model_validate({"case_hash": "a" * 64, "expected_revision": 0, "decision": "pass", "note": "Synthetic", "confirmed": True, **changes})


@pytest.mark.asyncio
async def test_concurrent_review_from_two_sessions_has_one_winner(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    other = EvidenceRepository(repo.sf, protection=repo.protection, evidence_protection=repo.evidence_protection, clock_ms=repo.clock_ms)
    results = await asyncio.gather(repo.review_case("owner", project, run["id"], 1, review(case)), other.review_case("owner", project, run["id"], 1, review(case)), return_exceptions=True)
    assert sum(isinstance(row, dict) for row in results) == 1
    assert sum(isinstance(row, Conflict) for row in results) == 1


@pytest.mark.asyncio
async def test_public_metadata_queries_do_not_select_sensitive_columns(captured):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    queries = []

    def track(_conn, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", track)
    try:
        await repo.list_runs("owner", project)
        await repo.list_cases("owner", project, run["id"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", track)
    assert queries
    assert not any(word in " ".join(queries) for word in ("encrypted_payload", "ticket_hash", "evaluation_references", "evaluation_samples.input"))


@pytest.mark.asyncio
async def test_ambiguous_capture_commit_never_returns_success_or_overwrites(captured, monkeypatch):
    repo, _, project, _, run, ticket, _ = captured
    original = repo.sf

    class DropAfterCommit:
        def __call__(self):
            return original()

        def begin(self):
            class Context:
                async def __aenter__(self):
                    self.inner = original.begin()
                    return await self.inner.__aenter__()

                async def __aexit__(self, *args):
                    result = await self.inner.__aexit__(*args)
                    if args[0] is None:
                        raise DBAPIError("SYNTHETIC_SQL", {"payload": "SYNTHETIC_SECRET"}, Exception("SYNTHETIC_DISCONNECT"))
                    return result

            return Context()

    monkeypatch.setattr(repo, "sf", DropAfterCommit())
    with pytest.raises(JournalWriteUnconfirmed) as exc:
        await repo.record_attempt("owner", project, run["id"], ticket, observation())
    assert "SYNTHETIC" not in str(exc.value)
    monkeypatch.setattr(repo, "sf", original)
    assert (await repo.open_case("owner", project, run["id"], 1))["output"] == "SYNTHETIC_OUTPUT"
    with pytest.raises(Conflict):
        await repo.record_attempt("owner", project, run["id"], ticket, observation())


@pytest.mark.parametrize("change", [{"owner_id": "other"}, {"project_id": "other"}, {"run_id": "other"}, {"ordinal": 2}, {"sample_id": "other"}, {"plan_hash": "b" * 64}, {"observation_hash": "c" * 64}])
def test_protected_outputs_cannot_be_transplanted(change):
    protection = EvidenceProtection(Fernet.generate_key())
    binding = {"owner_id": "owner", "project_id": "project", "run_id": "run", "ordinal": 1, "sample_id": "sample", "plan_hash": "a" * 64, "observation_hash": "d" * 64}
    token = protection.seal("output", "SYNTHETIC_OUTPUT", binding)
    assert protection.open("output", token, binding) == "SYNTHETIC_OUTPUT"
    with pytest.raises(RequestProtectionError):
        protection.open("output", token, {**binding, **change})
    with pytest.raises(RequestProtectionError):
        protection.open("review", token, binding)


@pytest.mark.asyncio
async def test_successful_open_and_review_are_audited_without_content(captured):
    repo, _, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    await repo.review_case("owner", project, run["id"], 1, review(case))
    events = await repo.journal_audit("owner", project, run["id"])
    assert [row["sequence"] for row in events] == list(range(1, len(events) + 1))
    assert [row["action"] for row in events][-3:] == ["output_evidence_recorded", "review_case_opened", "human_review_recorded"]
    assert "SYNTHETIC_" not in json.dumps(events)


@pytest.mark.asyncio
async def test_review_rechecks_snapshot_after_decryption_before_commit(captured, monkeypatch):
    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    case = await repo.open_case("owner", project, run["id"], 1)
    original = repo._read_verified

    async def change_after_read(*args):
        snapshot, checked = await original(*args)
        async with engine.begin() as conn:
            await conn.execute(update(t.references).values(expected="SYNTHETIC_CHANGED_AFTER_READ"))
        return snapshot, checked

    monkeypatch.setattr(repo, "_read_verified", change_after_read)
    with pytest.raises(Conflict):
        await repo.review_case("owner", project, run["id"], 1, review(case))
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.case_reviews))).all()


@pytest.mark.asyncio
async def test_additive_migration_matches_metadata_and_preserves_harness(captured):
    from sqlalchemy import inspect

    from app.evaluation.schema import upgrade_evaluation_schema

    repo, engine, project, _, run, ticket, _ = captured
    await repo.record_attempt("owner", project, run["id"], ticket, observation())
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('synthetic_harness')"))
    await upgrade_evaluation_schema(engine)
    await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        for table in (t.output_evidence, t.case_reviews):
            columns = await conn.run_sync(lambda c: inspect(c).get_columns(table.name))
            assert {row["name"] for row in columns} == set(table.c.keys())
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0007"
        assert (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar_one() == "synthetic_harness"
    assert (await repo.open_case("owner", project, run["id"], 1))["output"] == "SYNTHETIC_OUTPUT"


@pytest.mark.parametrize("prepared", ["eval_0005"], indirect=True)
@pytest.mark.asyncio
async def test_deployed_eval_0005_upgrade_keeps_existing_dispatch_rows(prepared):  # noqa: F811
    from app.evaluation.schema import upgrade_evaluation_schema

    repo, engine, project, plan, _ = prepared
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=128, max_total_response_bytes=258))
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0005"
        before = [dict(row) for row in (await conn.execute(select(t.dispatches))).mappings()]
    await upgrade_evaluation_schema(engine)
    await upgrade_evaluation_schema(engine)
    evidence = EvidenceRepository(repo.sf, protection=repo.protection, evidence_protection=EvidenceProtection(Fernet.generate_key()), clock_ms=repo.clock_ms)
    async with engine.connect() as conn:
        assert [dict(row) for row in (await conn.execute(select(t.dispatches))).mappings()] == before
        assert not (await conn.execute(select(t.output_evidence))).all()
        assert not (await conn.execute(select(t.case_reviews))).all()
    await evidence.record_attempt("owner", project, run["id"], ticket, observation())
    assert (await evidence.open_case("owner", project, run["id"], 1))["output"] == "SYNTHETIC_OUTPUT"
