# AGENTS.md

## 共享完整有界 QA run 候选（2026-11-10）

`devpilot.qa_json_run` 固定 `qa-json-run.v1`，由平台真实 Worker 共用 ordinal/输入循环、并发、原 absolute deadline、未知交付先停发及任务关闭。必须显式提供 clock/reserve/collect/record/check-active 能力；callback 本身不是准入或耐久证明。App 保留授权、全局/整 run 字节配额、动态出站、加密证据与 claim/load/finish，所有 DB 读写仍经 `_drained_database`；finish 在共用核心排空后执行。无默认客户端/配置/凭据、重试、API、依赖或迁移，不是授权 exporter/CLI 或正式批准。见[合同和验证](docs/DevPilot_Shared_QA_JSON_Run_Core.md)。

## Shared bounded JSON attempt collector candidate (2026-11-10)

`devpilot.qa_json_attempt` pins `qa-json-attempt.v1` and shares the existing complete single-attempt collector, not a second runner. Require an explicit client factory; App retains dynamic outbound policy, admission, durable dispatch, budgets and no-resend. Preserve cooperative deadline, max+1 yielded bytes, normal-end-only off-loop decode, original errors/cancellation/close and re-exported observation type identity. Cancellation cannot kill parser threads or synchronous callbacks; never claim hard-death or release authority. Sensitive output is not a public result/verdict. Verify actual old/new behavior and built-wheel mock sends with existing HTTPX. No dependency/migration/deployment/enablement/real calls. [Contract](docs/DevPilot_Shared_QA_JSON_Attempt_Core.md).

## Shared pinned HTTP transport candidate (2026-11-10)

`devpilot.pinned_http` pins `pinned-http.v1`; the existing App transport delegates the real origin/Host/SNI/TLS/no-retry mechanism with a fresh explicit resolver callback. App keeps dynamic allowlists and ALL-answer DNS policy. Callback results must be literal unscoped IPs, never second-DNS hostnames. Keep errors/cancellation/close, client no-redirect/no-env and admitted dispatch-before-I/O/no-resend; no standalone runner/export permission. Uses existing HTTPX, not a no-site pure core. Verify actual wire parity and built wheel without business imports. No dependency/migration/deployment/enablement/real calls. [Contract](docs/DevPilot_Shared_Pinned_HTTP_Core.md).

## Shared QA JSON request preparation core candidate (2026-11-10)

`devpilot.qa_json_request.QAJSONRequest` pins `qa-json-request.v1`; App attempts delegate literal URL/method/body/headers and conditional identity preparation. Freeze headers; preserve explicit/duplicate encodings and historical 64 original → 65 derived headers, exact UTF-8 body limit and lazy content encoding within the original deadline. Values remain sensitive internal data, not an export DTO/authorization. Keep Worker render → durable dispatch → collect, transport and unknown/no-resend App-owned; no plan/hash migration. Verify old/new actual requests plus isolated source/wheel. No dependency/deployment/enablement/real calls. [Contract](docs/DevPilot_Shared_QA_JSON_Request_Core.md).

## Shared QA JSON response core candidate (2026-11-10)

`devpilot.qa_json_response` pins `qa-json-response.v1` as the single pure buffer/framing/output parser used by App attempts. Preserve head precedence, max+1 yielded-byte limits, strict binding and normal-end-only finish; errors/cancellation never finalize or resend. Decode/extract off-loop, keep sensitive output out of repr/public DTOs and test isolated source/wheel imports. Transport/admission/journal remain App-owned; no historical plan hashes change. This is not a full versioned runner/exporter or approval. No dependency/migration/deployment/enablement/real calls. [Contract](docs/DevPilot_Shared_QA_JSON_Response_Core.md).

## QA shutdown repeated-cancellation drain candidate (2026-11-10)

`qa_execution_runtime` cancels its original Worker once, shields one shared gather waiter through repeated Gateway shutdown cancellation, and propagates cancellation only after that Worker drains. Clear the repository after drain even on cancellation; never retry/restart tasks or add a drain timeout. Keep dispatch/no-resend and original finish/reservation rules; hard process death still retains quota. Event barriers must cover normal/cancelled/error bodies and the real Worker with synthetic collectors/temporary DB. No API, migration, dependency, operator enablement or deployment. [Contract](docs/DevPilot_QA_Shutdown_Drain.md).

## Route resource budget candidate (2026-11-10)

`frontend/scripts/content-page-map-*` projects only Nextra-generated App namespace imports in its exact build placeholder; content metadata/map topology and real App routes stay unchanged. Unknown generator/config shapes fail closed; verify Turbopack and Webpack builds. `globals.css` scans explicit runtime/public and full Streamdown plugin chunks only. Preserve ALL historical raw-HTML safelist directives in lazy `rich-html.css`; source-free theme tokens prevent duplicate app utilities. Only Markdown artifacts/lazy memory settings own this palette, not iframe/editor entry paths. Never raise budgets, drop routes or change measurement to hide regressions. Six original route budgets pass, but chat CSS has only 609 bytes headroom. No dependency, migration, backend behavior, deployment or real calls. [Contract](docs/DevPilot_Route_Resource_Budgets.md).

## Read-only execution diagnostics workspace candidate (2026-11-10)

`/workspace/operations` is explicit human-admin aggregate GET only. Keep strict 16 KiB streamed JSON, all five held states/total coherence, no occupancy clamp to serving policy, synchronous locks and account/role/auth-refresh/unmount late-response fences. No mount fetch, polling, retries, persistent cache, sensitive reads, release/reclaim/dispatch controls or execution enablement. Backend admin + separate permission remains authoritative; deadline is not death, policy is process-local and observation is not a heartbeat. [Contract](docs/DevPilot_Execution_Diagnostics_Workspace.md).

## Read-only execution reservation diagnostics candidate (2026-11-10)

