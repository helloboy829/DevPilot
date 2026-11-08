# DevPilot

**Frozen QA Word drafts:** explicitly download `.docx` from an opened historical archive, including real component tables, draft labels and receipt metadata. No current-template recomputation, model calls or automatic approval. [Workflow and limits](docs/DevPilot_QA_Word_Draft_Export.md).

**Verified local deployment (2026-11-08):** Docker Desktop recovered after an authorized restart, and an online-backup-protected gateway/frontend update deployed feature SHA `59ab6304cd842af3e5222a17dfb41a10d7d52894` at App head `eval_0008`. Existing accounts, evaluation rows, configuration hashes and mounts were verified unchanged. All authenticated users can manage their own assistants; no model is configured yet, and QA execution remains explicitly disabled. [Recovery procedure and verification limits](docs/DevPilot_Local_Recovery_and_Upgrade.md). All six triggered GitHub Actions passed for that exact feature SHA. This is not real-model/target acceptance; documentation-only follow-ups have their own CI results.

**QA execution and human review:** freeze a request/data/mapping plan, separately authorize bounded execution, collect encrypted output, then inspect Q, actual A, reference and source in **Projects & datasets**. Worker enablement is operator-owned/default-off and requires the explicit key and destination policy. Unknown sends are never retried; collection is not quality PASS. [Execution and cancellation scope](docs/DevPilot_Admitted_QA_Execution.md) · [Encrypted evidence/review](docs/DevPilot_QA_Evidence_Review.md).

**Verified human summary preview:** explicitly load a selected effectiveness run's summary. Latest human PASS / all frozen-plan samples is shown alongside unreviewed/uncertain/technical blockers. Changing cases or scope invalidates the preview. Complete review is not project approval or an archived report. [Formula, integrity and permissions](docs/DevPilot_Verified_QA_Summaries.md).

**Immutable multi-component QA report drafts:** Reports can explicitly bind fully reviewed platform runs to pinned template versions, freeze the historical Markdown, and append new revisions without overwriting earlier results. Server metrics only; still not formal approval. Unknown writes reconcile by the same archive ID, never automatic retry. [Workflow and limits](docs/DevPilot_Immutable_QA_Report_Archives.md).

**AI component evaluation workspace and bounded evaluation agents**, built on ByteDance DeerFlow. Targets include AI/CV models, LLMs and agents. [中文](README_zh.md) · [Design index](docs/README.md) · [Delivery and configuration](docs/DevPilot_Evaluation_Workspace.md)

> Development preview, not a complete unattended acceptance system. Measured evidence, model suggestions and human decisions remain separate.

Plan confirmation: open **Projects & datasets → select project → Frozen QA plans**. Select encrypted request metadata and a frozen QA revision, enter literal JSON pointers and bounded limits, then explicitly confirm a definition-only freeze. No target request is sent. [Workflow and limits](docs/DevPilot_Frozen_QA_Plan_UI.md).

The [single-attempt collector](docs/DevPilot_Bounded_QA_Attempts.md) and [durable dispatch journal](docs/DevPilot_Durable_Dispatch_Journal.md) now serve the separately admitted QA Worker. Their original scope notes describe earlier internal slices. Plan freeze itself still sends no requests, and legacy evaluation paths are not silently redirected.

## Workspace appearance and navigation

The evaluation-first sidebar keeps stable Evaluation center and AI collaboration groups. Opening Chats or Custom assistants no longer inserts a new-chat row above the menu; create conversations inside Chats (or use the command palette). Assistant management does not open a conversation.

**Settings → Appearance → Workspace style** offers Precision console, Graphite minimal, Forest lab, Paper studio and Violet atelier. Each works with light, dark or system mode. Preferences are browser-local, not account settings or evaluation facts. Keyboard selection and mobile layouts are supported. [Scope and CI verification](docs/DevPilot_Workspace_Styles_CI.md).

## Available workspace slices

