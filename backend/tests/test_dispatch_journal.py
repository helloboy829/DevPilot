"""Synthetic-only durable dispatch metadata; no HTTP, execution authority or verdict."""

import asyncio
import json
from dataclasses import replace

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.evaluation import tables as t
from app.evaluation.datasets import QASample, SourceDeclaration
from app.evaluation.dispatch_journal import DispatchJournalRepository, JournalLimits, TechnicalObservation
from app.evaluation.plans import PlanCreate
from app.evaluation.registry import ComponentLinkCreate
from app.evaluation.repository import Conflict, NotFound
from app.evaluation.request_protection import RequestProtection
from app.evaluation.request_versions import RequestVersionCreate
from app.evaluation.schema import upgrade_evaluation_schema
from deerflow.persistence.models import ComponentRow


@pytest_asyncio.fixture
async def prepared(tmp_path, request, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'journal.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: ComponentRow.__table__.create(conn))
    if getattr(request, "param", None) in {"eval_0004", "eval_0005"}:
        from app.evaluation import schema

        original = schema.command.upgrade
        monkeypatch.setattr(schema.command, "upgrade", lambda config, _revision: original(config, request.param))
        try:
            await upgrade_evaluation_schema(engine)
        finally:
            monkeypatch.setattr(schema.command, "upgrade", original)
    else:
        await upgrade_evaluation_schema(engine)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    clock = {"ms": 1_800_000_000_000}
    repo = DispatchJournalRepository(sf, protection=RequestProtection(Fernet.generate_key()), clock_ms=lambda: clock["ms"])
    async with sf.begin() as session:
        session.add(ComponentRow(id="source", user_id="owner", name="Synthetic", transport="http_post", api_url="https://example.test", validation_type="manual_review"))
    project = (await repo.create_project("owner", "Synthetic"))["id"]
    component = await repo.link_component("owner", project, ComponentLinkCreate(source_component_id="source", kind="llm"))
    version = await repo.create_request_version(
        "owner", project, component["id"], RequestVersionCreate(version_label="Synthetic", confirmed=True, request={"url": "https://example.test/SYNTHETIC_SECRET", "method": "POST", "headers": [], "body": '{"q":"placeholder"}'})
    )
    dataset = await repo.create_dataset("owner", project, "Synthetic", "acceptance", SourceDeclaration(label="Synthetic", reference="synthetic://local", authorization_basis="Synthetic test only", attested=True))
    changed = await repo.replace_samples("owner", project, dataset["id"], dataset["revision"], [QASample(sample_id=key, input="SYNTHETIC_INPUT", expected="SYNTHETIC_GOLD", source_ref="synthetic://local") for key in ("z", "a")])
    dataset = await repo.freeze("owner", project, dataset["id"], changed["revision"], changed["content_hash"])
    plan = await repo.create_plan(
        "owner",
        project,
        component["id"],
        PlanCreate.model_validate(
            {
                "version_label": "Synthetic",
                "request_version_id": version["id"],
                "request_protected_hash": version["protected_hash"],
                "dataset_id": dataset["id"],
                "dataset_revision": dataset["revision"],
                "dataset_hash": dataset["content_hash"],
                "binding": {"schema": "qa-json-binding.v1", "input_pointer": "/q", "output_pointer": "/a"},
                "response_mode": "json_text",
                "limits": {"mode": "effectiveness", "concurrency": 2, "request_count": 2, "timeout_ms": 1000, "wall_time_ms": 10000, "max_total_body_bytes": 10000},
                "confirmed": True,
            }
        ),
    )
    yield repo, engine, project, plan, clock
    await engine.dispose()


async def record(prepared, **limits):
    repo, _, project, plan, _ = prepared
    return await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=16, max_total_response_bytes=34, lease_grace_ms=100, **limits))


