# EFF-01 Results API Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Implement owner-scoped effectiveness result list, summary, paged cases, and metadata-only case detail.

**Architecture:** Preserve `/review-runs`. Add a dedicated result query service/DTOs and read-only `/runs` routes. Queries use frozen plan/dataset samples as denominator and join evidence by run+ordinal. Cursor HMAC uses a purpose-derived key from stable `AUTH_JWT_SECRET`, never the evidence encryption key. Result version covers only owner-visible projections, not independent blind-review decisions.

**Execution status (2026-11-20):** The uncommitted candidate contains the cursor primitive, four read-only routes and synthetic regression tests. `list_runs` now loads run/plan metadata and all owner-visible dispatch/reference metadata in set-based queries, derives a project-wide cursor version from that complete visible state, filters and keyset-pages run metadata, then builds full summaries only for the returned page. This removes full case projection per historical run while preserving stale-cursor detection for changes outside the current page. The query-count regression compares 5 versus 10 historical runs at a fixed page size and passes. Result API/cursor/router tests pass (25 passed); Ruff lint/format checks pass. EFF-01 remains incomplete: `list_cases` and `get_case` still build every case projection before filtering/pagination; `list_runs` still scans all run/evidence metadata to compute a complete cross-page version; full module verification and task checkboxes are not reconciled. Do not describe this as fully bounded data-volume pagination. See [module progress](../../DevPilot_实现进度与下一步.md) and [delivery evidence](../../DevPilot_Delivery_Status.md).

**2026-11-20 follow-up:** Artifact reconciliation now advances the run-local result revision transactionally. Case pages use SQL keyset/filter/count queries over frozen sample IDs with window ordinals, and case detail resolves existence/rank with targeted SQL; only the requested page is evidence-projected. A before/after run revision check rejects a page if its visible run state changes during projection. Six related backend test files pass (157 passed) in the isolated Linux source copy; Ruff check/format and touched-file diff check pass. PostgreSQL parity, complete-suite execution and historical run metadata scaling remain open.

**Tech Stack:** Python 3.12, FastAPI, async SQLAlchemy Core, Pydantic, pytest; SQLite/PostgreSQL compatible.

**Spec:** `docs/DevPilot_效果测试工作台设计.md` sections 3, 7; `docs/DevPilot_API接口设计文档.md` effectiveness mapping.

## Global Constraints

- Owner isolation; inaccessible project/run/case returns existing 404 boundary.
- Frozen sample membership fixes `total`; missing/mismatched dispatch slots remain blockers, never reduce the denominator or fabricate evidence.
- List/detail never decrypt input, expected, output, request/response bodies, or reviewer notes.
- Never expose independent blind-review decisions, identities, notes, task state, or hidden revisions.
- Cursor binds actor, project, resource, normalized filters, limit, ordering key, run snapshot and owner-visible result version.
- Malformed/tampered/cross-filter cursor: 422. Valid cursor with changed visible snapshot: 409.
- Synthetic tests only; no real model/target calls. Do not disturb existing dirty worktree changes.

## File Map

- Add `backend/app/evaluation/qa_result_cursor.py`: typed binding, canonical encoding, HMAC, validation.
- Add `backend/app/evaluation/qa_results.py`: owner-scoped queries, fixed denominator, filters/counts, result versions, DTO projection.
- Modify `backend/app/gateway/routers/evaluation_projects.py`: add `/runs`, `/runs/{run_id}`, `/runs/{run_id}/cases`, `/runs/{run_id}/cases/{case_id}`; preserve legacy routes.
- Add `backend/tests/test_qa_result_cursor.py`, `test_qa_results.py`, `test_qa_results_router.py`.
- Update progress and delivery docs only with observed facts.

## Task 1: Cursor Primitive

