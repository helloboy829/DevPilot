# DevPilot

**AI component evaluation workspace and bounded evaluation agents**, built on ByteDance DeerFlow. Targets include AI/CV models, LLMs and agents. [中文](README_zh.md) · [Design index](docs/README.md) · [Delivery and configuration](docs/DevPilot_Evaluation_Workspace.md)

> Development preview, not a complete unattended acceptance system. Measured evidence, model suggestions and human decisions remain separate.

## Available workspace slices

| Page | Implemented scope |
| --- | --- |
| `/workspace/component-tests` | Existing component registration/effect/performance prototype, plus paste/import/edit/send cURL and inspect/copy bounded responses |
| `/workspace/evaluation-schedules` | One-off/cron/timezone schedules, frozen bounded parameters, pause/resume/history; deterministic evaluation dispatch, not scheduled chat or push delivery |
| `/workspace/reports` | Manual single-component and multi-component project snapshots, pinned Chinese/English templates, Markdown/JSON draft downloads |
| `/workspace/models` | Administrator model catalog, write-only encrypted credentials, explicit connectivity probes, default/report role assignments |
| Chat | Existing harness conversation and per-conversation model selection, not the evaluation evidence ledger |

The unified local entry point is `http://127.0.0.1:2026`. See [Install.md](Install.md), [AGENTS.md](AGENTS.md) and module guides for installation and full-stack `make dev`/Docker commands. Do not commit local configuration, credentials or customer materials.

## Important boundaries

- **Request debugger:** parses one complete cURL without running a shell or reading files. Review method/URL/headers/body and explicitly authorize sending. Operator host approval, DNS pinning, TLS verification, no redirects/environment proxies, bounded timeout/response. Not a full Postman replacement: no multipart uploads, cookie jar, collections/environments, scripts or runnable test export yet. Debug data is not persisted or automatically promoted into an approved evaluation specification.
- **Off-peak evaluations:** require `scheduler.enabled: true` and approved destination hosts. Plans do not copy component credentials, reject changed target configuration, and recheck owner permissions at launch. Scheduled effect calls collect outputs for manual review, without implicit disclosure to an LLM judge. The existing scheduler provides leases/history/non-overlap, but component execution remains process-local rather than a durable worker queue. Pausing/deleting does not cancel an active run.
- **Project reports:** stage each component from the form, then generate one project draft. Snapshots are independent; remove/restage after changes. Shared project/tester/period/mode must match. No cross-component averaging of unrelated accuracy or latency. Reports are manual/unverified drafts kept in page memory; download before leaving. No persistence, formal approval, DOCX/PDF export or full reference-DOCX layout reproduction.
- **Reference templates:** only the generic structure of authorized local reports is reused. No private project names, historical measured metrics or source report text is committed. Template ID/version and facts/template hashes are pinned; future template updates must be new versions.
- **Report agent:** reuses the harness model factory and a tool-free LangGraph agent. Explicit opt-in requirements → structured proposed fields/questions → human confirmation → real counters entered by the evaluator. Currently single-turn intake, not persistent multi-turn dialogue. A separate opt-in advisor sees allowlisted aggregate metrics only. Neither can invent measurements, alter counters or approve reports.
- **Metrics:** effect pass rate uses the full denominator. Errors/pending/not-run remain visible. TTFT applies only to observable content-bearing streaming responses; missing/inapplicable metrics are not zero or automatic PASS.

## Model management

Set `DEVPILOT_MODEL_CATALOG_DIR` to a private persistent Gateway directory. Administrators can add OpenAI-compatible or Anthropic models, update metadata, test a fixed non-business prompt with explicit consent, and assign roles. Keys are write-only; an omitted key retains the prior value. SQLite catalog payloads are Fernet-encrypted. Supply `DEVPILOT_MODEL_ENCRYPTION_KEY` through secret management, or protect the generated separate `catalog.key`. Back up the encrypted database and key securely; same-volume encryption is not a KMS, and Windows ACLs require operator care.

`general_agent` controls the default platform model; chat may override it. `report_advisor` enables report intake/advice, still requiring per-call consent. Dataset generation, evaluation judge and review assistant are **reserved bindings only**, not completed pipelines. Platform working models are separate from evaluated targets. No real provider is configured by this change and no customer/provider call is required for mock tests.

Operator models in `config.yaml` remain operator-owned. Preserve the `deerflow` package, compatibility keys/environment variables, upstream attribution and license; user-facing product branding is DevPilot.

## Next milestones

1. Versioned datasets, reference provenance/authorization, gold-label review, coverage slices, deduplication and leakage controls.
2. Confirmed RequestSpec integration with all evaluation adapters and reproducible runnable exports.
3. Human-review workbench, evidence-linked persistent reports and template revision/approval history.
4. Durable execution, quotas/cancellation, security policy across legacy execution paths and audit.
5. Explicitly authorized judge-model integration and reviewed knowledge promotion, not automatic training.

New features ship with backend tests and frontend browser/API regressions. Backend: Ruff format/check and pytest/toolkit tests. Host pnpm commands go through `scripts/pnpm.py`; frontend: `check`, unit tests and Playwright. See [backend](backend/AGENTS.md), [frontend](frontend/AGENTS.md), [upstream](README_upstream.md) and [LICENSE](LICENSE).
