# Persistent Performance Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add an owner-scoped durable cancel request for admitted performance runs, with bounded synthetic-worker drain and no resend semantics.

**Architecture:** Persist the request as a `cancel_requested` run lifecycle state plus one append-only audit event, atomically fencing later dispatch operations. The synthetic worker polls that durable state, stops admissions, drains already-fenced requests, and lets unresolved fences become unknown under existing safety rules. Expose one authenticated human-only endpoint; do not add scheduling or automatic execution.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, pytest, Ruff.

**Spec:** `docs/DevPilot_Performance_Cancellation.md`

## Global Constraints

- Work only in the isolated `feature/perf-persistent-cancel` worktree.
- Preserve owner/project/run scoping, append-only audit, immutable request identities, and cancellation idempotency.
- Cancellation means requested, not worker death or completed drain; never resend an unknown request.
- Keep all execution synthetic-only; no real model/target calls, deployment, or new scheduler.
- Write and observe a failing regression before production changes; do not relax assertions or test budgets.
- Update module contract, docs index, and delivery status with verified facts only.

---

### Task 1: Repository lifecycle and migration

**Files:**
- Modify: `backend/app/evaluation/tables.py`
- Create: `backend/app/evaluation/migrations/versions/eval_0031_performance_cancel_request.py`
- Modify: `backend/app/evaluation/performance_run_repository.py`
- Test: `backend/tests/test_performance_run_repository.py`
- Test: `backend/tests/test_performance_run_ledger_migrations.py`

**Interfaces:**
- Produce `request_cancel(owner, project_id, run_id, *, confirmed)` returning the owner-scoped run receipt.
- Produce `cancellation_requested(owner, project_id, run_id) -> bool` for the worker.
- Lifecycle status `cancel_requested` plus one `run_cancel_requested` audit event atomically fences later claims, ACKs, send starts, and completion.

- [x] Add failing repository tests for owner isolation, confirmed-only requests, cancellation idempotency, lifecycle conflicts, dispatch fencing, and completion race.
- [x] Run those tests and verify expected assertion failures.
- [x] Add migration + schema constraints and minimum repository implementation.
- [x] Run focused repository and migration tests.

### Task 2: Worker observes and drains cancellation

**Files:**
- Modify: `backend/app/evaluation/performance_worker.py`
- Modify: `backend/app/evaluation/performance_run_repository.py`
- Test: `backend/tests/test_performance_worker.py`

**Interfaces:**
- Worker checks `cancellation_requested` before each dispatch fence and at bounded intervals while waiting on in-flight tasks.
- Cancellation uses the existing drain bound; no new dispatch after observation; unresolved fenced requests are unknown, never retried.

- [x] Add failing async regressions for no-late-admission, successful in-flight drain/evidence, cancellation during a delayed request, and drain timeout/unknown behavior.
- [x] Verify they fail for the intended missing behavior.
- [x] Implement the minimal coordinator polling/stop/drain path and atomic completion fence.
- [x] Run focused worker tests and Blocking IO tests.

### Task 3: Owner-scoped API

**Files:**
- Modify: `backend/app/evaluation/performance_scenarios.py`
- Modify: `backend/app/gateway/routers/evaluation_performance.py`
- Test: `backend/tests/test_evaluation_performance_router.py`

- [x] Add failing API tests for human + write/review checks, foreign-owner 404, invalid confirmation, accepted request, and idempotent replay.
- [x] Verify expected failures.
- [x] Implement DTO and POST route using existing private error mapping.
- [x] Run focused route tests.

### Task 4: Contracts and complete verification

**Files:**
- Modify: `docs/DevPilot_Execution_Safety_Contract.md`
- Modify: `docs/README.md`
- Modify: `docs/DevPilot_Delivery_Status.md`

- [x] Document requested-vs-drained semantics, monotonic fence, and no-resend rule.
- [x] Run focused worker/repository/router/migration tests, Blocking IO, Ruff, format, and diff checks.
- [x] Run the complete frozen Linux/Python 3.12 offline backend suite; record the observed test results. The candidate remains uncommitted, so no resulting source SHA exists yet.
- [x] Inspect exact worktree diff/status.
- [ ] Obtain independent code review before integration.
