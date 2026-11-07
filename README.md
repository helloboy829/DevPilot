# DevPilot

**AI component evaluation workspace and bounded evaluation agents**, built on ByteDance DeerFlow. Targets include AI/CV models, LLMs and agents. [中文](README_zh.md) · [Design index](docs/README.md) · [Delivery and configuration](docs/DevPilot_Evaluation_Workspace.md)

> Development preview, not a complete unattended acceptance system. Measured evidence, model suggestions and human decisions remain separate.

## Available workspace slices

| Page | Implemented scope |
| --- | --- |
| `/workspace/evaluations` | Default evaluation-first landing page with real component inventory and explicit remaining capabilities |
| `/workspace/datasets` | Owner-scoped projects, QA import/review/freeze, existing-component links and immutable inventory-only submission versions |
| `/workspace/component-tests` | Existing component registration/effect/performance prototype, plus paste/import/edit/send cURL and inspect/copy bounded responses |
| `/workspace/evaluation-schedules` | One-off/cron/timezone schedules, frozen bounded parameters, pause/resume/history; deterministic evaluation dispatch, not scheduled chat or push delivery |
| `/workspace/reports` | Manual single-component and multi-component project snapshots, pinned Chinese/English templates, Markdown/JSON draft downloads |
| `/workspace/models` | Connection profiles for OpenAI Chat, OpenAI Responses, Anthropic and Gemini; controlled parameters, encrypted write-only credentials, probes and default/report role routing |
| Chat | Existing harness conversation and per-conversation model selection, not the evaluation evidence ledger |

The unified local entry point is `http://127.0.0.1:2026`. See [Install.md](Install.md), [AGENTS.md](AGENTS.md) and module guides for installation and full-stack `make dev`/Docker commands. Do not commit local configuration, credentials or customer materials.

## Navigation and outbound baseline

Evaluation pages have one component-test navigation entry. Custom assistant management is optional: its link appears only when enabled, rather than a disabled placeholder; it is not the report assistant or evaluation executor. Debug, manual and scheduled component calls now share host/DNS/TLS enforcement. An empty operator allowlist also blocks manual runs. See [scope and remaining work](docs/DevPilot_导航与统一出站基线.md).

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