`GET /api/evaluation/operations/reservations` requires a human administrator plus separate `evaluation_operations:read`. One aggregate SELECT over held execution metadata only; no IDs/claim material/evidence, guard initialization/write/expiry, released quota or resend authority. Deadline reached is not Worker-death proof; local process policy is not global agreement. Keep private generic errors, no-store, deny-wins and literal false release/reclaim/retry/dispatch flags. No migration/dependency/UI/deployment/real calls; safe operational release remains unfinished. [Contract](docs/DevPilot_Execution_Reservation_Diagnostics.md).

## Authenticated synthetic multi-account QA regression (2026-11-10)

`backend/tests/test_qa_authenticated_workflow_api.py` overrides only the old workflow's API fixture: real temporary-DB password users, local login/JWT/token-version, CSRF and enabled fail-closed RBAC; independent cookie jars, never identity middleware/state actor switches. Keep synthetic secrets/config isolated, socket fail-closed, blind-review narrow grants, ALL denominators, historical immutability and no approval authority. This is offline ASGI/Worker integration, not real-user/browser/deployment acceptance; no runtime, migration, dependency or real calls. [Scope](docs/DevPilot_Authenticated_QA_Regression.md).

## Independent historical PDF candidate (2026-11-09)

`independent-qa-pdf-v1` / `independent-retest-pdf-v1` consume only pinned internal Word-v1 historical public projections, never client XML/HTML or current sources. Keep human owner read/review + viewed hash, off-loop checks/rendering, ALL frozen populations, literal bounded whole-document rejection, fixed engine/embedded OFL font and frontend no-store/ref locks/late-response fences. Unsupported glyph/complex direction fails closed; no system-font/network fallback. Preserve legacy archives/Word/hash. Font rebuild is build-only; the Tenki source override retains the exact old official wheel/hash, not a new SDK. No migration/deployment/execution/model/approval authority. [Contract](docs/DevPilot_Independent_PDF_Drafts.md).

## Independent historical retest Word candidate (2026-11-09)

`independent-retest-docx-v1` exports a pinned bilingual projection of stored public comparison facts, NOT stored Markdown (retests have none). Human owner read/review + viewed archive hash; integrity and rendering off-loop, no current sources/keys or metric/criteria recomputation. Preserve ALL frozen samples/task commitments, strict bounded whole-document rejection, literal text and separate namespaces. UI downloads explicitly with ref locks/late-response fences; no retry. No migration/dependency/deployment/approval authority; old report/Word bytes unchanged. [Contract](docs/DevPilot_Independent_Retest_Word_Drafts.md).

## Independent lifecycle integration regression (2026-11-09)

`backend/tests/test_qa_independent_workflow_api.py` joins HTTP-frozen v2 plans and the real offline Worker to blind reviewers/arbitration, immutable assessment revisions and explicitly selected historical report/retest archives/Word. Preserve ALL frozen denominators, owner-vote isolation, missing-evidence rejection, unique assessment pairs, reopened-history immutability and same-ID GET-only reconciliation even on 404. DNS/wire are synthetic and sockets fail closed; no runtime feature, migration, dependency, execution enablement, deployment or real calls. Explicit case/result opens are sensitive, unlike metadata. See [scope and gates](docs/DevPilot_Independent_Workflow_Regression.md).

## Independent historical Word candidate (2026-11-09)

`app.evaluation.independent_report_docx` and the separate `independent-qa-docx-v1` GET export explicitly viewed independent report archives only. Preserve stored Markdown/public historical receipts, off-loop integrity/rendering, human owner read/review, bounded OOXML, no active content, no current sources/keys/metric recomputation and frontend late-response fences. Legacy `qa-docx-v1` is unchanged. No retest Word/PDF, approval, migration, deployment or target/model calls. See [contract](docs/DevPilot_Independent_Word_Drafts.md).

## New-machine CI and database cancellation (2026-11-09)

Treat deployment receipts from another computer as historical evidence, not this machine's runtime. Rebuild isolated dependencies from tracked source and lockfiles; never copy private configuration, databases or virtual environments. The QA Worker must drain monitor database reads as well as writes before finalization: cancelling an aiosqlite read can strand a pooled lock and block the final commit. Preserve cancellation, same-ID reconciliation and no-resend semantics; do not hide the failure with retries, longer timeouts, weaker assertions or execution enablement. See [execution](docs/DevPilot_Admitted_QA_Execution.md) and [current status](docs/DevPilot_Delivery_Status.md).

## Module delivery and GitHub CI discipline (2026-11-09)

Finish a scoped module, run its regression tests and relevant full checks, then commit and push the verified changes to GitHub. Keep unrelated work, private configuration and local evidence out of the commit. Record the exact pushed SHA and its Actions runs; a successful push is not successful CI. Long-running Actions may be checked before the next module push, but inspect the previous results and fix attributable failures rather than carrying a known failure forward. Do not implicitly deploy, enable execution or call real models/targets.

## Independent historical archive workspace candidate (2026-11-09)

`IndependentArchivePanel` adds separate report/retest sections without changing legacy owner-review routes. Explicitly load and open historical assessment IDs/revisions; never default to latest, substitute owner votes or read sensitive evidence. Only complete historical sources may be staged. Keep strict receipt/source/parent and benchmark-population coherence checks, ALL frozen denominators, page-memory pending IDs, write locks and late-response fences. Unknown PUT outcomes, including 404, reconcile only by same-ID GET; never resend. Stored Markdown is displayed literally. Independent Word/PDF and formal approval remain unfinished. Candidate head `eval_0012` is not deployed. [Contract and verification](docs/DevPilot_Independent_Report_Retest_Archives.md).

## Independent historical report/retest archives candidate (2026-11-09)

