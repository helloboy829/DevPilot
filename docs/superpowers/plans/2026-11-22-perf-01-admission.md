# PERF-01 Performance Scenario Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add owner-scoped, versioned performance scenarios that validate bounded load profiles and freeze an exact deterministic case-cycle manifest without executing requests.

**Architecture:** A scenario references an existing frozen performance QA plan, revalidates its immutable request/data bindings, and freezes profile, selected case scope, deterministic cycle manifest, and budgets in an App-owned PostgreSQL table. The API is read/write-only for scenario definitions; it does not create a run, dispatch, worker, or target request. Existing legacy `perf_run()` remains untouched and is not called.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async Core, Alembic evaluation migrations, pytest.

**Spec:** `docs/DevPilot_AI性能测试工作台设计.md` (PERF-01), `docs/DevPilot_Feature_Implementation_Spec.md` (PERF-01), and `docs/DevPilot_API接口设计文档.md`.

## Global Constraints

- PostgreSQL remains the default persistent backend; SQLite is test-only where explicitly configured.
- Bind scenario access to both authenticated owner and project; unknown or cross-owner identifiers fail closed.
- Freeze exact source IDs, revisions, hashes, selected case order and all load/budget limits; no mutable current-state lookups may silently alter a frozen scenario.
- Request count is finite even when duration is configured; duration is a first-limit stop condition, never an unlimited workload.
- Case cycling is deterministic and preserves every ordinal; duplicate case use does not collapse the unique source-case denominator.
- Require explicit confirmation on creation; no execution, scheduling, real model/target calls, or automatic retries in PERF-01.
- Keep response/reference plaintext out of scenario DTOs and logs; expected values are never used to construct performance inputs.
- Add migrations additively and prove SQLite/PostgreSQL schema parity and reversible downgrade.

---

### Task 1: Profile and deterministic manifest contract

**Files:**
- Create: `backend/app/evaluation/performance_scenarios.py`
- Test: `backend/tests/test_performance_scenarios.py`

**Interfaces:**
- `PerformanceProfile`: bounded concurrency, measured request count, warmup count, optional duration cap, request timeout, max in-flight, absolute wall-time deadline, drain limit, and request/response/total byte budgets.
- `build_case_manifest(case_ids, measured_count, warmup_count)`: return immutable ordinal records carrying phase, sample ID, and iteration; order input IDs lexically and cycle only after exhausting the frozen order.
- Profile validation rejects empty scope, duplicate/invalid IDs, overflows, count/deadline contradictions, and any configured cap exceeded by the profile.

**Steps:**
- [x] Write domain tests for stable ordering, exact ordinal coverage, cycle iteration, phase assignment, and overflow/bounds rejection.
- [x] Run the new tests and confirm they fail because the module does not exist.
- [x] Implement strict Pydantic DTOs and pure manifest builder.
- [x] Run domain tests and existing QA-plan tests.

### Task 2: Persist immutable owner-scoped scenario revisions

**Files:**
- Modify: `backend/app/evaluation/tables.py`
- Create: `backend/app/evaluation/migrations/versions/eval_0024_performance_scenarios.py`
- Create: `backend/app/evaluation/performance_scenario_repository.py`
- Test: `backend/tests/test_performance_scenario_repository.py`
- Test: migration parity coverage following `backend/tests/test_*migrations.py`

**Interfaces:**
- `create(owner, project_id, component_id, plan_id, payload)` verifies owner/project/component and frozen `performance` plan bindings, independently rechecks the plan hash, derives case IDs from the frozen dataset, builds and hashes the manifest, then inserts one immutable revision and an audit event in the same transaction.
- `list(owner, project_id, component_id)` returns bounded metadata only.
- `get(owner, project_id, scenario_id)` validates persisted DTO/hash and hides cross-owner existence.

**Steps:**
- [x] Write failing repository tests for owner isolation, wrong-mode/draft plan rejection, exact dataset/request hash binding, tamper detection, and audit atomicity.
- [x] Run new repository tests to establish RED.
- [x] Add table and `eval_0024` migration with bounded checks/FKs/indexes; implement repository methods.
- [x] Verify migration upgrade/downgrade and SQLite/PostgreSQL schema parity.
- [x] Run repository, datasets, and plans test modules.

### Task 3: Expose performance scenario API

**Files:**
- Create: `backend/app/gateway/routers/evaluation_performance.py`
- Modify: `backend/app/gateway/app.py`
- Test: `backend/tests/test_evaluation_performance_router.py`

**Interfaces:**
- `POST /api/evaluation/projects/{project_id}/components/{component_id}/performance-scenarios` creates a frozen scenario only after `confirmed: true`.
- `GET` on the collection lists scenarios; `GET .../{scenario_id}` reads a validated public projection.
- Reuse evaluation human identity, permission dependencies, bounded private routes, and existing stable 404/409/422 error semantics. Do not expose run/dispatch/evidence endpoints here.

**Steps:**
- [x] Write failing API tests for owner scope, permission, explicit confirmation, malformed profile, scenario creation/read, and absent execution side effects.
- [x] Run router tests to establish RED.
- [x] Implement routes and register the router.
- [x] Run router and relevant authorization regressions.

### Task 4: Record implementation and verify slice

**Files:**
- Modify: `docs/DevPilot_API接口设计文档.md`
- Modify: `docs/DevPilot_Feature_Implementation_Spec.md`
- Modify: `docs/DevPilot_AI性能测试工作台设计.md`
- Modify: `docs/DevPilot_实现进度与下一步.md`
- Modify: `docs/DevPilot_Delivery_Status.md`
- Modify: `docs/README.md`

**Steps:**
- [x] Update only the PERF-01 status and API/schema implementation facts; keep PERF-02/03/04 explicitly pending.
- [x] Run targeted tests, backend Blocking IO, Ruff, migration parity and the complete offline backend suite in the approved Linux/Python 3.12 environment.
- [x] Run `git diff --check`; inspect ignore rules and ensure formal plan/status/design docs remain tracked.
- [x] Commit this module slice, push its branch, integrate into `main`, push `main`, and record exact-SHA Actions terminal states. Push alone is not CI success.
- [x] Clean only this slice's temporary test/worktree resources after confirming their exact paths and state; preserve unrelated worktrees, Docker resources and user changes.
