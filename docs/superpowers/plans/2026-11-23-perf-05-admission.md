# PERF-05 Durable Performance Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PostgreSQL-first, owner-scoped admission transition for a frozen performance run without starting a worker or sending a real request.

**Architecture:** Keep `create_run` as an immutable ledger/materialization operation. Add an explicit `admit_run` transition from `created` to `running` that revalidates the frozen scenario/profile/manifest and records a durable `run_admitted` audit event in the same transaction. The endpoint is authorization-gated and confirmation-gated; it returns the existing run by the caller-supplied ID and remains safe to reconcile after an ambiguous response. Dispatch claim/start and transport remain separate and unchanged.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core, Alembic, PostgreSQL, pytest/asyncio.

**Spec:** `docs/DevPilot_AI性能测试工作台设计.md` sections 3, 5, 6, 9; `docs/DevPilot_Feature_Implementation_Spec.md` EXEC-01/EXEC-02; `docs/DevPilot_Agent_Contracts.md` unknown-delivery and owner/fence constraints.

## Global Constraints

- PostgreSQL is the default persistence backend; SQLite tests do not replace PostgreSQL migration/parity checks.
- Admission is not a network send, worker start, or target authorization; this slice has no real model/target calls.
- Only the owner/project/run binding may read or mutate the run; wrong owner and wrong project are indistinguishable from not-found.
- `created -> running` is the only new transition; repeated admission is idempotent for the same run and never appends a second admission audit.
- A failed or ambiguous write is reconciled with the original run ID; never auto-retry with a new ID or send a request.
- New audit actions and schema changes require additive PostgreSQL migration and SQLite migration-test parity.

---

### Task 1: Add the admission contract and failing repository/router tests

**Files:**
- Modify: `backend/app/evaluation/performance_scenarios.py`
- Modify: `backend/tests/test_performance_run_repository.py`
- Modify: `backend/tests/test_evaluation_performance_router.py`

**Interfaces:**
- `PerformanceRunAdmission(StrictDTO)` consumes `{confirmed: true}` and rejects all extra fields.
- `PerformanceRunRepository.admit_run(owner, project_id, run_id, *, confirmed)` returns the public run row with `status == "running"`.
- Repeated `admit_run` on the same `running` run returns the same run and does not add another `run_admitted` audit event.
- Admission of a missing, cross-owner, cross-project, tampered, or terminal run raises the repository's existing `NotFound`/`Conflict` errors.
- Gateway adds `POST /api/evaluation/projects/{project_id}/performance-runs/{run_id}/admit` and maps the existing errors without exposing private details.

- [ ] **Step 1: Write the failing model and repository tests**

Add tests that create a synthetic frozen scenario/run, call `admit_run(..., confirmed=True)`, assert `status == "running"`, assert the first dispatch remains `pending` with no `send_started_ns`, and assert the audit actions end in exactly one `run_admitted`. Add a repeated-admission assertion and a rejected `confirmed=False` assertion.

- [ ] **Step 2: Write the failing router tests**

Add an API test for `POST .../admit` with `confirmed=true`, then verify `GET` returns `running`; add a `confirmed=false` 422 case and a different actor 404 case. Keep the test synthetic and do not patch or call an HTTP client.

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```powershell
cd backend
uv run pytest tests/test_performance_run_repository.py -k admission -q
uv run pytest tests/test_evaluation_performance_router.py -k admission -q
```

Expected: failures because the DTO, repository method, route, and migration audit constraint do not yet exist.

### Task 2: Add the PostgreSQL-first admission audit migration

**Files:**
- Create: `backend/app/evaluation/migrations/versions/eval_0029_performance_admission.py`
- Modify: `backend/app/evaluation/tables.py`
- Modify: `backend/tests/test_evaluation_plans.py` and any schema-head expectation tests

**Interfaces:**
- Table metadata accepts `run_admitted` in `ck_evaluation_performance_run_audit_action`.
- Migration `eval_0029` has `down_revision = "eval_0028"`, changes only the audit action check, and downgrade restores the previous check.
- Existing rows and migration heads remain valid; no historical run is changed to `running` during upgrade.

- [ ] **Step 1: Update table metadata and add migration**

Extend the audit action check with `run_admitted`. Create the additive migration using `batch_alter_table`, dropping and recreating only the check constraint. Keep downgrade symmetric.

