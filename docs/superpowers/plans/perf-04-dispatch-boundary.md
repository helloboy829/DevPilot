# PERF-04 Dispatch Boundary Implementation Plan

> **For agentic workers:** Inline execution is authorized by the user’s “开始开发” instruction. Execute each step in order; do not add real-target calls.

**Goal:** Separate durable worker leasing, dispatch acknowledgement, and transport-start recording so no ledger row claims a request was sent before the one-way transport boundary.

**Architecture:** Keep execution authority and the durable ledger in `backend/app`; add a PostgreSQL-first additive migration for lease/fence metadata; make ACK create a stable dispatch/evidence ticket without starting measurement time; then require the current lease fence to transition that ticket to `send_started`. A stale worker must be unable to ACK, start, or observe a dispatch. No transport, retry, or production target is added in this slice.

**Tech Stack:** Python 3.12, FastAPI app repository, SQLAlchemy Core, Alembic, PostgreSQL (default), pytest/asyncio.

**Spec:** `docs/DevPilot_AI性能测试工作台设计.md` sections 3, 5, 6, 9; `docs/DevPilot_Agent_Contracts.md` unknown-delivery and fence constraints.

## Global Constraints

- PostgreSQL is the default persistence backend; SQLite tests do not replace PostgreSQL migration/parity checks.
- No real model or target calls; tests use isolated database fixtures.
- `claim` is not `send_started`; only a committed ACK ticket followed by a current-fence send transition permits transport.
- Once send may have started, unknown is reconciled read-only by the same IDs; never retry or re-issue.
- Keep owner/project/run scoping and append-only audit ordering.

---

### Task 1: Specify the durable dispatch boundary with regression tests

**Files:**
- Modify: `backend/tests/test_performance_run_repository.py`
- Modify: `backend/tests/test_evaluation_performance_router.py` only if public DTOs are changed

**Interfaces:**
- Produces repository behavior: `claim_dispatch(owner, project_id, run_id, ordinal, *, worker_id, lease_expires_at)` returns an opaque fence `{dispatch_id, worker_id, lease_epoch, lease_expires_at}`.
- Produces repository behavior: `acknowledge_dispatch(..., *, worker_id, lease_epoch, request_bytes=None, request_hash=None)` reserves stable dispatch/evidence identity but leaves `state=pending` and `send_started_ns=NULL`.
- Produces repository behavior: `start_dispatch(..., *, dispatch_id, worker_id, lease_epoch, send_started_ns)` atomically validates current fence and transitions pending ACK to dispatched.

- [ ] Add tests for lease claim and monotonically increasing fence epoch.
- [ ] Add tests that ACK has no send timestamp and cannot be counted in measurement summary.
- [ ] Add tests that start requires current fence and a unique ACK ticket.
- [ ] Add tests that stale epoch/worker and duplicate start are rejected without changing audit/ledger.
- [ ] Run the focused tests and record expected RED before implementation.

### Task 2: Add PostgreSQL-first lease/fence schema

**Files:**
- Create: `backend/app/evaluation/migrations/versions/eval_0028_performance_dispatch_fence.py`
- Modify: `backend/app/evaluation/tables.py`
- Modify: migration chain/revision tests as required

- [ ] Add nullable lease owner/deadline and nonnegative epoch with safe server defaults for existing rows.
- [ ] Add constraints/indexes for lease metadata; verify downgrade and metadata parity.
- [ ] Preserve historical dispatched rows as already-sent; do not infer lease ownership retroactively.

### Task 3: Implement atomic claim, ACK, and send-start transitions

**Files:**
- Modify: `backend/app/evaluation/performance_run_repository.py`
- Modify: `backend/tests/test_performance_run_repository.py`

- [ ] Claim under transaction/row lock, only while the run accepts dispatch and the ordinal is pending; expired/reclaimed leases increment epoch.
- [ ] ACK validates worker/epoch/deadline, reserves stable dispatch ID and response artifact manifest exactly once, and appends audit without setting `send_started_ns`.
- [ ] `start_dispatch` validates the same current fence and ACK ID, writes monotonic send start exactly once, and starts the measurement window only for first measurement send.
- [ ] Ensure interruption, observation, and metrics retain current unknown/not-started semantics; a sent or unknown row is never reclaimed for a second send.
- [ ] Run RED/GREEN focused tests and relevant router, repository, metrics, and migration tests.

### Task 4: Reconcile docs and verify

**Files:**
- Modify: `docs/DevPilot_AI性能测试工作台设计.md`
- Modify: `docs/DevPilot_Delivery_Status.md`
- Modify: `docs/DevPilot_实现进度与下一步.md`

- [ ] Correct the current-status header to cite the actual current main SHA, and distinguish latest-main CI from historical candidate evidence.
- [ ] Record this slice as repository boundary primitives only; do not claim worker/transport or full load testing exists.
- [ ] Run backend lint, full backend offline tests, Blocking IO, and PostgreSQL migration/parity tests; record exact outputs and SHA-specific Actions after push.
