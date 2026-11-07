# AGENTS.md

## Encrypted request definitions (2026-11-08)

App migration head is `eval_0003`, after unchanged `eval_0001/eval_0002`. `devpilot.request_versions.FrozenRequest` is deep-immutable; protected serialization contains secrets and is never a public DTO. `app.evaluation.request_version_repository` appends owner-scoped complete-request ciphertext under explicit `DEVPILOT_REQUEST_ENCRYPTION_KEY`; no key fallback/generation. Public metadata queries exclude ciphertext; write requires write+review, human confirmation and rejects internal Agents. Crypto is thread-offloaded; open is internal/audited, not an executor. No plaintext/open/execute/update/delete HTTP routes or frontend save button. `request_definition_only` is not approval, evidence or a credential-reference vault. See [scope](docs/DevPilot_Request_Versions.md).

## Stable navigation / workspace styles (2026-11-08)

The sidebar brand/product groups never insert route-dependent creation rows. New-chat creation belongs to conversation content; assistant management is not a new conversation. WorkspaceStyleProvider applies an allowlisted browser-only preference on workspace routes, independently of next-themes light/dark. Presets must keep semantic statuses unchanged and pass contrast/keyboard/mobile regressions. Before pushing, run the **entire** frontend Prettier check, including Markdown guides; lint/typecheck alone does not cover CI formatting. See [delivery](docs/DevPilot_Workspace_Styles_CI.md).

## Authenticated assistants / request-template slice (2026-11-07)

`AgentsApiConfig.enabled` now defaults true. All authenticated accounts may manage their own assistants; keep auth middleware, owner scoping and explicit operator opt-out. Private profile routes use `users/{user_id}/USER.md`, with threaded/atomic I/O and no legacy global fallback. Operator-provisioned legacy shared agents remain a compatibility read fallback, not other users' personal agents.

`devpilot.request_templates` is pure configuration-only wiring: all request values become explicit references; method/origin/header names remain. `/api/component-tests/debug/template` and the debugger download do not send, persist, certify debugging, resolve secrets, or create execution plans/evidence. Fingerprint is structural integrity, not a signature or secret/value binding. Never send `resolve()` output without fresh policy/consent. See [delivery](docs/DevPilot_Assistants_Request_Templates.md).


## Navigation / shared outbound slice (2026-11-07)

Evaluation component calls share app.evaluation.http.PinnedEvaluationTransport across debugger/manual/scheduled paths. Manual admission requires runs:create and checks policy before creating a run. Custom-assistant navigation is hidden when disabled; do not bypass its operator gate to remove grey UI. Full RequestSpec execution/credential references remain pending. See [scope](docs/DevPilot_导航与统一出站基线.md).


## Project component/submission inventory (2026-11-07)

`app.evaluation.registry` and `registry_repository` link owner-owned legacy components to projects and frozen QA versions. The inventory slice introduced `eval_0002`; do not edit deployed revisions (current head `eval_0003`). SQL selects only safe inventory columns, never legacy endpoints/tokens/criteria. Server-built immutable snapshots have `scope=inventory_only`: NOT RequestSpec locks, executable plans, acceptance or report evidence. Submission creation requires write+review and explicit confirmation; rejects internal Agent callers. See [inventory slice](docs/DevPilot_项目组件与提测清单.md).

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

## Service Topology

A single `make dev` / Docker stack runs four cooperating services:

| Service         | Port   | Role                                                                 |
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
