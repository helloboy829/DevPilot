# PERF-08 Dataset-backed Performance Workload Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each synthetic performance dispatch use the exact request body rendered from the run's frozen plan and dataset case, preserving repeat-cycle mapping without reading expected answers or sending network traffic.

**Architecture:** Extend the owner-scoped run snapshot loader to revalidate the immutable scenario, plan, request version and frozen dataset metadata; decrypt the request version only inside the repository boundary; render one `FrozenRequest` per case using the existing QA JSON binding; and pass its body to the explicitly synthetic worker. Keep credentials and request values in memory only, preserve durable request-body hash/byte accounting, and keep all transport restricted to the built-in synthetic adapter in this slice.

**Tech Stack:** Python 3.12, FastAPI-domain repository, SQLAlchemy async, Pydantic, `devpilot.qa_json_binding.QAJSONBinding`, pytest/pytest-asyncio, Ruff.

**Spec:** `docs/DevPilot_AI性能测试工作台设计.md` (sections 1, 5, 6, 9; PERF-07 acceptance boundary).

## Global Constraints

- PostgreSQL is the production-default persistent backend; SQLite is test-only.
- App may depend on DevPilot core; shared core must not import `app.*`.
- Do not read/use expected answers in the workload builder; bind only frozen case inputs.
- Do not persist raw request bodies or credentials; expose neither in public DTOs, audit events, logs, errors or test output.
- This slice remains synthetic-only: no HTTP client, socket, subprocess, background poller, real destination or model invocation.
- Preserve the frozen ordinal/case/iteration manifest, concurrency and byte budgets, ACK/send fence, evidence identity and unknown/no-resend semantics.
- Do not label synthetic latency as target/model performance or metrics.

---

## Files and responsibilities

- Modify `backend/app/evaluation/performance_run_repository.py`: owner-scoped snapshot verification, request-version decryption/audit, dataset-input lookup, deterministic `QAJSONBinding` rendering and request-budget validation.
- Modify `backend/app/evaluation/performance_worker.py`: select rendered body by frozen manifest `case_id`; send it only to `SyntheticPerformanceTransport`; retain ordinal only as synthetic failure-control metadata.
- Modify `backend/tests/test_performance_worker.py`: assert dataset-cycle body mapping, repeated-case stability, hash/byte evidence and absence of gold/credential disclosure.
- Modify `backend/tests/test_performance_run_repository.py`: reject stale/mismatched frozen request/dataset inputs and enforce request-byte budgets before worker dispatch.
- Update `docs/DevPilot_AI性能测试工作台设计.md`, `docs/DevPilot_Delivery_Status.md`, and `docs/DevPilot_实现进度与下一步.md` with the verified boundary and remaining real-worker/UI gap.

## Task 1: Prove the worker currently ignores frozen workload inputs

- [x] Add a regression to `backend/tests/test_performance_worker.py` that monkeypatches `SyntheticPerformanceTransport.request` to capture bodies, runs an admitted scenario with known frozen case inputs, and asserts the body sent per ordinal contains the rendered input (including repeated cycles).
- [x] Assert only the non-secret body hash/byte count is recorded and the response evidence remains linked to the same ordinal/dispatch.
- [x] Run `uv run pytest tests/test_performance_worker.py::test_worker_sends_rendered_frozen_case_body -q` from `backend`; expected RED because the worker currently emits a synthetic ordinal JSON document rather than rendered case data.

## Task 2: Build frozen case requests inside the repository boundary

- [x] Extend `PerformanceRunRepository.get_execution_snapshot` to revalidate the run/scenario hash and profile/manifest as today, then owner-scope the linked frozen plan, dataset, samples and protected request version.
- [x] Verify the plan definition hash and bindings agree with scenario `plan_hash`, `dataset_id`, `dataset_revision`, `dataset_hash`, component and performance request count. Verify the dataset is frozen at the pinned revision/hash and the request version id/protected hash/template fingerprint still agree with the frozen plan.
- [x] Read only sample IDs and input values for request rendering. Keep references/expected values out of the query and returned snapshot.
- [x] Open the encrypted request row through `_open_request_row` in the caller transaction so the existing request-version access audit is retained; never include the decrypted request in public run DTOs.
- [x] Render each unique case using `QAJSONBinding.render(FrozenRequest, input)`. Validate per-case body bytes against `profile.max_request_bytes` and total cycle-expanded body bytes against `profile.max_total_bytes`; reject before any claim/ACK/send fence if violated.
- [x] Keep credentials/request bodies only in the private in-memory snapshot; return an internal case-id-to-`FrozenRequest` map plus the already verified manifest/profile.
- [x] Run the new regression and relevant repository tests; expect GREEN.

## Task 3: Feed rendered bodies through the synthetic-only ledger path

- [x] Change worker dispatch body selection to use the frozen case request body from the snapshot; retain exact body byte/hash journaling before `send_started`.
- [x] Pass ordinal as non-request metadata to the synthetic transport so deterministic failure injection remains independent of user data.
- [x] Keep `SyntheticPerformanceTransport` the only accepted transport; do not add target transport/API or reuse the synthetic timing as metric input.
- [x] Run all `tests/test_performance_worker.py`, `tests/test_performance_run_repository.py`, and `tests/test_request_version_repository.py` tests; verify network denial tests still pass.

## Task 4: Document boundary and verify

- [ ] Update the performance design's current implementation boundary: synthetic runs now consume rendered frozen case requests but still do not send to AI targets or produce target metrics.
- [ ] Correct stale statements that metrics API / results UI do not exist; link the current state page for commit/CI evidence instead of duplicating stale counts.
- [ ] Run focused performance/repository/evidence tests, Ruff check and format, backend Blocking IO gate, `git diff --check`, and full offline backend suite where the existing environment allows. Do not weaken gates or modify dependencies to hide environment failures.
- [ ] Review the diff for secret/body leakage, expected-answer access, implicit network paths, or changed run terminal semantics.
- [ ] Commit only this slice; push/merge after exact-SHA checks pass. Record SHA and actual CI results. Do not clean unrelated worktrees, containers, caches or local artifacts.

## Acceptance

- Repeated manifest cases deterministically render the same frozen input body for each iteration; different cases render their own input.
- Each ACK records the exact UTF-8 body length and SHA-256 of the body that the synthetic transport receives.
- The snapshot is rejected before any dispatch if plan/request/dataset binding, full persisted sample/reference content hash, or budget checks fail; an admitted run with invalid preflight is terminally interrupted and audited with all unsent ordinals recorded as `not_dispatched`.
- Expected answers, raw bodies and credentials are never returned in public DTOs, audit details, logs or persisted request evidence.
- Network-denial tests prove no target/model request occurs; run remains `execution_mode=synthetic_only` with `metrics=null`.
- All terminal failure, cancellation, drain and no-resend invariants from PERF-06/07 remain unchanged.