- [ ] **Step 2: Run migration/schema tests**

Run:

```powershell
cd backend
uv run pytest tests/test_evaluation_plans.py -k "migration or schema or head" -q
```

Expected: the migration head becomes `eval_0029`; no existing rows are modified.

### Task 3: Implement atomic idempotent admission

**Files:**
- Modify: `backend/app/evaluation/performance_run_repository.py`
- Modify: `backend/app/gateway/routers/evaluation_performance.py`

**Interfaces:**
- `admit_run` validates `confirmed is True`, locks the owner/project/run row, reloads the bound scenario, validates definition hash, profile, case order, and manifest with `PerformanceScenarioRepository._public` and `build_case_manifest`, then transitions only `created -> running`.
- On first transition, append `run_admitted` with `profile_hash`, `manifest_hash`, `population_count`, and `admission_version: "performance-admission.v1"`.
- On repeated admission of `running`, return the run without appending an audit event.
- `completed`, `interrupted`, and `failed` runs are rejected; dispatch rows are not mutated.
- Router uses existing permission decorators, `_require_human`, and maps `NotFound`, `Conflict`, and SQLAlchemy failures consistently with adjacent endpoints.

- [ ] **Step 1: Implement the minimum repository transition**

Use one transaction and `with_for_update` on the run row. Revalidate the immutable scenario before updating. Update only `status`; then append the audit event. Return `get_run` after commit.

- [ ] **Step 2: Implement the route and DTO wiring**

Use `PerformanceRunAdmission` as the request body. Do not add an automatic start, polling, dispatch claim, transport adapter, or model call.

- [ ] **Step 3: Run focused tests and verify GREEN**

Run:

```powershell
cd backend
uv run pytest tests/test_performance_run_repository.py -k admission -q
uv run pytest tests/test_evaluation_performance_router.py -k admission -q
```

Expected: all new admission tests pass and existing performance tests remain green.

### Task 4: Reconcile facts, finish verification, and record delivery

**Files:**
- Modify: `docs/DevPilot_Delivery_Status.md`
- Modify: `docs/DevPilot_实现进度与下一步.md`
- Modify: `docs/DevPilot_AI性能测试工作台设计.md`
- Modify: `docs/superpowers/plans/perf-04-dispatch-boundary.md`
- Modify: this plan file

**Interfaces:**
- Status docs cite the exact pre-push base SHA only until this slice is pushed; after push they record the new exact SHA and separate local results from SHA-specific Actions.
- PERF-04 is documented as merged durable dispatch boundary; PERF-05 is documented as admission-only and not a complete load-test loop.
- Remaining gaps stay explicit: worker lease consumption, transport, cancel/drain, metrics API, performance UI execution controls, and complete effect-result browser.

- [ ] **Step 1: Run all required verification**

Run the focused performance repository/router tests, backend Ruff, Blocking IO, migration/parity tests, and the complete backend offline suite required by the repository guide. Capture exact counts and failures; do not copy historical counts.

- [ ] **Step 2: Update docs from observed facts**

Update the current status headers, implementation matrix, PERF-04 plan checkboxes, and progress ledger with the actual changed files, test commands, branch, and commit SHA. Keep historical evidence labeled as historical.

- [ ] **Step 3: Commit and push the feature branch**

```powershell
git add backend/app/evaluation/performance_scenarios.py backend/app/evaluation/performance_run_repository.py backend/app/gateway/routers/evaluation_performance.py backend/app/evaluation/tables.py backend/app/evaluation/migrations/versions/eval_0029_performance_admission.py backend/tests docs
git commit -m "feat(perf): add durable run admission boundary"
git push -u origin feature/perf-05-admission
```

- [ ] **Step 4: Verify the exact pushed SHA**

Query GitHub Actions for the pushed commit SHA. Report the actual run conclusion; a push alone is not a passing CI result.

- [ ] **Step 5: Merge to main and clean only this slice**

After verification, update local `main` from `origin/main`, merge the feature branch with a non-fast-forward merge only if repository history policy requires it (otherwise fast-forward is acceptable when it preserves the reviewed commit), push `main`, then remove only `.worktrees/perf-05-admission` and the local/remote feature branch after confirming it is merged. Do not delete other worktrees or run global prune.