`app.evaluation.qa_independent_archives` explicitly binds archived assessment IDs/revisions/hashes in separate report/retest namespaces and fixed bilingual templates. `eval_0012` adds two tables/indexes; deployed head remains `eval_0009`. Historical complete revisions remain selectable after task reopen; no latest-state pointer, owner-vote substitution, sensitive evidence reads, execution or approval. Keep ALL frozen samples, strict benchmark/budget/criteria equality, off-loop checks and final project → ordered-run locks with atomic archive/audits. Unknown writes only GET the same ID. Legacy archives/templates/hashes are unchanged. The separate workspace now provides explicit historical source selection; independent Word/PDF and formal approval remain unfinished. [Contract and gates](docs/DevPilot_Independent_Report_Retest_Archives.md).

## Independent assessment revisions candidate (2026-11-09)

`app.evaluation.qa_assessments` verifies ALL frozen effectiveness samples against independent case tasks, not owner self-review. Off-loop verification precedes whole-snapshot run-lock rechecks and atomic immutable assessment/audit append with revision CAS. Missing/cancelled/conflicting/uncertain or technical evidence blocks completeness; frozen v2 criteria use integer comparisons, never approval. Candidate App head `eval_0011` adds one table/index; deployment remains `eval_0009`. Post-collection assessment is not retroactive pre-run admission. The datasets workspace now adds explicit independent preview/history/archive UI with page-memory pending IDs and same-ID GET-only reconciliation. No legacy report/retest switch, formal approval or target/model calls. [Contract and tests](docs/DevPilot_Independent_Assessments.md).

## Independent case review workspace candidate (2026-11-09)

`/workspace/reviews` and the datasets inline assignment/detail reuse the same human-only task APIs: explicit metadata loads/claims/case opens, two blind reviewers, a separate arbitrator and immutable owner round results. Three exact account UUIDs and separate sharing/creation consent are required; no account directory or project membership grant. Keep page-memory pending creation IDs across project switches, same-ID GET-only reconciliation, write locks, unmount fences and post-await lease checks; no polling, automatic retry, persistent sensitive caching or target/model calls. Reasons/edits revoke consent, missing evidence cannot PASS, expired leases close evidence without renewal. This slice remains undeployed; the later assessment and historical report/retest slices extend it without adding formal approval. [Scope and verification](docs/DevPilot_Independent_Case_Review.md).

## Independent case review backend candidate (2026-11-09)

`app.evaluation.review_tasks` and human-only task APIs grant one frozen case to two distinct blind reviewers and a third arbitrator, never the owner or general project membership. Claims have bounded leases; viewed revision, CAS and ordered run-lock rechecks fence changes. Notes/reopen reasons use domain-separated encrypted envelopes; decisions/resolutions/rounds/audit append atomically. Missing/technical evidence cannot PASS. Unknown writes reconcile the same task ID by GET, never auto-resend. Candidate `eval_0010` adds five tables/two indexes; deployed `eval_0009` is unchanged. The workspace UI described above consumes these APIs; no assessment/summary/report integration, formal approval, model/target calls or automatic deployment. [Scope and tests](docs/DevPilot_Independent_Case_Review.md).

## Current delivery and test-resource lifecycle (2026-11-09)

[Current matrix](docs/DevPilot_Delivery_Status.md) separates implemented code, deployed SHA, verification and remaining work; older slice notes are historical, not a claim that later Workers/reports/retests are missing. Never equate the bounded QA chain with formal independent approval or a completed platform.

Record which isolated CI containers a session starts and stop those after all test processes finish; do not stop pre-existing services or active tests. Retire obsolete DevPilot-only verification containers only after checking purpose/state/data and retaining replacement verification. Use exact container IDs, no force or volume removal. Then check image references across **all** containers before exact project-only image removal. Keep useful stopped dependency caches, current deployment and required rollback resources; no global prune/build-cache cleanup or unrelated-project changes. Images consume disk; running containers consume RAM. `docker system df` reclaimable percentages and missing tags never authorize deletion; verify exact ownership and all container references. See [operations](docs/DevPilot_Docker_Diagnostics.md).

## Synthetic API-to-Worker QA regression (2026-11-09)

`backend/tests/test_qa_workflow_api.py` exercises HTTP-created frozen v2 plans through the real Worker, durable dispatch, encrypted evidence, human review, verified criteria, immutable reports/Word and same-benchmark retests. Migrated temporary SQLite and synthetic auth/data/keys are explicit; DNS/wire are substituted and socket sends are fail-closed. Concurrency 1/2 and six transport/output failures cover dispatch-before-I/O, frozen request versions, no retries, all-sample denominators and immutable history. This is offline regression, not deployed/browser/real-auth acceptance, independent approval or production enablement. No runtime feature, dependency or migration is added.

## PostgreSQL TLS URL compatibility (2026-11-09)

Only `DatabaseConfig.app_sqlalchemy_url` translates a single explicit libpq `sslmode` to asyncpg's `ssl`, preserving the mode, encoded credentials and other query values. The original DSN and synchronous psycopg path are unchanged. Duplicate/invalid modes or simultaneous `ssl`/`sslmode` fail closed with a generic error; never drop TLS policy or default to disabled TLS. Regression: `backend/tests/test_postgres_url_sslmode.py`; dedicated PostgreSQL schema checks use an owned temporary test database. No dependency, migration, production configuration, deployment or target/model calls.

## Static-scan failures and deterministic regressions (2026-11-08)

With skill scanning enabled, `enforce_static_scan` rejects reported `scanner_errors` with a generic `StaticScannerError`; critical findings keep precedence and their existing details, and the explicit operator switch remains unchanged. An incomplete scan is not a clean scan. The native scanner tests build deep ASTs iteratively to exercise the analyzer independently of CPython parser limits, while separate injected parser/read failures prove rejection. Run ordering tests use distinct frozen timestamps; the equal-timestamp insertion-order contract is unchanged. Tests: `backend/tests/test_skillscan_native.py`, `backend/tests/test_run_manager.py` plus existing installer/router/tool rejection tests. No model/target calls, migration or Docker changes.

## Frozen pre-run effectiveness criteria (2026-11-08)

