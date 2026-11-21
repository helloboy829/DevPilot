# EFF-03 Results Browser Implementation Plan

> Use the executing-plans workflow; each checkbox is a separate testable checkpoint.

**Goal:** Build an owner-scoped effectiveness-results workspace for run summaries, filtered/keyset-paged cases, non-sensitive details, and explicitly authorized captured responses.

**Architecture:** Add `/workspace/effectiveness-results` with focused DTOs, API helpers, and UI components. Reuse existing `/runs` and EFF-02 grant/read contracts. Sensitive values stay in page memory, no-store, explicitly loaded, and cleared/fenced on object changes. Do not change legacy review UI or backend permissions.

**Tech:** Next.js App Router, React, TypeScript, authenticated evaluation fetcher, Rstest, Testing Library, Playwright.

**Spec:** `docs/DevPilot_效果测试工作台设计.md` sections 1-7; feature spec EFF-03; implementation ledger EFF-03.

## Constraints
- No implicit run/case/evidence reads, polling, retries, target/model calls, or writes.
- Never persist sensitive data in URLs, browser storage, telemetry, or persistent cache.
- Clear sensitive state on project/run/case/account changes, unmount, and stale response; parsed output is not raw response.
- Preserve blind-review assignment/reveal boundaries. Keep `.patch-test` unstaged.

### Task 1: DTOs and API
Files: create `frontend/src/core/evaluation/result-types.ts`, `results-api.ts`, and `frontend/tests/unit/core/evaluation/results-api.test.ts`.
- [x] Add failing route/query/no-store/grant/binary-bound tests and observe RED.
- [x] Implement typed run/case query helpers and bounded response read with the authenticated fetcher; no retries.
- [x] Run focused API tests and existing evaluation API tests.

### Task 2: Workspace and run list
Files: create `/workspace/effectiveness-results`, `evaluation-results-workspace.tsx`, DOM tests; link from evaluation home.
- [x] Prove no mount `/runs` request, explicit load, cursor pagination, reset on project change, stale-response discard.
- [x] Observe RED, implement bilingual run list with accessible loading/error/empty states.
- [x] Check keyboard use and narrow viewport overflow.

### Task 3: Summary, filters, cases, detail
Files: create run-summary and case-table components; extend workspace/DOM tests.
- [x] Cover only API filters (`integrity_status`, `dispatch_state`, `kind`, `http_status`, `reference_status`), filter reset, fixed `total` vs `matched_total`, explicit detail, and honest status/verdict/evidence labels.
- [x] Observe RED, implement server-cursor paging and metadata-only result views.
- [x] Run DOM suite and frontend check.

### Task 4: Explicit response evidence
Files: create evidence viewer and `frontend/tests/e2e/evaluation-results.spec.ts`; extend DOM tests.
- [x] Cover no implicit calls, explicit grant then bounded read, stale fences, clear on close/switch, HTML-as-text, size/media/error paths.
- [x] Observe RED, implement escaped in-memory response viewer; no download in this slice.
- [x] Run synthetic desktop/mobile Playwright regression.

### Task 5: Gates and delivery
Files: update implementation ledger, feature spec, and delivery status.
- [x] Run frontend full Rstest (1,468 passed), `check`, `format`, production build, and synthetic Chromium E2E (2 passed at 390px/1440px); no models, targets, deployments, or containers used.
- [ ] Record exact commit SHA and Actions after push; keep EFF-01 PostgreSQL parity and exact-count scale gates open.
- [ ] Inspect final index, exclude `.patch-test`, commit/push after gates, and verify Actions for the exact SHA.

**Out of scope:** Request bodies, references, parsed output, legacy raw bodies, downloads, and task-reviewer access without matching authorization APIs.