| Page | Implemented scope |
| --- | --- |
| `/workspace/evaluations` | Default evaluation-first landing page with real component inventory and explicit remaining capabilities |
| `/workspace/datasets` | Owner-scoped projects, QA import/review/freeze, existing-component links, immutable inventory-only submissions, frozen QA plans and revisioned human result review |
| `/workspace/component-tests` | Existing component registration/effect/performance prototype, plus paste/import/edit/send cURL and inspect/copy bounded responses |
| `/workspace/evaluation-schedules` | One-off/cron/timezone schedules, frozen bounded parameters, pause/resume/history; deterministic evaluation dispatch, not scheduled chat or push delivery |
| `/workspace/reports` | Verified immutable multi-component QA archives and revisions, plus separate manual/Agent drafts; pinned Chinese/English templates and frozen Markdown/Word draft downloads |
| `/workspace/models` | Connection profiles for OpenAI Chat, OpenAI Responses, Anthropic and Gemini; controlled parameters, encrypted write-only credentials, probes and default/report role routing |
| Chat | Existing harness conversation and per-conversation model selection, not the evaluation evidence ledger |

The unified local entry point is `http://127.0.0.1:2026`. See [Install.md](Install.md), [AGENTS.md](AGENTS.md) and module guides for installation and full-stack `make dev`/Docker commands. Do not commit local configuration, credentials or customer materials.

## Assistants and request templates

Custom assistants are enabled by default for **all authenticated users**, not only administrators. Each account manages its own assistants and private profile; operators can still opt out with `agents_api.enabled: false`. The legacy global `USER.md` is retained but is not exposed through the private profile API. Model-backed conversations still require a configured model; enabling assistant management does not configure one.

The cURL debugger can export a **parameterized request template** (`request-template.v1`) with a structural SHA-256 fingerprint. Full URL/path/query, every header value and the body are replaced with explicit runtime references. Only method, origin and header names remain: review those as potentially sensitive metadata. This configuration-only download is not a persisted request version, executable test script, target authorization, debug-success certificate or evaluation evidence. See [delivery details](docs/DevPilot_Assistants_Request_Templates.md).

## Navigation and outbound baseline

Evaluation pages have one component-test navigation entry. Custom assistant management defaults to enabled for signed-in users; an operator opt-out hides its link rather than leaving a disabled placeholder; it is not the report assistant or evaluation executor. Debug, manual and scheduled component calls now share host/DNS/TLS enforcement. An empty operator allowlist also blocks manual runs. See [scope and remaining work](docs/DevPilot_导航与统一出站基线.md).

## Important boundaries

- **Project inventories:** link existing owner-owned components to frozen QA revision/hash and create multiple immutable inventory-only submission versions. Server snapshots exclude endpoints, credentials and gold. This is not a locked request/executable plan, test verdict or report evidence. See [inventory delivery](docs/DevPilot_项目组件与提测清单.md).

- **Request debugger:** parses one complete cURL without running a shell or reading files. Review method/URL/headers/body and explicitly authorize sending. Operator host approval, DNS pinning, TLS verification, no redirects/environment proxies, bounded timeout/response. Not a full Postman replacement: no multipart uploads, cookie jar, collections/environments, scripts or runnable test export yet. Debug data is not persisted or automatically promoted into an approved evaluation specification.
- **Off-peak evaluations:** require `scheduler.enabled: true` and approved destination hosts. Plans do not copy component credentials, reject changed target configuration, and recheck owner permissions at launch. Scheduled effect calls collect outputs for manual review, without implicit disclosure to an LLM judge. The existing scheduler provides leases/history/non-overlap, but component execution remains process-local rather than a durable worker queue. Pausing/deleting does not cancel an active run.
- **Project reports:** stage each component from the form, then generate one project draft. Snapshots are independent; remove/restage after changes. Shared project/tester/period/mode must match. No cross-component averaging of unrelated accuracy or latency. Reports are manual/unverified drafts kept in page memory; download before leaving. No persistence, formal approval, DOCX/PDF export or full reference-DOCX layout reproduction.
- **Reference templates:** only the generic structure of authorized local reports is reused. No private project names, historical measured metrics or source report text is committed. Template ID/version and facts/template hashes are pinned; future template updates must be new versions.
- **Report agent:** reuses the harness model factory and a tool-free LangGraph agent. Explicit opt-in requirements → structured proposed fields/questions → human confirmation → real counters entered by the evaluator. Bounded multi-turn intake (at most 10 rounds) is held in page memory, not persistent dialogue. A separate opt-in advisor sees allowlisted aggregate metrics only. Neither can invent measurements, alter counters or approve reports.
- **Metrics:** effect pass rate uses the full denominator. Errors/pending/not-run remain visible. TTFT applies only to observable content-bearing streaming responses; missing/inapplicable metrics are not zero or automatic PASS.

## Model management

