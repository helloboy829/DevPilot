"""Synthetic-only owner-scoped effectiveness result projections."""

import pytest
from sqlalchemy import delete, event, insert, update

from app.evaluation import tables as t
from app.evaluation.dispatch_journal import JournalLimits, TechnicalObservation
from app.evaluation.qa_result_cursor import InvalidResultCursor
from app.evaluation.qa_results import ResultRepository, StaleResultCursor
from app.evaluation.repository import NotFound

pytest_plugins = ("test_dispatch_journal",)


@pytest.mark.asyncio
async def test_frozen_denominator_keeps_missing_and_mismatched_dispatch_slots(prepared):
    journal, engine, project, plan, _ = prepared
    run = await journal.record_run(
        "owner",
        project,
        plan["id"],
        plan["definition_hash"],
        JournalLimits(),
    )

    async with engine.begin() as connection:
        await connection.execute(
            delete(t.response_artifacts).where(
                t.response_artifacts.c.run_id == run["id"],
                t.response_artifacts.c.ordinal == 1,
            )
        )
        await connection.execute(
            delete(t.dispatches).where(
                t.dispatches.c.run_id == run["id"],
                t.dispatches.c.ordinal == 1,
            )
        )
        await connection.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.ordinal == 2).values(sample_id="not-in-frozen-dataset"))

    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    page = await repository.list_cases("owner", project, run["id"], limit=50)

    assert page["total"] == 2
    assert page["matched_total"] == 2
    assert [case["case_id"] for case in page["items"]] == ["a", "z"]
    assert [case["ordinal"] for case in page["items"]] == [1, 2]
    assert [case["integrity_status"] for case in page["items"]] == ["missing_dispatch", "sample_mismatch"]
    assert all(case["dispatch_state"] is None for case in page["items"])
    assert all(case["response_evidence"] is None for case in page["items"])

    detail = await ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret").get_run("owner", project, run["id"])
    assert detail["total"] == 2
    assert detail["technical_counts"] == {"missing_dispatch": 1, "sample_mismatch": 1}
    assert "dispatch_integrity_incomplete" in detail["blockers"]


@pytest.mark.asyncio
async def test_result_queries_preserve_project_owner_boundary(prepared):
    journal, _, project, plan, _ = prepared
    run = await journal.record_run(
        "owner",
        project,
        plan["id"],
        plan["definition_hash"],
        JournalLimits(),
    )
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")

    with pytest.raises(NotFound):
        await repository.list_cases("another-owner", project, run["id"], limit=50)


@pytest.mark.asyncio
async def test_case_filter_preserves_denominator_and_cursor_pages_without_gaps(prepared):
    journal, _, project, plan, _ = prepared
    run = await journal.record_run(
        "owner",
        project,
        plan["id"],
        plan["definition_hash"],
        JournalLimits(),
    )
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")

    empty = await repository.list_cases("owner", project, run["id"], filters={"kind": "no-such-kind"})
    assert empty["total"] == 2
    assert empty["matched_total"] == 0
    assert empty["items"] == []

    first = await repository.list_cases("owner", project, run["id"], limit=1)
    second = await repository.list_cases("owner", project, run["id"], limit=1, cursor=first["next_cursor"])
    assert [first["items"][0]["ordinal"], second["items"][0]["ordinal"]] == [1, 2]
    assert second["next_cursor"] is None

    with pytest.raises(InvalidResultCursor):
        await repository.list_cases("owner", project, run["id"], limit=2, cursor=first["next_cursor"])


@pytest.mark.asyncio
async def test_case_page_and_detail_project_only_requested_frozen_samples(prepared, monkeypatch):
    journal, engine, project, plan, _ = prepared
    run = await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    observed = []
    project_page = repository._case_projection

    async def record_projection(session, run_row, dataset, case_rows, snapshot_hash):
        observed.append(tuple(case_rows))
        return await project_page(session, run_row, dataset, case_rows, snapshot_hash)

    statements = []

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        if "evaluation_samples" in statement:
            statements.append(statement.lower())

    monkeypatch.setattr(repository, "_case_projection", record_projection)
    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        first = await repository.list_cases("owner", project, run["id"], limit=1)
        second = await repository.list_cases("owner", project, run["id"], limit=1, cursor=first["next_cursor"])
        page_queries = list(statements)
        statements.clear()
        detail = await repository.get_case("owner", project, run["id"], "z")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)

    assert observed == [((1, "a"),), ((2, "z"),), ((2, "z"),)]
    assert first["items"][0]["case_id"] == "a"
    assert second["items"][0]["case_id"] == detail["case_id"] == "z"
    assert second["result_version"] == detail["result_version"]
    assert sum("limit" in sql and "ordinal >" in sql for sql in page_queries) == 2
    assert all("count(" in sql or "limit" in sql for sql in page_queries)
    assert any("sample_id =" in sql for sql in statements)
    assert not any("order by evaluation_samples.sample_id" in sql for sql in statements)