def observed(**changes):
    return TechnicalObservation(kind="output_collected", http_status=200, body_bytes=12, elapsed_ms=10.0, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_response_bytes": True},
        {"max_response_bytes": 0},
        {"max_response_bytes": 1048577},
        {"max_total_response_bytes": 1},
        {"max_total_response_bytes": 67108865},
        {"max_response_bytes": 16, "max_total_response_bytes": 16},
        {"lease_grace_ms": 99},
        {"lease_grace_ms": 30001},
        {"lease_grace_ms": "100"},
        {"confirmed": True},
    ],
)
def test_response_reservation_limits_are_strict(changes):
    with pytest.raises(ValidationError):
        JournalLimits.model_validate(changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "passed"},
        {"kind": "output_collected", "http_status": 500},
        {"kind": "output_collected", "body_bytes": 0},
        {"body_bytes": True},
        {"elapsed_ms": float("nan")},
        {"elapsed_ms": float("inf")},
        {"elapsed_ms": -1.0},
        {"output": "SYNTHETIC_SECRET"},
        {"ttft_ms": 1.0},
        {"http_status": True},
        {"kind": "policy_rejected", "http_status": 200},
    ],
)
def test_technical_dto_rejects_verdicts_secrets_invalid_metrics(changes):
    with pytest.raises(ValidationError):
        TechnicalObservation.model_validate({"kind": "output_collected", "http_status": 200, "body_bytes": 12, "elapsed_ms": 10.0, **changes})


@pytest.mark.asyncio
async def test_journal_records_sorted_ordinals_and_has_no_authority_or_gold(prepared):
    repo, _, project, plan, _ = prepared
    run = await record(prepared)
    assert run["scope"] == "dispatch_journal_only" and run["status"] == "recording"
    assert run["plan_hash"] == plan["definition_hash"]
    assert run["reserved_body_bytes"] == run["reserved_response_bytes"] == 0
    entries = await repo.list_dispatches("owner", project, run["id"])
    assert [(row["ordinal"], row["sample_id"], row["state"]) for row in entries] == [(1, "a", "pending"), (2, "z", "pending")]
    assert all("ticket_hash" not in row for row in entries)
    assert "SYNTHETIC" not in json.dumps([run, entries])
    assert (await repo.journal_audit("owner", project, run["id"]))[0]["action"] == "run_recorded"


@pytest.mark.asyncio
async def test_reservation_survives_restart_and_cannot_be_dispatched_twice(prepared):
    repo, engine, project, _, clock = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    assert ticket.sample_id == "a" and ticket.token not in repr(ticket)
    recovered = DispatchJournalRepository(async_sessionmaker(engine, expire_on_commit=False), clock_ms=lambda: clock["ms"])
    with pytest.raises(Conflict):
        await recovered.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    state = await recovered.get_journal("owner", project, run["id"])
    assert state["reserved_body_bytes"] == 20 and state["reserved_response_bytes"] == 17
    await recovered.record_observation("owner", project, run["id"], ticket, observed())
    rows = await recovered.list_dispatches("owner", project, run["id"])
    assert rows[0]["state"] == "observed" and rows[0]["kind"] == "output_collected"
    assert "output" not in rows[0]
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, observed())


@pytest.mark.asyncio
async def test_fenced_tickets_cannot_overwrite_another_attempt(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    for forged in (replace(ticket, token="0" * 32), replace(ticket, ordinal=2), replace(ticket, sample_id="z"), replace(ticket, expires_at_ms=1), replace(ticket, run_id="missing")):
        with pytest.raises(Conflict):
            await repo.record_observation("owner", project, run["id"], forged, observed())
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "dispatched"


@pytest.mark.asyncio
async def test_unknown_delivery_interrupts_all_pending_and_inflight_without_retry(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="delivery_unknown", http_status=None, body_bytes=0, elapsed_ms=1000.0))
    rows = await repo.list_dispatches("owner", project, run["id"])
    assert [row["state"] for row in rows] == ["delivery_unknown", "not_dispatched"]
    assert (await repo.get_journal("owner", project, run["id"]))["stop_reason"] == "delivery_unknown"
    with pytest.raises(Conflict):
        await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=20)