Interfaces: `encode_cursor(payload, secret) -> str`; `decode_cursor(token, secret, expected_binding) -> payload`. Invalid syntax/signature/version/binding raises `InvalidResultCursor`; stale visible snapshot is checked by the query service and raises `StaleResultCursor`. Derive HMAC key with HMAC-SHA256(`AUTH_JWT_SECRET`, `devpilot:effectiveness-results-cursor:v1`).

- [ ] Test round-trip; token tampering; wrong actor/project/resource/filter/limit; bounded input; operation with `DEVPILOT_REQUEST_ENCRYPTION_KEY` absent.
- [ ] Run `cd backend; uv run pytest -q tests/test_qa_result_cursor.py`; observe expected missing-module failures.
- [ ] Implement strict versioned base64url/JSON parser, canonical binding, constant-time signature comparison, bounded token size.
- [ ] Re-run cursor tests and auth config/evidence protection tests.

## Task 2: Result Queries and DTOs

Interfaces: `ResultRepository(sf).list_runs(owner, project_id, filters, limit, cursor)`, `get_run(owner, project_id, run_id)`, `list_cases(owner, project_id, run_id, filters, limit, cursor)`, `get_case(owner, project_id, run_id, case_id)`.

- [ ] Test frozen two-case run with one missing slot; both count in `total`, missing slot reports blocker, and evidence remains absent.
- [ ] Test mismatched dispatch sample ID, distinct counting, filter changes to `matched_total` but not `total`, and same-time stable run ordering.
- [ ] Test owner isolation, metadata-only DTOs, and that free-text/reference/hidden blind fields are not accepted as filters.
- [ ] Run `cd backend; uv run pytest -q tests/test_qa_results.py`; observe expected failures.
- [ ] Implement left-side frozen sample projection; join dispatch/artifact/extracted-evidence metadata and owner-visible legacy review/assessment only by run+ordinal. Never decrypt.
- [ ] Keep rows/counts/version in one read transaction; count distinct frozen ordinals. Hash immutable plan/dataset/sample identity for `snapshot_hash`; hash only owner-visible projection fields for result version.
- [ ] Re-run result tests plus existing QA evidence, assessment, and review-task tests.

## Task 3: Pagination and Staleness

- [ ] Test default limit 50, bounds 1-200, first/next/final pages, ordinal order, run order `(started_at_ms DESC, run_id ASC)`, and no gaps/duplicates.
- [ ] Test cross-run/filter/limit cursor gives 422; owner-visible result change gives 409; independent blind-task-only change does not invalidate owner cursor.
- [ ] Test empty filter result returns `matched_total=0` without changing `total` or verdict/blockers.
- [ ] Implement limit+1; issue `next_cursor` only when another row exists, bound to the last returned row.
- [ ] Run cursor and repository tests together.

## Task 4: HTTP Contract

- [ ] Test unauthenticated 401, owner success, cross-owner 404, invalid cursor 422, stale cursor 409, and `private, no-store` headers.
- [ ] Assert responses exclude synthetic input, gold, extracted output, raw bodies, notes, blind decisions and reviewer identities.
- [ ] Add four read-only routes with existing permission/context helpers; never accept client owner ID. Sanitize cursor/database errors.
- [ ] Run `cd backend; uv run pytest -q tests/test_qa_results_router.py tests/test_qa_evidence_router.py tests/test_evaluation_projects_router.py`.

## Task 5: Gates and Ledger

- [ ] Run focused QA domain/router suite, `make lint`, `make test-blocking-io`, and `git diff --check` using repository commands.
- [ ] Fix attributable failures without weakening assertions or editing unrelated changes.
- [ ] Update module ledger and delivery status with exact commands/results; keep EFF-02/03, commit SHA CI, deployment and acceptance distinct.

## Self-Review

EFF-01 must not invent assessment/PASS where DAT-02/ASMT-01 evidence is absent. Blind task results remain in assignment APIs until an explicit reveal contract permits projection. No cursor may depend on encryption-key availability.