@pytest.mark.asyncio
async def test_case_filters_match_before_limit_and_hide_mismatched_dispatch_metadata(prepared):
    journal, engine, project, plan, _ = prepared
    run = await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    async with engine.begin() as connection:
        await connection.execute(delete(t.references).where(t.references.c.dataset_id == plan["dataset_id"], t.references.c.sample_id == "z"))
        await connection.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"]).values(state="observed", kind="output_collected", http_status=200, elapsed_ms=8.0, body_bytes=12))
        await connection.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.ordinal == 1).values(sample_id="not-in-frozen-dataset"))
    statements = []

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        if "evaluation_samples" in statement:
            statements.append(statement.lower())

    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    event.listen(engine.sync_engine, "before_cursor_execute", record_sql)
    try:
        page = await repository.list_cases("owner", project, run["id"], filters={"kind": "output_collected", "http_status": 200, "reference_status": "absent"}, limit=1)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", record_sql)
    assert page["total"] == 2
    assert page["matched_total"] == 1
    assert [item["ordinal"] for item in page["items"]] == [2]
    assert page["next_cursor"] is None
    filtered = [sql for sql in statements if "http_status" in sql and "evaluation_references" in sql]
    assert any("count(" in sql for sql in filtered)
    assert any("limit" in sql for sql in filtered)
    untrusted = await repository.list_cases("owner", project, run["id"], filters={"integrity_status": "sample_mismatch", "http_status": 200})
    assert untrusted["matched_total"] == 0


@pytest.mark.asyncio
async def test_case_page_rejects_revision_change_during_projection(prepared, monkeypatch):
    journal, _, project, plan, _ = prepared
    run = await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    project_page = repository._case_projection

    async def advance_revision(*args):
        result = await project_page(*args)
        await journal.record_dispatch("owner", project, run["id"], 2, body_bytes=10)
        return result

    monkeypatch.setattr(repository, "_case_projection", advance_revision)
    with pytest.raises(StaleResultCursor):
        await repository.list_cases("owner", project, run["id"], limit=1)


@pytest.mark.asyncio
async def test_case_cursor_becomes_stale_when_visible_projection_changes(prepared):
    journal, engine, project, plan, _ = prepared
    run = await journal.record_run(
        "owner",
        project,
        plan["id"],
        plan["definition_hash"],
        JournalLimits(),
    )
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    first = await repository.list_cases("owner", project, run["id"], limit=1)

    async with engine.begin() as connection:
        await connection.execute(update(t.dispatches).where(t.dispatches.c.run_id == run["id"], t.dispatches.c.ordinal == 2).values(state="observed", kind="output_collected", http_status=200, elapsed_ms=8.0, body_bytes=12))
        await connection.execute(update(t.dispatch_runs).where(t.dispatch_runs.c.id == run["id"]).values(revision=t.dispatch_runs.c.revision + 1))

    with pytest.raises(StaleResultCursor):
        await repository.list_cases("owner", project, run["id"], limit=1, cursor=first["next_cursor"])


@pytest.mark.asyncio
async def test_case_cursor_binds_run_and_filters_but_ignores_blind_task_changes(prepared):
    journal, engine, project, plan, _ = prepared
    first_run = await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    second_run = await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    first_page = await repository.list_cases("owner", project, first_run["id"], limit=1)
    cursor = first_page["next_cursor"]
    assert cursor is not None

    with pytest.raises(InvalidResultCursor):
        await repository.list_cases("owner", project, first_run["id"], filters={"kind": "output_collected"}, limit=1, cursor=cursor)
    with pytest.raises(InvalidResultCursor):
        await repository.list_cases("owner", project, second_run["id"], limit=1, cursor=cursor)

    async with engine.begin() as connection:
        await connection.execute(
            insert(t.review_tasks).values(
                id="a" * 32,
                owner_id="owner",
                project_id=project,
                run_id=first_run["id"],
                ordinal=1,
                case_hash="b" * 64,
                subject_hash="c" * 64,
                definition={"blind_decision": "SYNTHETIC_HIDDEN_DECISION"},
                round=1,
                revision=1,
                status="queued",
                created_at_ms=1,
            )
        )

    second_page = await repository.list_cases("owner", project, first_run["id"], limit=1, cursor=cursor)
    assert [item["ordinal"] for item in second_page["items"]] == [2]
    assert "SYNTHETIC_HIDDEN_DECISION" not in repr(second_page)


