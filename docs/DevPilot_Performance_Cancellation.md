# Synthetic Performance Run Cancellation Contract

**Date:** 2026-11-27  
**Scope:** Owner-scoped durable cancellation request for an admitted performance run; the only current executor remains the synthetic-only `PerformanceWorker`.

## Behavior

- An authenticated human with existing evaluation write/review permissions can submit `POST /api/evaluation/projects/{project_id}/performance-runs/{run_id}/cancel` with `{"confirmed": true}`.
- The request is authorized only for the owning user and an admitted (`running`) run. Missing or foreign runs remain indistinguishable (404); non-cancellable lifecycle states conflict (409).
- Cancellation is durable and idempotent: one append-only `run_cancel_requested` audit event accompanies an atomic `running` → `cancel_requested` transition. Repeating the same run-ID cancellation returns its current receipt without appending another event. This does not cancel a completed/interrupted run.
- The status transition is the dispatch fence. Any claim/ACK/send-start transition serialized after the cancellation request is rejected. Dispatches already fenced as `send_started` are treated as potentially in flight.
- The Worker observes persisted cancellation before opening further dispatch fences and polls while requests are in flight. It stops admissions, drains in-flight responses/evidence within the existing bounded drain policy, then records `interrupted`; unresolved sends remain `unknown` and are never retried. A request receipt means “requested,” not “drained.”
- The worker's final completion transition races atomically with the cancellation request: whichever locks/transitions the run first wins. If cancellation wins, completion cannot overwrite it.
- The run response exposes the lifecycle status; no new identity, credential, response, or evidence fields are added.

## Safety boundaries

- No scheduler, automatic worker launch, target transport, retry/replay, quota release, forced task cancellation, or unknown-state reconciliation is introduced.
- The endpoint does not prove Worker liveness or immediate cessation. A deadline remains distinct from cancellation completion.
- All writes are owner/project/run scoped and audited. Existing project permission and human checks remain mandatory.
- Existing admission/dispatch lifecycle stays the only authority for dispatches; cancellation is a monotonic stop request, never authorization to send.

## Verification

Regression coverage must include repository idempotency and owner isolation, concurrent cancellation/admission fencing, lifecycle-state conflicts, API auth/permissions/private 404 behavior, worker stop-admission/drain/unknown semantics, completion-vs-cancel ordering, and migration downgrade/upgrade/schema parity. Run focused tests, Blocking IO, Ruff/format, then the full offline backend suite on Linux/Python 3.12. No real model or target calls.