@pytest.mark.asyncio
async def test_expiry_ends_run_never_reclaims_slots_or_requeues_attempts(prepared):
    repo, _, project, _, clock = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    clock["ms"] = ticket.expires_at_ms
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, observed())
    with pytest.raises(Conflict):
        await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=20)
    assert await repo.interrupt_expired("owner", project, run["id"])
    assert not await repo.interrupt_expired("owner", project, run["id"])
    assert [row["state"] for row in await repo.list_dispatches("owner", project, run["id"])] == ["delivery_unknown", "not_dispatched"]


@pytest.mark.asyncio
async def test_deadline_without_dispatch_marks_all_not_dispatched(prepared):
    repo, _, project, _, clock = prepared
    run = await record(prepared)
    clock["ms"] = run["deadline_ms"]
    assert await repo.interrupt_expired("owner", project, run["id"])
    assert (await repo.get_journal("owner", project, run["id"]))["stop_reason"] == "deadline_expired"
    assert all(row["state"] == "not_dispatched" for row in await repo.list_dispatches("owner", project, run["id"]))


@pytest.mark.asyncio
async def test_response_budget_is_reserved_before_dispatch_and_not_recycled(prepared):
    repo, _, project, plan, _ = prepared
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=16, max_total_response_bytes=17, lease_grace_ms=100))
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    await repo.record_observation("owner", project, run["id"], ticket, observed())
    with pytest.raises(Conflict):
        await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=20)
    state = await repo.get_journal("owner", project, run["id"])
    assert state["reserved_response_bytes"] == 17 and state["reserved_body_bytes"] == 20


@pytest.mark.asyncio
async def test_body_budget_and_observation_limit_fail_closed(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    with pytest.raises(Conflict):
        await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=10001)
    assert (await repo.get_journal("owner", project, run["id"]))["reserved_body_bytes"] == 0
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="response_limit", http_status=200, body_bytes=18, elapsed_ms=10.0))
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "dispatched"


@pytest.mark.asyncio
async def test_technical_finish_is_not_quality_pass_and_terminal_rows_are_immutable(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    for ordinal in (1, 2):
        ticket = await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=20)
        await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="http_error", http_status=503, body_bytes=0, elapsed_ms=10.0))
    state = await repo.get_journal("owner", project, run["id"])
    assert state["status"] == "recording_finished" and "passed" not in state
    assert await repo.interrupt_journal("owner", project, run["id"]) == state
    assert (await repo.journal_audit("owner", project, run["id"]))[-1]["action"] == "run_recording_finished"