@pytest.mark.asyncio
async def test_run_list_and_detail_are_metadata_only_and_keep_frozen_denominator(prepared):
    journal, _, project, plan, _ = prepared
    run = await journal.record_run(
        "owner",
        project,
        plan["id"],
        plan["definition_hash"],
        JournalLimits(),
    )
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")

    page = await repository.list_runs("owner", project)
    assert page["total"] == 1
    assert page["matched_total"] == 1
    assert page["items"][0]["run_id"] == run["id"]
    assert page["items"][0]["case_count"] == 2
    assert "next_cursor" not in page or page["next_cursor"] is None

    detail = await repository.get_run("owner", project, run["id"])
    assert detail["run_id"] == run["id"]
    assert detail["total"] == 2
    assert detail["technical_counts"] == {"pending": 2}
    assert "collection_not_finished" in detail["blockers"]
    serialized = repr({"page": page, "detail": detail})
    for secret in ("SYNTHETIC_INPUT", "SYNTHETIC_GOLD", "SYNTHETIC_OUTPUT"):
        assert secret not in serialized


@pytest.mark.asyncio
async def test_run_list_uses_stable_keyset_order_and_metadata_filters(prepared):
    journal, _, project, plan, _ = prepared
    runs = [await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits()) for _ in range(3)]
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")

    page = await repository.list_runs("owner", project, filters={"status": "recording"}, limit=1)
    observed = [page["items"][0]["run_id"]]
    while page["next_cursor"] is not None:
        page = await repository.list_runs("owner", project, filters={"status": "recording"}, limit=1, cursor=page["next_cursor"])
        observed.extend(item["run_id"] for item in page["items"])

    expected = sorted(run["id"] for run in runs)
    assert observed == expected
    assert page["total"] == page["matched_total"] == 3
    empty = await repository.list_runs("owner", project, filters={"status": "interrupted"})
    assert empty["total"] == 3
    assert empty["matched_total"] == 0
    assert empty["items"] == []
    assert empty["next_cursor"] is None


@pytest.mark.asyncio
async def test_run_list_query_count_does_not_grow_per_run(prepared):
    journal, engine, project, plan, _ = prepared
    for _ in range(5):
        await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    statements = []

    def count_selects(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        page = await repository.list_runs("owner", project, limit=2)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)
    five_run_query_count = len(statements)

    for _ in range(5):
        await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    statements.clear()
    event.listen(engine.sync_engine, "before_cursor_execute", count_selects)
    try:
        larger_page = await repository.list_runs("owner", project, limit=2)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_selects)

    assert page["total"] == 5
    assert larger_page["total"] == 10
    assert len(statements) == five_run_query_count


@pytest.mark.asyncio
async def test_run_list_filters_and_limits_candidates_in_sql(prepared):
    journal, engine, project, plan, _ = prepared
    for _ in range(4):
        await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits())
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    run_selects = []

    def capture_run_selects(connection, cursor, statement, parameters, context, executemany):
        normalized = statement.lower()
        if normalized.lstrip().startswith("select") and "evaluation_dispatch_runs" in normalized:
            run_selects.append(normalized)

    event.listen(engine.sync_engine, "before_cursor_execute", capture_run_selects)
    try:
        page = await repository.list_runs("owner", project, filters={"status": "recording"}, limit=1)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_run_selects)

    assert page["total"] == page["matched_total"] == 4
    assert len(page["items"]) == 1
    assert any(" limit " in f" {statement} " for statement in run_selects)
    assert any("status" in statement and "where" in statement for statement in run_selects)


@pytest.mark.asyncio
async def test_run_list_rejects_revision_change_during_page_projection(prepared, monkeypatch):
    journal, _, project, plan, _ = prepared
    runs = [await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits()) for _ in range(2)]
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    project_summary = repository._run_summary_projection
    changed = False

    async def write_during_projection(session, owner, project_id, run, plan_row):
        nonlocal changed
        result = await project_summary(session, owner, project_id, run, plan_row)
        if not changed:
            changed = True
            ticket = await journal.record_dispatch("owner", project_id, runs[-1]["id"], 1, body_bytes=20)
            await journal.record_observation(
                "owner",
                project_id,
                runs[-1]["id"],
                ticket,
                TechnicalObservation(kind="output_collected", http_status=200, elapsed_ms=8.0, body_bytes=12),
            )
        return result

    monkeypatch.setattr(repository, "_run_summary_projection", write_during_projection)
    with pytest.raises(StaleResultCursor):
        await repository.list_runs("owner", project, limit=1)



@pytest.mark.asyncio
async def test_run_cursor_becomes_stale_when_a_visible_run_changes(prepared):
    journal, engine, project, plan, _ = prepared
    runs = [await journal.record_run("owner", project, plan["id"], plan["definition_hash"], JournalLimits()) for _ in range(3)]
    repository = ResultRepository(journal.sf, cursor_secret="synthetic-result-cursor-secret")
    first = await repository.list_runs("owner", project, limit=1)
    assert first["next_cursor"] is not None

    ticket = await journal.record_dispatch("owner", project, runs[-1]["id"], 1, body_bytes=20)
    await journal.record_observation(
        "owner",
        project,
        runs[-1]["id"],
        ticket,
        TechnicalObservation(kind="output_collected", http_status=200, elapsed_ms=8.0, body_bytes=12),
    )

    with pytest.raises(StaleResultCursor):
        await repository.list_runs("owner", project, limit=1, cursor=first["next_cursor"])