`qa-json-plan.v2` binds strict plan-scoped basis-point criteria to the existing definition hash. v1 serialization/hashes remain unchanged; no migration. Verified summaries use ALL frozen samples and integer comparison; incomplete/uncertain evidence blocks even zero thresholds, and `met` is never approval. Template 1.1.0 adds criteria; 1.0.0/historical archives remain immutable, and v2 sources cannot silently use old layouts. Retests require identical schema/criteria. No additional model/target calls or auto-enabled execution. [Scope, contracts and exclusions](docs/DevPilot_Frozen_Effectiveness_Criteria.md).

## Local Docker image hygiene

After each test session, stop only the CI containers started by that session once all tests and evidence export are complete. Precisely remove session-owned temporary snapshots and helpers after verifying evidence copies; keep reusable dependency caches, business services, volumes and unrelated resources. Audit project image references against ALL containers before deletion. Running containers use RAM; image/snapshot cleanup concerns disk and does not establish host memory or VHDX reclamation. No unattended cleanup daemon or global prune.

After building and independently verifying a replacement, remove obsolete **DevPilot-only** images that no container (including stopped containers) references. Use exact image references, no force, global prune, volume deletion or unrelated-project cleanup. Keep the current deployment and pre-upgrade rollback image until verification succeeds; do not build at service startup. Dangling images require proven build provenance; absence of a tag alone is not ownership. Image deletion may share layers and does not prove host VHDX compaction. [Operations](docs/DevPilot_Docker_Diagnostics.md#镜像清理与空间维护)。

## Same-benchmark QA retest archives (2026-11-08)

`app.evaluation.qa_retests` and `/workspace/retests` add immutable, owner/human-only comparisons of fully reviewed effectiveness runs. Strict frozen benchmark/budget equality, distinct version declarations and non-overlapping chronology are required. Off-loop verification precedes final ordered locks and atomic append/two-run audit. Unknown writes only reconcile the same ID by GET, never auto-resend. UI retains pending IDs across project switches, fences late responses and opens paired Q/A separately; current review revisions do not rewrite frozen decisions. App head `eval_0009` is additive and is now backed up, deployed and independently verified locally. No execution/model calls, approval or automatic notification. [Scope, privacy, tests and exclusions](docs/DevPilot_Same_Benchmark_Retesting.md).

## Verified local recovery and deployment (2026-11-08)

Latest verified runtime deployment is `0fd689da83a4ac7646250447fb6d044599a823c5`, App head `eval_0009`; all six triggered Actions succeeded for that exact SHA. An online consistent backup preceded gateway/frontend-only replacement and nginx reload; no Docker Desktop restart. All 24 checked account/evaluation/ledger tables, four config hashes, mounts and unrelated containers were preserved, with integrity/foreign-key checks. All 626 runtime Python sources and 528 frontend source files matched the manifest. Every existing account passed desktop/mobile read-only retest, assistant, dataset, report and model-page smoke, with no writes or model/target calls. After verification, the two old `qa-retests-3a5cd38fc99d` image tags were precisely removed; referenced legacy test images were retained, with no force/prune/container/volume deletion. Post-cleanup services are healthy. Assistants remain available privately to all authenticated users; model/request keys remain unconfigured and execution disabled. [Procedure and evidence limits](docs/DevPilot_Local_Recovery_and_Upgrade.md). This supersedes earlier deployment status, not historical evidence or feature exclusions. Follow-up commits need their own CI; the Windows full suite still has separately tracked failures.

## Frozen QA Word drafts (2026-11-08)

`app.evaluation.report_docx` exports authenticated immutable archives via the pinned `qa-docx-v1` GET route. Stored Markdown only, no current-template lookup/metric recomputation/model/target calls/approval. Standard-library bounded OOXML runs off-loop; owner + human + read/review and viewed receipt are mandatory. UI downloads explicitly, validates bounded binary responses and fences scope changes. MarkItDown/Mammoth is an existing independent test reader; synthetic browser fixture parts are checked against the renderer. No new dependency or migration. [Workflow, safety and exclusions](docs/DevPilot_QA_Word_Draft_Export.md). Earlier notes retain their original slice scope.

## Immutable platform QA report drafts (2026-11-08)

`app.evaluation.qa_reports` appends reverified multi-component server summaries, full template/layout versions and rendered Markdown to `evaluation_report_archives` (`eval_0008`). Owner-only human read/review; write also requires write permission and separate confirmation. Sources are IDs + viewed hashes, never client metrics. Complete review is required, not all-PASS or approval. Crypto runs off-loop; final ordered run locks recheck every snapshot, with archive/audits atomic. Same-ID receipts are immutable; unknown writes only reconcile by GET, never retry/new-ID automatically. `VerifiedProjectReportPanel` explicitly loads data, retains pending IDs across project switches in page memory, fences unmounts and opens old documents without rerendering current templates. Manual/Agent suggestions stay separate and unverified. No formal approval, DOCX/PDF or target/model calls. Local last confirmed head remains `eval_0006`; preserve accounts/config/mounts and back up before deployment. [Scope and gates](docs/DevPilot_Immutable_QA_Report_Archives.md). Earlier notes below retain their historical boundaries.

## Verified human summary preview (2026-11-08)

`app.evaluation.qa_summary` authenticates shared frozen sources, each output and only the latest encrypted human decision off-loop, then rechecks the whole snapshot under the run lock before audit/return. Denominator is ALL frozen effectiveness samples, never the reviewed/successful subset. Performance repetitions are rejected. Complete review is not acceptance; no report snapshot is persisted. No migration; code head remains `eval_0007`, local confirmed head `eval_0006`. [Scope and gates](docs/DevPilot_Verified_QA_Summaries.md).

## Independently authorized QA execution (2026-11-08)

The candidate App head is `eval_0007`; local deployed head remains `eval_0006` until a backed-up upgrade succeeds. Separate human-only authorization connects frozen QA JSON plans to global DB reservations, one-time claims, a bounded Worker and encrypted review evidence. Operator policy is restart-required/default-disabled; never generate keys or enable target/model calls implicitly. Unknown writes/delivery never retry; DB operations and local tasks drain before reservation release. Lost Workers retain quota, never reclaim. See [scope and verification gates](docs/DevPilot_Admitted_QA_Execution.md) and the module guides. Earlier slice notes below describe their original boundaries.

## Encrypted QA evidence and human review (2026-11-08)

`app.evaluation.qa_evidence` adds internal atomic extracted-output capture and owner-only revisioned human review. This slice introduced `eval_0006`; preserve deployed revisions and Harness ledger. `EvidenceProtection` requires the explicit request-encryption key, binds output/review envelopes to owner/project/run/ordinal/sample/plan/observation, and exposes no plaintext output hashes. Metadata reads exclude Q/A/gold/ciphertext; sensitive opens and reviews verify snapshots off-loop, recheck under the run lock and audit atomically. Human decisions append; absent evidence cannot PASS. `/workspace/datasets` adds the explicit review panel; no new execution or output-upload route, automatic target/model calls, Worker, independent-team arbitration or acceptance verdict. See [scope](docs/DevPilot_QA_Evidence_Review.md).

## Internal durable dispatch journal (2026-11-08)

`app.evaluation.dispatch_journal` persists owner-scoped technical metadata only (`dispatch_journal_only`). This slice used App head `eval_0006`; deployed migrations and Harness ledger are unchanged. Per-run DB row writes serialize one-way ordinal dispatch, concurrency and non-recycled response reservations (`max_response_bytes + 1`). A future independently admitted caller must confirm dispatch commit before sending; uncertain writes never return permission to send/retry. Expired leases interrupt the whole run, never reclaim slots for continuing. No network, input/gold/ciphertext reads, output evidence, API, reaper or verdict. `recording_finished` is not PASS. See [scope](docs/DevPilot_Durable_Dispatch_Journal.md).

## Internal bounded QA attempt collection (2026-11-08)

`app.evaluation.qa_attempts` performs one application-level send via the shared DNS-pinned transport, bounded raw response retention and total attempt timeout. No gold, verdict, retry, execution route or persistence. `output_collected` is not PASS; timeout/transport error is uncertain delivery. Cancellation propagates. The future durable caller must authorize and journal dispatch before calling, enforce run-wide budgets, and never resend uncertain attempts. Output is sensitive internal data with repr suppression, not a public/evidence DTO. Existing execution paths are not switched. See [scope](docs/DevPilot_Bounded_QA_Attempts.md).

## Frozen QA plan workspace (2026-11-08)

`EvaluationPlanPanel` on `/workspace/datasets` is keyed by project. Explicit source reads load only request/QA/plan metadata. Strict `plan-form` builds the existing frozen-definition DTO; edits, refresh and submission revoke confirmation. Keep page-memory-only state, write ref locking, stale-response tokens, and an explicit metadata refresh after any failed/unknown write. No target calls, gold reads, auto-retry, execution authority or model requirement. Root-string output is opt-in; pointer whitespace is literal. See [UI scope](docs/DevPilot_Frozen_QA_Plan_UI.md).

## Frozen QA JSON plans (2026-11-08)

The frozen-plan slice introduced `eval_0004`; its original App head was `eval_0006`. `app.evaluation.plan_repository` freezes same-owner/project/component request versions, gold-bound QA revision/hash, strict JSON mappings and bounded limits after all-input preflight. Decryption audit and plan/audit commit atomically. `frozen_definition_only` is NOT execution authorization, evidence or a Worker; the workspace plan UI consumes these routes without adding execution authority. Metadata reads exclude gold/ciphertext. Never pass expected answers to rendering. See [scope](docs/DevPilot_Frozen_QA_Plans.md).

## QA JSON wiring core (2026-11-08)

devpilot.qa_json_binding.QAJSONBinding prepares immutable request copies and extracts JSON text with strict bounded pointers, exact decimal preservation and no gold/network/model access. The plan API now consumes it for input-only preflight; the confirmation UI consumes plan routes; actual Worker execution remains pending. See [scope](docs/DevPilot_QA_JSON_Binding.md).

## Request-version workspace UI (2026-11-08)

The cURL debugger can explicitly save an encrypted request snapshot to an owner-scoped project component, or list public metadata without importing a request. Keep page-memory-only values, separate storage/send consent, generic errors, no automatic retries, write locking and scope resets. No plaintext retrieval or execution is added. The separate operator key remains mandatory, never generated by the UI. See [delivery](docs/DevPilot_Request_Version_UI.md).

## Encrypted request definitions (2026-11-08)

The request-version slice introduced `eval_0003`; current App migration head is `eval_0006`, after unchanged `eval_0001/eval_0002`. `devpilot.request_versions.FrozenRequest` is deep-immutable; protected serialization contains secrets and is never a public DTO. `app.evaluation.request_version_repository` appends owner-scoped complete-request ciphertext under explicit `DEVPILOT_REQUEST_ENCRYPTION_KEY`; no key fallback/generation. Public metadata queries exclude ciphertext; write requires write+review, human confirmation and rejects internal Agents. Crypto is thread-offloaded; open is internal/audited, not an executor. No plaintext/open/execute/update/delete HTTP routes. The later workspace UI adds explicit save and metadata browsing. `request_definition_only` is not approval, evidence or a credential-reference vault. See [scope](docs/DevPilot_Request_Versions.md).

## Stable navigation / workspace styles (2026-11-08)

The sidebar brand/product groups never insert route-dependent creation rows. New-chat creation belongs to conversation content; assistant management is not a new conversation. WorkspaceStyleProvider applies an allowlisted browser-only preference on workspace routes, independently of next-themes light/dark. Presets must keep semantic statuses unchanged and pass contrast/keyboard/mobile regressions. Before pushing, run the **entire** frontend Prettier check, including Markdown guides; lint/typecheck alone does not cover CI formatting. See [delivery](docs/DevPilot_Workspace_Styles_CI.md).

## Authenticated assistants / request-template slice (2026-11-07)

`AgentsApiConfig.enabled` now defaults true. All authenticated accounts may manage their own assistants; keep auth middleware, owner scoping and explicit operator opt-out. Private profile routes use `users/{user_id}/USER.md`, with threaded/atomic I/O and no legacy global fallback. Operator-provisioned legacy shared agents remain a compatibility read fallback, not other users' personal agents.

`devpilot.request_templates` is pure configuration-only wiring: all request values become explicit references; method/origin/header names remain. `/api/component-tests/debug/template` and the debugger download do not send, persist, certify debugging, resolve secrets, or create execution plans/evidence. Fingerprint is structural integrity, not a signature or secret/value binding. Never send `resolve()` output without fresh policy/consent. See [delivery](docs/DevPilot_Assistants_Request_Templates.md).

## Navigation / shared outbound slice (2026-11-07)

Evaluation component calls share app.evaluation.http.PinnedEvaluationTransport across debugger/manual/scheduled paths. Manual admission requires runs:create and checks policy before creating a run. Custom-assistant navigation is hidden when disabled; do not bypass its operator gate to remove grey UI. Full RequestSpec execution/credential references remain pending. See [scope](docs/DevPilot_导航与统一出站基线.md).

## Project component/submission inventory (2026-11-07)

`app.evaluation.registry` and `registry_repository` link owner-owned legacy components to projects and frozen QA versions. The inventory slice introduced `eval_0002`; do not edit deployed revisions (current head `eval_0005`). SQL selects only safe inventory columns, never legacy endpoints/tokens/criteria. Server-built immutable snapshots have `scope=inventory_only`: NOT RequestSpec locks, executable plans, acceptance or report evidence. Submission creation requires write+review and explicit confirmation; rejects internal Agent callers. See [inventory slice](docs/DevPilot_项目组件与提测清单.md).

## Project / QA data slice (2026-11-07)

`devpilot.datasets` owns pure import/fingerprint primitives. `app.evaluation` owns project/QA DTOs, tables, repository and independent Alembic migrations (`devpilot_alembic_version`, `eval_0001`); never add App imports to Harness. `/workspace/datasets` and `/api/evaluation/projects` enforce owner scope and separate read/write/review permissions. Gold answers use a separate table/read route and never normal chat or persistent browser cache. Freeze is explicit self-review with revision/hash checks, not independent approval or acceptance. No Agent generation or execution/run/report linkage yet; the later inventory slice adds non-executable component/submission bindings. See [QA slice](docs/DevPilot_QA数据最小闭环.md).

## Report assistant slice (2026-11-07)

`app.reporting.assistant` reuses the existing model factory and a single tool-free LangGraph agent. `reports_agent` is operator config, off by default and explicitly names a model. Only validated aggregate metrics enter the model; no free text/identity/evidence. POST assistant requires threads:write, runs:create and per-request consent; no memory, tool execution, report approval or knowledge writes. User-confirmed advice is a separate, unverified appendix bound to facts hash and template version, never metric updates. Client-returned advice and claimed model are unauthenticated. See module guides and report design; provider telemetry policies still require review.

## Reports slice (2026-11-07)

`devpilot.reporting` is a pure, version-pinned manual draft renderer. Gateway `/api/reports/templates` and `/api/reports/preview` enforce existing thread read/write permissions; `/workspace/reports` offers entry and Markdown/JSON downloads. Facts and template snapshots are included, but hashes are not signatures. This is stateless, unverified input: no report publication, persistent revision history, template uploads or acceptance decisions. See [report design](docs/DevPilot_报告模块设计.md). Keep published template versions immutable and old downloads invalidated after any input/version change. Never commit customer scenario names, historical aggregate metrics or original materials.

This file provides guidance to AI coding agents (Claude Code, Codex, and others) when working with code in this repository. It is the source of truth; the sibling `CLAUDE.md` imports it via `@AGENTS.md`.

It is the **monorepo orientation layer**: it maps the whole repo and points to the
module guides that own the depth. For anything inside a module, read that module's
guide rather than expecting full detail here:

- **[backend/AGENTS.md](backend/AGENTS.md)** — backend depth: harness/app split, agent &
  middleware chain, sandbox, MCP, skills, memory, IM channels, persistence/migrations,
  config system, test layout.
- **[frontend/AGENTS.md](frontend/AGENTS.md)** — frontend depth: Next.js App Router layout,
  thread/streaming data flow, code style, commands.

## Material and CI calibration (2026-11-07)

Read [the sanitized material analysis](docs/DevPilot_历史材料分析与设计校准.md) and [the isolated CI guide](docs/DevPilot_CI修复与隔离开发环境.md).
Keep raw customer files, reference answers, credentials and internal endpoints out of Git and model context. BASELINE/ACCEPTANCE and metric populations are accepted only as unverified manual report facts in the new preview slice, not as implemented execution/acceptance capabilities in component-tests; weighted scoring remains planned. Do not infer numerical accuracy from output shape or silently default acceptance thresholds.

## DevPilot Product Direction (2026-11-06)

DevPilot is being specialized into an **AI component evaluation workbench and
bounded evaluation Agent**, not a general coding SaaS. Read
[docs/README.md](docs/README.md) and the linked baseline audit before implementing.
The revised documents describe a target design, not completed runtime features.

- Prioritize authorized, reviewed, versioned datasets and reproducible evidence.
- Agents propose/generate/explain; deterministic services enforce execution,
  denominators, budgets, approvals, and acceptance. Missing evidence is never PASS.
- Keep App → Harness and App → devpilot dependencies; do not add business imports
  to the harness. Keep raw acceptance answers separate from ordinary memory/RAG.
- Retain legacy APIs/chat until explicitly migrated. Hide/disable non-core features
  before deletion; do not claim an evaluation profile switch already exists.
- Use one RequestSpec and versioned execution core for debug, platform runs and
  optional standalone exports. Do not implement independent LLM-generated runners.
- Human review uses one task service for the review center and inline results;
  keep observations, automatic judgments, human decisions and assessments separate.
- Maintain project documentation in Chinese and English only; do not delete
  runtime locales or licenses as part of documentation cleanup.
- The complete evaluation lifecycle remains planned. Implemented workspace slices
  now cover cURL debugging, evaluation scheduling, project report drafts/intake
  and administrator model management; see
  [delivery and configuration](docs/DevPilot_Evaluation_Workspace.md) for actual
  boundaries. Existing component-tests still has known durability, dataset,
  unified-egress and export gaps; do not treat the new slices as final acceptance.

## What is DeerFlow

DeerFlow is a LangGraph-based AI super-agent system with a full-stack architecture. The
backend runs a "super agent" with sandboxed execution, persistent memory, subagent
delegation, and extensible tools (built-in, MCP, community), all per-thread isolated. The
frontend is a Next.js chat UI. External IM platforms (Feishu, Slack, Telegram, Discord,
DingTalk) bridge into the same agent through the Gateway.

## Docker health and startup ordering (2026-11-08)

Both Compose templates define bounded, quiet exec-form probes: Gateway's loopback `/health`, frontend's unauthenticated loopback `/login` (exact 200 headers only, no redirects/body), and nginx's fixed `/nginx-health`. Nginx waits for both upstream healthchecks at initial Compose startup; no dependency restart cascade/auto-heal is installed. `unless-stopped` still handles process exits, not unhealthy-but-running services. These are minimal HTTP/process signals, not database/asset/model/target acceptance, and template edits do not update existing containers. Offline contracts live in `backend/tests/test_compose_service_health.py`; see [operations and boundaries](docs/DevPilot_Docker_Diagnostics.md). Do not replace incident diagnosis with automatic restarts/resends.

## Service Topology

A single `make dev` / Docker stack runs four cooperating services:

| Service         | Port   | Role                                                                |
| --------------- | ------ | ------------------------------------------------------------------- |
| **Nginx**       | `2026` | Unified reverse-proxy entry point — open this in the browser        |
| **Gateway API** | `8001` | FastAPI REST API + embedded LangGraph-compatible agent runtime      |
| **Frontend**    | `3000` | Next.js web interface                                               |
| **Provisioner** | `8002` | Optional — only when sandbox is configured for provisioner/K8s mode |

Nginx is the single public entry: it serves the frontend and proxies `/api/langgraph/*`
to the Gateway's LangGraph runtime, rewriting it to Gateway's native `/api/*` routes; all
other `/api/*` go straight to the Gateway REST routers. See
[backend/AGENTS.md](backend/AGENTS.md) for the runtime and router detail.
It compresses HTML and configured textual assets, while deliberately leaving SSE,
fonts, images, audio, and video uncompressed at the proxy layer.

Both compose files publish that entry as `"${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"`
— **loopback by default**, matching the README's documented deployment model. A bare
`"${PORT}:2026"` binds `0.0.0.0`, which does not.
Nginx itself listens `default_server` on IPv4+IPv6 and the
Gateway binds `0.0.0.0:8001` inside the container on purpose — both are container-
internal; the published nginx port is the entire external surface, and the Gateway's
`8001` is deliberately not published. Any new published port needs an explicit bind
address; `backend/tests/test_compose_default_bind_host.py` pins this for every service
in both compose files.

## Repository Map

```
deer-flow/
├── Makefile                        # Root orchestration: drives the full stack (dev/start/stop, docker, setup)
├── config.example.yaml             # Template → copy to config.yaml (gitignored) at repo root
├── extensions_config.example.json  # Template → copy to extensions_config.json (gitignored): MCP servers + skills
├── backend/                        # Python backend — see backend/AGENTS.md
│   ├── Makefile                    # Per-module backend commands (dev, gateway, test, lint, migrate-rev)
│   ├── packages/extension-api/     # deerflow-extension-api package (import: deerflow_extension_api.*) — public extension contract
│   ├── packages/harness/           # deerflow-harness package (import: deerflow.*) — agent framework
│   └── app/                        # FastAPI Gateway + IM channels (import: app.*)
├── frontend/                       # Next.js frontend (pnpm) — see frontend/AGENTS.md
├── devpilot/                       # AI component-test toolkit core (import: devpilot.*) — pure logic + httpx outbound, zero DeerFlow dependency; evaluated via the Gateway's component-tests router
├── docker/                         # docker-compose files, nginx config, provisioner
├── skills/                         # Agent skills: public/ (committed), custom/ (gitignored)
│                                    # Managed integration skill packs are global at .deer-flow/integrations/skills/{provider}/
│                                    # Integration credentials and enabled state remain per-user
├── contracts/                      # Cross-component JSON contracts (e.g. subagent status, skill review)
├── scripts/                        # Root orchestration scripts invoked by the Makefile (check, configure, doctor, support_bundle, serve, nginx, docker, deploy, setup_wizard)
├── tests/                          # Root-level tests (currently tests/skills/ — public skill tests)
└── docs/                           # Cross-cutting docs, plans, and design notes
```

Third-party extensions are loaded from a top-level `plugins:` list in `config.yaml`
(operator-controlled on purpose — that list causes code to be imported, so it is deliberately
kept out of the API-writable `extensions_config.json`). See the Extension System section in
[backend/AGENTS.md](backend/AGENTS.md).

Runtime config lives at the **repo root**: copy `config.example.yaml` → `config.yaml`
(main app config) and `extensions_config.example.json` → `extensions_config.json` (MCP
servers + skills). Both real files are gitignored and may be edited at runtime via the
Gateway API. Config schema and resolution order are documented in
[backend/AGENTS.md](backend/AGENTS.md).

Skill quality review note:

- `skills/public/skill-reviewer/` is the built-in read-only skill quality reviewer.
  It uses the harness-layer `review_skill_package` tool and contracts in
  `contracts/skill_review/`. Model-visible review data is compact and
  tag-neutralized; full raw payloads stay in tool artifacts. See
  [backend/AGENTS.md](backend/AGENTS.md) for the non-activation, SkillScan, and
  `skill-creator` ownership boundaries.

Scheduled-task note:

- The scheduled-task MVP adds a workspace page at `/workspace/scheduled-tasks` plus a background scheduler service gated by `config.yaml -> scheduler.enabled`.
- Scheduled background runs are intentionally non-interactive: they execute through the normal run lifecycle, but the lead-agent toolset excludes `ask_clarification` when `context.non_interactive=true`. The key is honored only for internally-authenticated callers (the scheduler launch path); client-supplied `context.non_interactive` is dropped.

## Commands: Root vs. Module

**Root `make` targets drive the whole stack** (run from the repo root):

```bash
make setup       # Interactive setup wizard (recommended for new users)
make doctor      # Check configuration and system requirements
make support-bundle  # Generate redacted troubleshooting summary, AI issue draft, and optional zip
make config      # Generate local config files from the examples
make check       # Check that required tools are installed
make install     # Install all dependencies (frontend + backend + pre-commit hooks)
make dev         # Start all services with hot-reload (Gateway + Frontend + Nginx)
make start       # Start all services in production mode (local, optimized)
make stop        # Stop all running services
make up / down   # Build/stop the production Docker stack (browser at localhost:2026)
make docker-start / docker-stop / docker-logs   # Docker development environment
```

Docker log and restart commands resolve `DEER_FLOW_ROOT` from the current
checkout before invoking Compose, matching the start and stop commands.

Run `make help` for the full list.

**Per-module commands drive a single module** (run inside that module):

```bash
# Backend (see backend/AGENTS.md for the full set)
cd backend && make dev        # Gateway API with reload (port 8001)
cd backend && make test       # Backend test suite
cd backend && make lint       # ruff check
cd backend && make format     # ruff format

# Frontend (see frontend/AGENTS.md for the full set)
cd frontend && pnpm dev       # Dev server with Turbopack (port 3000)
cd frontend && pnpm check     # Lint + type check (run before committing)
cd frontend && pnpm test      # Unit tests
```

Rule of thumb: **root `make` = the full application**; **`backend/Makefile` and `frontend/`
(`pnpm`) = per-module work.**

Host-side pnpm consumers, including the root/frontend Makefiles and local diagnostic scripts, must run through `scripts/pnpm.py`. Diagnostic scripts resolve the runner and frontend directory to absolute paths before changing the child process working directory, so they remain independent of the caller's current directory. The runner preserves direct `pnpm`/`pnpm.cmd` priority, falls back to `corepack pnpm`, and is invoked from `frontend/` so Corepack honors the package-manager version pinned by that project.

Docker incident diagnosis: `python scripts/docker_health.py --project devpilot-local` (or `make docker-health DOCKER_HEALTH_PROJECT=<actual-compose-project>`) runs without backend dependencies. It reads only bounded, allowlisted Docker metadata for the selected project and host disk capacity; never logs/env/mounts/configuration, target/model requests or recovery actions. A maximum of three CLI commands have per-command timeouts and a shared deadline. Unknown disk readings stay unknown; absent healthchecks and historical restart/OOM flags are warnings, not root-cause/readiness proof. Keep accounts/configuration/volumes intact; never add automatic Desktop restarts, prune or execution retry. Synthetic tests: `backend/tests/test_docker_health.py`.

## Where to Go Next

- Backend work → **[backend/AGENTS.md](backend/AGENTS.md)**
- Frontend work → **[frontend/AGENTS.md](frontend/AGENTS.md)**
- Setup & install → **[Install.md](Install.md)**, **[CONTRIBUTING.md](CONTRIBUTING.md)**
- Project overview & usage → **[README.md](README.md)** (DevPilot); upstream reference:
  **[English](README_upstream.md)** and **[中文](README_zh.md)**
- Security policy → **[SECURITY.md](SECURITY.md)**
- Changes → **[CHANGELOG.md](CHANGELOG.md)**
- Cutting a release → **[RELEASING.md](RELEASING.md)**

## Cross-Cutting Conventions

Production frontend compilation belongs to the Docker builder stage, never container startup. The production image starts Node directly; Compose production must preserve that command. Keep development hot reload explicit. Contract tests: `backend/tests/test_frontend_docker_runtime.py`. Local overrides are private, must preserve existing mounts/configuration and must not introduce `build && start`.

These apply repo-wide; module guides own the module-specific detail.

- **Documentation update policy** — keep docs in sync with code: update `README.md` for
  user-facing changes and the relevant `AGENTS.md` for development/architecture changes in
  the same change set.
- **Test-driven development** — features and bug fixes ship with tests. Backend tests live
  in `backend/tests/` (TDD is mandatory there; see [backend/AGENTS.md](backend/AGENTS.md));
  frontend tests live in `frontend/tests/`.
- **Format before pushing** — run `make format` (backend) / `pnpm check` (frontend). Backend
  CI enforces `ruff format --check`, so formatting must be clean before a push.

## Connection profiles and multi-turn intake (2026-11-07)

Managed model protocols are allowlisted OpenAI Chat, OpenAI Responses, Anthropic Messages and Gemini Developer API; keep the old openai_compatible wire ID. Only controlled ModelParameters are API-writable. Never copy credentials on duplication; endpoint/protocol changes require new credentials or explicit clear_credential. Preserve catalog_from_env/catalog_signature/overlay_models integration and role precedence. Responses uses store=false; Gemini explicitly disables Vertex mode.

Report intake accepts bounded client-held message/proposal turns, not arbitrary roles: at most 10 rounds, current message 4000 characters, serialized context 24000 characters. Require fresh consent per round; suggestions are unverified and cannot update metrics. No memory/store/tools/persistent conversation. /workspace defaults to /workspace/evaluations; chat remains a secondary compatible route. Keep inventory counts distinct from acceptance statistics and label unfinished capabilities honestly. See the implementation matrix in docs for the remaining lifecycle gaps.