@pytest.mark.asyncio
async def test_owner_scope_applies_to_every_read_and_mutation(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    for operation in (
        repo.get_journal("other", project, run["id"]),
        repo.list_dispatches("other", project, run["id"]),
        repo.journal_audit("other", project, run["id"]),
        repo.record_dispatch("other", project, run["id"], 1, body_bytes=20),
        repo.interrupt_expired("other", project, run["id"]),
        repo.interrupt_journal("other", project, run["id"]),
    ):
        with pytest.raises(NotFound):
            await operation


@pytest.mark.asyncio
async def test_plan_hash_and_dataset_metadata_are_checked_without_decrypting(prepared, monkeypatch):
    repo, engine, project, plan, _ = prepared

    async def forbidden(*_args, **_kwargs):
        pytest.fail("Journal must not decrypt, read gold or send requests")

    monkeypatch.setattr(repo, "_open_request_row", forbidden)
    with pytest.raises(Conflict):
        await repo.record_run("owner", project, plan["id"], "0" * 64, JournalLimits())
    await record(prepared)
    async with engine.begin() as conn:
        await conn.execute(update(t.datasets).where(t.datasets.c.id == plan["dataset_id"]).values(revision=99))
    with pytest.raises(Conflict):
        await record(prepared)


@pytest.mark.asyncio
async def test_reads_and_writes_never_select_gold_ciphertext_or_input(prepared):
    repo, engine, project, _, _ = prepared
    statements = []

    def capture(_conn, _cursor, statement, *_args):
        statements.append(statement.lower())

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        run = await record(prepared)
        ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
        await repo.record_observation("owner", project, run["id"], ticket, observed())
        await repo.get_journal("owner", project, run["id"])
        await repo.list_dispatches("owner", project, run["id"])
        await repo.journal_audit("owner", project, run["id"])
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert all("evaluation_references" not in sql and "encrypted_payload" not in sql and "evaluation_samples.input" not in sql for sql in statements)


@pytest.mark.asyncio
async def test_cancel_with_inflight_and_pending_is_idempotent_and_not_replayable(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    first = await repo.interrupt_journal("owner", project, run["id"])
    assert first["status"] == "interrupted" and first["stop_reason"] == "cancelled"
    assert await repo.interrupt_journal("owner", project, run["id"]) == first
    assert [row["state"] for row in await repo.list_dispatches("owner", project, run["id"])] == ["delivery_unknown", "not_dispatched"]
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, observed())


@pytest.mark.asyncio
async def test_two_process_shaped_repositories_cannot_both_reserve_same_ordinal(prepared):
    repo, engine, project, _, clock = prepared
    run = await record(prepared)
    peer = DispatchJournalRepository(async_sessionmaker(engine, expire_on_commit=False), clock_ms=lambda: clock["ms"])
    results = await asyncio.gather(repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20), peer.record_dispatch("owner", project, run["id"], 1, body_bytes=20), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert (await repo.get_journal("owner", project, run["id"]))["reserved_response_bytes"] == 17


@pytest.mark.asyncio
async def test_journal_survives_repeat_migration(prepared):
    repo, engine, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    await upgrade_evaluation_schema(engine)
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "dispatched"
    await repo.record_observation("owner", project, run["id"], ticket, observed())
    async with engine.connect() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0006"


@pytest.mark.asyncio
async def test_audit_sequence_is_ordered_even_with_identical_timestamps(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    for ordinal in (1, 2):
        ticket = await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=20)
        await repo.record_observation("owner", project, run["id"], ticket, observed())
    audit = await repo.journal_audit("owner", project, run["id"])
    assert [row["sequence"] for row in audit] == list(range(1, 7))
    assert [row["action"] for row in audit] == ["run_recorded", "dispatch_recorded", "observation_recorded", "dispatch_recorded", "observation_recorded", "run_recording_finished"]


@pytest.mark.asyncio
async def test_failed_audit_rolls_back_dispatch_and_reservations(prepared, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

    repo, _, project, _, _ = prepared
    run = await record(prepared)

    async def fail(*_args, **_kwargs):
        raise IntegrityError("SYNTHETIC_SECRET", {}, Exception("SYNTHETIC_SECRET"))

    monkeypatch.setattr(repo, "_journal_event", fail)
    with pytest.raises(JournalWriteUnconfirmed) as error:
        await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    assert "SYNTHETIC" not in str(error.value)
    state = await repo.get_journal("owner", project, run["id"])
    assert state["reserved_response_bytes"] == state["reserved_body_bytes"] == 0
    assert all(row["state"] == "pending" for row in await repo.list_dispatches("owner", project, run["id"]))


@pytest.mark.asyncio
async def test_failed_observation_audit_does_not_overwrite_dispatch(prepared, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)

    async def fail(*_args, **_kwargs):
        raise IntegrityError("SYNTHETIC_SECRET", {}, Exception("SYNTHETIC_SECRET"))

    monkeypatch.setattr(repo, "_journal_event", fail)
    with pytest.raises(JournalWriteUnconfirmed):
        await repo.record_observation("owner", project, run["id"], ticket, observed())
    row = (await repo.list_dispatches("owner", project, run["id"]))[0]
    assert row["state"] == "dispatched" and row["kind"] is None


@pytest.mark.asyncio
async def test_same_owner_other_project_cannot_access_run_or_observe(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    other = (await repo.create_project("owner", "Other synthetic project"))["id"]
    with pytest.raises(NotFound):
        await repo.get_journal("owner", other, run["id"])
    with pytest.raises(NotFound):
        await repo.record_observation("owner", other, run["id"], ticket, observed())


@pytest.mark.asyncio
async def test_unused_budget_is_not_consumed_on_concurrent_duplicate_reservation(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    results = await asyncio.gather(*(repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20) for _ in range(5)), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert len(await repo.journal_audit("owner", project, run["id"])) == 2
    assert (await repo.get_journal("owner", project, run["id"]))["reserved_body_bytes"] == 20


@pytest.mark.parametrize("ordinal,body_bytes", [(True, 20), (0, 20), (10001, 20), (1, True), (1, 0), (1, "20"), (1, 262145)])
@pytest.mark.asyncio
async def test_strict_dispatch_parameters(prepared, ordinal, body_bytes):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    with pytest.raises(ValueError):
        await repo.record_dispatch("owner", project, run["id"], ordinal, body_bytes=body_bytes)
    assert (await repo.get_journal("owner", project, run["id"]))["reserved_body_bytes"] == 0


@pytest.mark.parametrize("offset,limit", [(True, 1), (-1, 1), (10001, 1), (0, True), (0, 0), (0, 201)])
@pytest.mark.asyncio
async def test_bounded_dispatch_pagination(prepared, offset, limit):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    with pytest.raises(ValueError):
        await repo.list_dispatches("owner", project, run["id"], offset=offset, limit=limit)


@pytest.mark.asyncio
async def test_dispatch_tokens_are_hashed_not_stored_in_plaintext(prepared):
    import hashlib

    repo, engine, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    async with engine.connect() as conn:
        digest = (await conn.execute(select(t.dispatches.c.ticket_hash).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.ordinal == 1))).scalar_one()
    assert digest != ticket.token and digest == hashlib.sha256(ticket.token.encode()).hexdigest()
    assert ticket.token not in json.dumps(await repo.list_dispatches("owner", project, run["id"]))


async def other_plan(prepared, **changes):
    repo, _, project, plan, _ = prepared
    fields = {key: plan["definition"][key] for key in PlanCreate.model_fields if key != "confirmed"}
    fields.update(version_label="Other synthetic plan", confirmed=True)
    fields["limits"] = {**fields["limits"], **changes}
    return await repo.create_plan("owner", project, plan["component_id"], PlanCreate.model_validate(fields))


@pytest.mark.asyncio
async def test_performance_cycle_is_fixed_by_python_sample_id_sort(prepared):
    repo, _, project, _, _ = prepared
    plan = await other_plan(prepared, mode="performance", request_count=5)
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    assert [row["sample_id"] for row in await repo.list_dispatches("owner", project, run["id"])] == ["a", "z", "a", "z", "a"]


@pytest.mark.asyncio
async def test_concurrency_cap_cannot_be_exceeded_by_two_repositories(prepared):
    repo, engine, project, _, clock = prepared
    plan = await other_plan(prepared, concurrency=1)
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    peer = DispatchJournalRepository(async_sessionmaker(engine, expire_on_commit=False), clock_ms=lambda: clock["ms"])
    results = await asyncio.gather(repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20), peer.record_dispatch("owner", project, run["id"], 2, body_bytes=20), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(row["state"] == "dispatched" for row in await repo.list_dispatches("owner", project, run["id"])) == 1


@pytest.mark.asyncio
async def test_response_budget_is_atomic_across_different_ordinals(prepared):
    repo, engine, project, plan, clock = prepared
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=16, max_total_response_bytes=17))
    peer = DispatchJournalRepository(async_sessionmaker(engine, expire_on_commit=False), clock_ms=lambda: clock["ms"])
    results = await asyncio.gather(repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20), peer.record_dispatch("owner", project, run["id"], 2, body_bytes=20), return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert (await repo.get_journal("owner", project, run["id"]))["reserved_response_bytes"] == 17


@pytest.mark.asyncio
async def test_observation_revalidates_bypassed_dto_and_exact_response_limit(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    with pytest.raises(ValidationError):
        await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation.model_construct(kind="passed", http_status=200, body_bytes=1, elapsed_ms=1.0))
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="output_collected", http_status=200, body_bytes=17, elapsed_ms=1.0))
    await repo.record_observation("owner", project, run["id"], ticket, TechnicalObservation(kind="response_limit", http_status=200, body_bytes=17, elapsed_ms=1.0))