Set `DEVPILOT_MODEL_CATALOG_DIR` to a private persistent Gateway directory. Administrators can add OpenAI Chat, OpenAI Responses, Anthropic Messages or Gemini Developer API model profiles, update metadata, test a fixed non-business prompt with explicit consent, and assign roles. Keys are write-only; an omitted key retains the prior value. SQLite catalog payloads are Fernet-encrypted. Supply `DEVPILOT_MODEL_ENCRYPTION_KEY` through secret management, or protect the generated separate `catalog.key`. Back up the encrypted database and key securely; same-volume encryption is not a KMS, and Windows ACLs require operator care.

`general_agent` controls the default platform model; chat may override it. `report_advisor` enables report intake/advice, still requiring per-call consent. Dataset generation, evaluation judge and review assistant are **reserved bindings only**, not completed pipelines. Platform working models are separate from evaluated targets. No real provider is configured by this change and no customer/provider call is required for mock tests.

Operator models in `config.yaml` remain operator-owned. Preserve the `deerflow` package, compatibility keys/environment variables, upstream attribution and license; user-facing product branding is DevPilot.

## Current delivery status

The report requirements assistant now supports a bounded, visible multi-turn conversation (10 rounds, 24000-character serialized context, page memory only). Every turn requires consent; confirming fields never alters measured metrics. Model profiles support custom provider labels/endpoints/model IDs, duplication without credentials, and explicit credential decisions when changing endpoints or protocols. This borrows connection-management patterns, not full CC Switch compatibility.

See the [implementation matrix](docs/DevPilot_实现进度与下一步.md) for delivered, partial and unimplemented capabilities. The QA foundation now supports strict JSON/JSONL import, owner isolation, separately authorized reference access, optimistic revisions and explicit self-reviewed freezing. This is not independently approved data or acceptance: source authorization is user-attested, the data has not been linked to components/runs/reports, and no Agent builds data yet. Full governance, a result-review center, durable execution, standalone exports and formal report/template lifecycle remain unfinished. See the [QA slice boundaries](docs/DevPilot_QA数据最小闭环.md).

## Next milestones

1. Link project/component submission versions and frozen QA data to execution; add independent review, quality cards and cross-set leakage controls.
2. Confirmed RequestSpec integration with all evaluation adapters and reproducible runnable exports.
3. Human-review workbench, evidence-linked persistent reports and template revision/approval history.
4. Durable execution, quotas/cancellation, security policy across legacy execution paths and audit.
5. Explicitly authorized judge-model integration and reviewed knowledge promotion, not automatic training.

New features ship with backend tests and frontend browser/API regressions. Backend: Ruff format/check and pytest/toolkit tests. Host pnpm commands go through `scripts/pnpm.py`; frontend: `check`, unit tests and Playwright. See [backend](backend/AGENTS.md), [frontend](frontend/AGENTS.md), [upstream](README_upstream.md) and [LICENSE](LICENSE).

### Manual evaluation assistants

Every signed-in user can use **Custom assistants → Configure manually** to save an assistant without a model call, with bilingual requirements, dataset-design and result-review presets. Conversations still need a configured model. These are advisory configurations, not sandboxed test executors or official acceptance. Private assistants remain account-scoped; the Reports module remains the report-generation entry.

### Encrypted request-definition versions

Project/component request versions can now be saved append-only through the authenticated API. Complete URL, header values and body are encrypted under a separate operator key; public reads return only structural metadata. App migration `eval_0003` preserves earlier tables and ledgers. This is not an execution plan, a successful-debugging attestation, a credential-reference vault or report evidence. The component debugger now offers **Save request version** (current edited snapshot) and **View request versions** (metadata only, no import needed), with project/component selection and separate storage confirmation. Saving does not send a request. Saving requires explicit `DEVPILOT_REQUEST_ENCRYPTION_KEY` provisioning; existing local settings are not changed. See [scope and operations](docs/DevPilot_Request_Versions.md).

Request-version UI boundaries, failure recovery and the remaining frozen-plan/worker milestones are documented in [the workspace delivery](docs/DevPilot_Request_Version_UI.md).

### QA JSON wiring prerequisite

The pure QA JSON binding core now maps input into an existing request string field and extracts response text with explicit bounded pointers, without gold answers or network access. It now underpins the frozen-plan API/UI; durable Worker execution is still pending. See [contract and remaining milestones](docs/DevPilot_QA_JSON_Binding.md).
