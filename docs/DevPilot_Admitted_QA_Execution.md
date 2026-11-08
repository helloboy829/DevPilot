# Admitted QA JSON execution

This change connects frozen plans to an independently authorized execution queue,
DB-fenced Worker, encrypted evidence and the existing human-review page. It is
**locally regression-tested but not deployed**. Linux full-suite results must be
confirmed against the exact pushed commit, not the prior deployment SHA.

## User flow

1. Link a component to a project, save an encrypted request version, review and
   freeze QA data, then freeze the JSON mapping and budgets.
2. In **Projects & datasets → Execute evaluation**, explicitly load metadata,
   select the component and frozen plan, review the hash and load budgets.
3. Separately attest target/data/load authorization and confirm this execution.
   Plan freezing alone never triggers a request. Internal agents cannot attest.
4. The browser generates one execution identifier before PUT. Keep that identifier
   if a response is uncertain. GET inspects the same receipt; there is no automatic
   write retry, new identifier, replay, or debugger send.
5. Explicitly refresh the receipt. Technical collection is not quality PASS. Use
   **Human result review** to inspect Q / actual A / expected / source and append
   a revisioned decision and reason.

The UI does not auto-poll or execute on mount, store request/Q/A/gold in browser
storage, or interpret returned text as HTML. Switching project discards page state
and ignores late responses. Recent executions are capped at 200. Keep an uncertain
execution identifier before leaving the page; this slice has no durable browser
receipt storage or cross-device request-intent reconciliation.

## Operator controls

`evaluation_execution` in root configuration is operator-owned, default disabled
and **Gateway restart-required**. No API/UI can edit this policy. Set an explicit
`DEVPILOT_REQUEST_ENCRYPTION_KEY` and exact destination host allowlist under
`evaluation_http` separately. Never auto-generate a key or reuse JWT/model secrets.
No model is required for this deterministic collection/human-review path.

Global reservations cover active runs, total concurrency, total rendered request
body bytes and all response upper bounds (`request_count * (max_response_bytes+1)`).
Admission validates the complete frozen gold-bound dataset without sending gold;
only input strings reach rendering and collection. It rechecks the prepared
snapshot under the global guard before writing the journal, execution and audit
in one transaction. Crypto and preflight happen outside the guard transaction.

SQLite/PostgreSQL guard-row writes serialize admission, claim and dispatch fencing
across sessions/processes. Conflicting policies fail closed while reservations are
held. The original worker may still drain/cancel under a changed policy; cancellation
must not depend on increasing quota. Actual outbound calls continue using fresh DNS
resolution, IP pinning, host/SNI preservation, TLS verification, no environment
proxy, no redirects and no application-level retries.

## Failure and cancellation semantics

- Queue time counts toward the frozen run wall deadline.
- A run is claimed once, never reclaimed or automatically requeued.
- Each send requires a confirmed durable ordinal marker first. This is **not** a
  claim of database/network exactly-once. A marker may exist without a send.
- Unknown DB commit: no send or automatic retry. Unknown delivery immediately
  fences further local sends, before evidence-write completion; already-dispatched
  tasks cancel/drain and the ordinal is never resent.
- Cancellation shields and drains each in-progress database operation before
  propagating, avoiding orphaned cursors/write locks. This never grants permission
  to send after cancellation. A claim committed during shutdown is remembered by
  its original Worker and finalized only after its local tasks have drained.
- Queued cancellation releases reservations because no worker claimed it.
- Running cancellation interrupts the journal but retains reservations until the
  original worker has cancelled and awaited all its local tasks. Stopping an HTTP
  client does not prove that remote business processing has stopped.
- Lost/expired claimed workers are terminalized without re-claiming and **retain
  global quota**. This intentionally favors safety over availability. No timeout
  proves an old process is dead. This slice does not provide an administrator
  forced-release API; operational reconciliation is a follow-up prerequisite for
  unattended production use. Do not manually reset rows to queued.
- Orderly Gateway shutdown cancels and drains its worker before closing database
  resources. Hard process death preserves unresolved reservations.

The journal scope remains `dispatch_journal_only`; the separate admission row has
`admitted_qa_json`. Neither is a quality verdict. Extracted outputs remain encrypted
and audited via `EvidenceRepository`; no arbitrary output-upload endpoint is added.

## Migration and exclusions

`eval_0007` only appends the guard and admission tables/index. Do not edit previous
revisions or the Harness Alembic ledger. Upgrade only after a consistent online
backup and preservation checks for accounts, configuration, old rows and mounts.
Do not remove data volumes. The local operator configuration is not auto-enabled.

This is a QA non-streaming JSON collection path, **not** the complete evaluation
product. No CV/image executor, streaming TTFT/TPS, model judge, stable accuracy
aggregation, schedule admission, runnable export, report-evidence binding, team
arbitration, remediation/retest chain or automatic production recovery is added.
The existing legacy component-test/schedule paths are not silently redirected.

## Validation status (2026-11-08)

Backend TDD started with absent-module collection failures; subsequent red tests
also exposed inherited helper-name collisions, cancellation leaving SQLite write
locks, shutdown during claim acknowledgement, and sends continuing while a known
unknown-delivery observation was still being persisted. Each has a regression.

Local isolated Windows Python 3.12 validation:

- New execution repository/router/lifecycle: **30 passed**.
- Evaluation, datasets, registry, plans, request versions, collection, dispatch,
  evidence and related runtime regressions: **479 passed**.
- Gateway lifecycle/recovery, App config and persistence bootstrap regression set:
  **302 passed / 2 skipped** (PostgreSQL integration unavailable locally).
- Final frontend unit suite: **137 files / 1061 passed / 0 skipped**; production
  build succeeds (95 routes) and lint/typecheck pass. Execution/review DOM subset:
  **12 passed**, including empty review guidance without implicit execution.
  A pre-existing code-block test imported the whole component inside its 5-second
  test budget and repeatedly timed out before assertions. Static suite import fixes
  that harness timing; it still loads the real highlighting helper, rejects the
  Shiki dependency and verifies raw fallback. No timeouts/retries were increased.
  Exact-SHA Linux Actions must still be confirmed after pushing.
- Full browser suite: **189 passed**, plus **2 authentication-recovery tests**,
  one worker, zero retries. Requests are fixture-stubbed, not real business calls.
  An initial browser failure was an exact implicit-label locator; using the
  combobox role/accessibility name fixed it without increasing timeouts.

These groups overlap; do not add them to invent a full-backend pass count.
A Windows full-backend attempt is **not a pass**: first-failure reproduction stops
at the existing POSIX `0600` config-file assertion (`0666` on Windows). Do not
weaken that security test or treat every error from the earlier interrupted run
as the same platform issue. Linux full suite and Blocking IO remain required.

Docker daemon API requests still time out in bounded read-only diagnostics; the
existing local login page returns HTTP 200. Local App deployment remains
`eval_0006`, while this candidate's App migration head is `eval_0007`. No service,
account, real configuration, key or volume was modified for these validations.
No real target, paid model or automatic run was enabled. A new consistent backup
and preservation checks remain mandatory before deploying this candidate.