@pytest.mark.asyncio
async def test_expiry_preserves_already_observed_attempts_and_fences_remaining(prepared):
    repo, _, project, _, clock = prepared
    run = await record(prepared)
    first = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    await repo.record_observation("owner", project, run["id"], first, observed())
    second = await repo.record_dispatch("owner", project, run["id"], 2, body_bytes=20)
    clock["ms"] = second.expires_at_ms
    assert await repo.interrupt_expired("owner", project, run["id"])
    rows = await repo.list_dispatches("owner", project, run["id"])
    assert [row["state"] for row in rows] == ["observed", "delivery_unknown"]
    assert rows[0]["kind"] == "output_collected"


@pytest.mark.parametrize("prepared", ["eval_0004"], indirect=True)
@pytest.mark.asyncio
async def test_deployed_eval_0004_upgrade_preserves_old_rows_and_harness_ledger(prepared):
    from sqlalchemy import inspect

    repo, engine, project, _, _ = prepared
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0004"
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('synthetic_harness')"))
        await conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT)"))
        await conn.execute(text("INSERT INTO users VALUES (1, 'synthetic@example.test', 'SYNTHETIC_HASH')"))
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        preserved = [name for name in names if name != "devpilot_alembic_version"]
        before = {name: (await conn.execute(text('SELECT * FROM "' + name + '"'))).all() for name in preserved}
    await upgrade_evaluation_schema(engine)
    await upgrade_evaluation_schema(engine)
    async with engine.connect() as conn:
        for name in preserved:
            assert (await conn.execute(text('SELECT * FROM "' + name + '"'))).all() == before[name]
        assert (await conn.execute(text("SELECT version_num FROM devpilot_alembic_version"))).scalar_one() == "eval_0006"
        assert not (await conn.execute(text("PRAGMA foreign_key_check"))).all()
    run = await record(prepared)
    assert len(await repo.list_dispatches("owner", project, run["id"])) == 2


