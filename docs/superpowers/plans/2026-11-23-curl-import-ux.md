# cURL Import and One-shot Insecure TLS Implementation Plan

> **For agentic workers:** Use the superpowers TDD workflow. Steps use checkbox syntax for tracking.

**Goal:** Make the request debugger and model configuration cURL imports understand common exported cURL syntax, including `-k`, while preserving no-shell parsing and explicit one-shot send consent.

**Architecture:** Parse cURL into normalized request fields plus separate diagnostics/one-shot TLS intent. Never execute shell syntax. The request debugger may disable certificate verification only for an explicitly confirmed individual send; destination allowlisting, DNS pinning, no proxy, no redirects, and response bounds remain enforced. Model import reports that `-k` is not persisted as model configuration.

**Tech Stack:** Python 3.12, FastAPI, HTTPX pinned transport, TypeScript, Vitest, Playwright.

**Spec:** Existing cURL and request-debugger contracts in `docs/DevPilot_Agent_Contracts.md`, `docs/DevPilot_API接口设计文档.md`, and `frontend/AGENTS.md`; update them only where the confirmed one-shot behavior supersedes the old TLS prohibition.

## Global Constraints

- The pasted cURL is never passed to a shell or executed.
- Parsing never sends a network request; sending remains a separate explicit action.
- Insecure TLS applies only to the explicitly confirmed debugger send and is never silently persisted in a model profile or executable template.
- Preserve operator host allowlists, all-address DNS checks/pinning, no environment proxy, no redirects, deadlines, bounded response, redaction, and no request-body logging.
- Do not echo raw command or credentials in diagnostics.

---

### Task 1: Backend parser and send boundary

**Files:** `devpilot/src/devpilot/http.py`, `devpilot/src/devpilot/pinned_http.py`, `backend/app/evaluation/http.py`, `backend/app/gateway/routers/request_debugger.py`, `backend/tests/test_request_debugger.py`, `backend/tests/test_evaluation_http_boundaries.py`

- Add failing tests for the supplied Dify command with `-k`, separated and combined safe flags, common continuation/JSON forms, specific unsupported-option diagnostics, and send-only explicit TLS authorization.
- Implement parse metadata separately from `RequestSpec`; do not persist TLS bypass intent into request versions/templates.
- Permit verify-disabled TLS only via explicit one-shot send payload consent; keep all outbound destination controls unchanged.

### Task 2: Frontend model import and debugger confirmation

**Files:** `frontend/src/core/evaluation/model-curl-import.ts`, `frontend/src/components/workspace/request-debugger.tsx`, `frontend/src/core/evaluation/api.ts`, `frontend/src/app/workspace/models/page.tsx`, `frontend/tests/unit/core/evaluation/model-curl-import.test.ts`, relevant component/e2e tests.

- Add failing parser/UI tests for `-k`, combined flags, the exact internal Dify cURL, line continuations and JSON body, and a visible insecure-TLS warning.
- Display parse diagnostics and TLS status without echoing raw secrets.
- Require an explicit additional checkbox/consent before a `-k` debugger send; ordinary requests retain existing send consent.
- Model cURL import accepts `-k` but clearly says the option is not stored as a model TLS policy.

### Task 3: Contracts and verification

**Files:** update only relevant cURL/request-debugger contract and delivery status documents.

- Replace stale statements that categorically reject parsing `-k` with the parser-vs-one-shot-send boundary.
- Run targeted backend and frontend tests, frontend checks, formatting, and diff checks. Record exact results; do not claim full suite success unless it passes.

### Task 4: Delivery

- Review diff and status; commit the small slice, push, verify exact-SHA Actions, merge to `main` if working from a feature branch, and record exact SHA/results in delivery status. Never clean unrelated worktrees/containers.
