# Performance Workbench UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an owner-scoped performance workbench UI to freeze bounded scenarios, create explicitly confirmed ledger runs, and browse the existing versioned summaries without dispatching requests.

**Architecture:** Add narrowly typed wrappers for the existing scenario and run APIs, then build a client workspace that reuses authenticated evaluation APIs and explicit user actions. The current main branch has no public synthetic Worker start/stop endpoint, so this slice must call no admission/dispatch endpoint and must label ledger creation as non-executing; existing metrics/results browsing remains linked rather than duplicated.

**Tech Stack:** Next.js App Router, React/TypeScript, existing evaluation API fetcher, Tailwind/shadcn UI, No new dependencies, Rstest, ESLint, TypeScript, Prettier.

**Spec:** `docs/DevPilot_AI性能测试工作台设�?md` (PERF-01 frozen scenario and PERF-03 workbench boundary); `frontend/AGENTS.md`; `docs/DevPilot_Equal_Review_and_Linux_Acceptance.md`.

## Global Constraints

- Projects are owner-scoped; all API calls use the authenticated Gateway evaluation API with `cache: no-store`.
- A performance scenario requires a frozen performance-mode plan and bounded profile matching that plan's request count.
- Require a fresh explicit confirmation before scenario freeze and run-ledger creation; changing project/component/plan/profile clears the confirmation.
- An uncertain run-create response is reconciled only by GET of the exact pre-generated run ID; never repeat POST, mint a replacement ID, or automatically retry.
- Run creation writes a ledger only. Do not invoke `/admit`, poll, send network requests, or imply that synthetic dispatch occurred.
- Metrics/results remain labeled by API applicability; `synthetic_only` is not measured target performance and missing evidence is not PASS.
- Preserve the user's existing worktree document changes; do not copy private configuration, databases, credentials, runtime output, or local evidence into this worktree.

---

### Task 1: Add scenario and run API wrappers with contract tests

**Files:**
- Modify: `frontend/src/core/evaluation/performance-results-api.ts`
- Test: `frontend/tests/unit/core/evaluation/performance-results-api.test.ts`

**Interfaces:**
- `listPerformanceScenarios(projectId, componentId): Promise<{scenarios: PerformanceScenario[]}>`
- `createPerformanceScenario(projectId, componentId, payload): Promise<PerformanceScenario>`
- `createPerformanceRun(projectId, payload): Promise<PerformanceRun>`
- Export types matching the backend's public scenario definition and `PerformanceRunCreate` request.

**Steps:**
- [ ] Write failing API tests for URL encoding, request bodies, POST method, and `no-store` for list/create scenario and create run.
- [ ] Run the focused API tests and verify failures are missing exports/behavior.
- [ ] Implement typed wrappers via `evaluationApi`; do not add retry logic.
- [ ] Re-run focused API tests and format the changed files.

### Task 2: Build the bounded scenario configuration and ledger workflow

**Files:**
- Create: `frontend/src/components/workspace/performance-workbench.tsx`
- Test: `frontend/tests/unit/components/workspace/performance-workbench.dom.test.tsx`
- Reuse: `frontend/src/core/evaluation/performance-results-api.ts`, `frontend/src/core/evaluation/results-api.ts`, `frontend/src/core/evaluation/plan-types.ts`

**Interfaces:**
- Default export `PerformanceWorkbench` resolves current user via `useAuth`, loads projects only after an explicit click, and keys state to user identity.
- Profile UI edits only the bounded fields exposed by `PerformanceProfile`; measured request count is fixed to the selected frozen plan's request_count.

**Steps:**
- [ ] Add DOM regressions: no API call on mount; explicit project/component/plan loads; only performance-mode frozen plans may be selected; invalid bounds block freeze; explicit consent is required; changing scope revokes consent.
- [ ] Run the new DOM suite and observe expected red failures.
- [ ] Implement explicit project and linked component loading; load plans/scenarios only after a component is chosen.
- [ ] Implement bounded profile editor with safe defaults (concurrency 1, warmup 0, max_in_flight 1, timeout/wall/drain/request/response/total byte bounds); never exceed selected plan's frozen request count.
- [ ] Implement scenario preview and explicit freeze confirmation; render returned immutable scenario/hash and reload scenario list only after the write succeeds.
- [ ] Implement explicit ledger-create consent and a browser-generated 32-character lowercase hex run ID. If POST fails ambiguously, show reconciliation action using GET of that exact ID only; never resend POST or generate another ID for that attempt.
- [ ] Show persistent inline scope notice: creating a scenario/run ledger does not start a Worker, dispatch requests, measure a target, or produce target metrics.
- [ ] Run DOM regressions; verify no /admit or evidence calls occur.

### Task 3: Expose the workbench and link existing results

**Files:**
- Create: `frontend/src/app/workspace/performance/page.tsx`
- Modify: `frontend/src/app/workspace/evaluations/page.tsx`
- Modify: `frontend/src/components/workspace/performance-workbench.tsx` (link only)
- Test: `frontend/tests/unit/app/workspace/performance-workbench-page.test.tsx` or add route assertion to the existing evaluations page test.

**Steps:**
- [ ] Add failing route/hub navigation regression.
- [ ] Implement `/workspace/performance` route and a link from the evaluations hub; retain the separate results page.
- [ ] Link to `/workspace/performance-results` for run/dispatch/metrics browsing and keep synthetic/not-measured applicability labels honest.
- [ ] Run route and DOM tests.

### Task 4: Document delivery boundary and run frontend gates

**Files:**
- Modify: `README_zh.md` (user-facing route/limitation)
- Modify: `docs/DevPilot_Delivery_Status.md` (this slice's actual source/verification status)
- Modify: `frontend/AGENTS.md` only if a durable frontend safety rule is newly introduced.

**Steps:**
- [ ] Update README with route and explicit ledger-only/no-dispatch limitation.
- [ ] Add a dated status entry that separates implementation from validation; don't claim runtime/deployment or synthetic Worker execution.
- [ ] Run focused API/DOM tests, full frontend unit suite, root-mediated frontend check and format, and `git diff --check` using repository scripts.
- [ ] Review final diff for private data, accidental API calls on mount, automatic retry/polling, and claims of target measurement.

## Explicitly Deferred

- Worker/admission/start/stop/polling controls, target transport, real target consent/allowlist, result persistence, target metrics, deployment, and end-to-end real backend calls.