@pytest.mark.asyncio
async def test_separate_os_processes_cannot_over_reserve_response_budget(prepared):
    import sys

    repo, engine, project, plan, clock = prepared
    run = await repo.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits(max_response_bytes=16, max_total_response_bytes=17))
    script = """import asyncio,json,sys
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.evaluation.dispatch_journal import DispatchJournalRepository,JournalWriteUnconfirmed
from app.evaluation.repository import Conflict
async def work():
 engine=create_async_engine(sys.argv[1])
 repo=DispatchJournalRepository(async_sessionmaker(engine,expire_on_commit=False),clock_ms=lambda:int(sys.argv[5]))
 try:
  await repo.record_dispatch('owner',sys.argv[2],sys.argv[3],int(sys.argv[4]),body_bytes=20)
  print(json.dumps({'reserved':True}))
 except (Conflict,JournalWriteUnconfirmed):
  print(json.dumps({'reserved':False}))
 finally:await engine.dispose()
asyncio.run(work())
"""
    children = []
    try:
        for ordinal in (1, 2):
            children.append(await asyncio.create_subprocess_exec(sys.executable, "-c", script, str(engine.url), project, run["id"], str(ordinal), str(clock["ms"]), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
        outputs = await asyncio.wait_for(asyncio.gather(*(child.communicate() for child in children)), timeout=60)
        assert all(child.returncode == 0 for child in children)
        assert sum(json.loads(stdout)["reserved"] for stdout, _stderr in outputs) == 1
    finally:
        for child in children:
            if child.returncode is None:
                child.terminate()
                await child.wait()
    state = await repo.get_journal("owner", project, run["id"])
    assert state["reserved_response_bytes"] == 17 and state["reserved_body_bytes"] == 20


@pytest.mark.asyncio
async def test_no_expired_lease_does_not_interrupt_or_mutate_revision(prepared):
    repo, _, project, _, _ = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    before = await repo.get_journal("owner", project, run["id"])
    assert not await repo.interrupt_expired("owner", project, run["id"])
    assert await repo.get_journal("owner", project, run["id"]) == before
    await repo.record_observation("owner", project, run["id"], ticket, observed())


@pytest.mark.asyncio
async def test_missing_sample_row_rejects_record_creation(prepared):
    from sqlalchemy import delete

    repo, engine, _, plan, _ = prepared
    async with engine.begin() as conn:
        await conn.execute(delete(t.references).where(t.references.c.dataset_id == plan["dataset_id"], t.references.c.sample_id == "a"))
        await conn.execute(delete(t.samples).where(t.samples.c.dataset_id == plan["dataset_id"], t.samples.c.sample_id == "a"))
    with pytest.raises(Conflict):
        await record(prepared)
    async with engine.connect() as conn:
        assert not (await conn.execute(select(t.dispatch_runs))).all()


@pytest.mark.asyncio
async def test_every_mutation_rolls_back_after_expired_fence(prepared):
    repo, _, project, _, clock = prepared
    run = await record(prepared)
    ticket = await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    before = await repo.get_journal("owner", project, run["id"])
    audit = await repo.journal_audit("owner", project, run["id"])
    clock["ms"] = ticket.expires_at_ms
    with pytest.raises(Conflict):
        await repo.record_observation("owner", project, run["id"], ticket, observed())
    assert await repo.get_journal("owner", project, run["id"]) == before
    assert await repo.journal_audit("owner", project, run["id"]) == audit


@pytest.mark.asyncio
async def test_expiry_lookup_index_matches_migrated_schema(prepared):
    from sqlalchemy import inspect

    _, engine, _, _, _ = prepared
    async with engine.connect() as conn:
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("evaluation_dispatches"))
    assert any(index["name"] == "ix_evaluation_dispatch_state_lease" and index["column_names"] == ["run_id", "state", "lease_expires_at_ms"] for index in indexes)
    assert any(index.name == "ix_evaluation_dispatch_state_lease" for index in t.dispatches.indexes)


@pytest.mark.asyncio
async def test_unconfirmed_commit_never_returns_a_ticket_or_releases_reservation(prepared):
    from contextlib import asynccontextmanager

    from sqlalchemy.exc import OperationalError

    from app.evaluation.dispatch_journal import JournalWriteUnconfirmed

    repo, _, project, _, _ = prepared
    run = await record(prepared)
    original = repo.sf

    class CommitThenDisconnect:
        @asynccontextmanager
        async def begin(self):
            async with original.begin() as session:
                yield session
            raise OperationalError("private SQL", {}, RuntimeError("private transport detail"))

    repo.sf = CommitThenDisconnect()
    try:
        with pytest.raises(JournalWriteUnconfirmed) as caught:
            await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
        assert str(caught.value) == "Journal write could not be confirmed"
    finally:
        repo.sf = original
    state = await repo.get_journal("owner", project, run["id"])
    assert state["reserved_body_bytes"] == 20
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "dispatched"
    with pytest.raises(Conflict):
        await repo.record_dispatch("owner", project, run["id"], 1, body_bytes=20)
    await repo.interrupt_journal("owner", project, run["id"])
    assert (await repo.list_dispatches("owner", project, run["id"]))[0]["state"] == "delivery_unknown"
