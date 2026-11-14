# DevPilot

DevPilot 基于 DeerFlow，面向 AI 组件评测：整理授权 QA 数据、冻结请求/计划/标准、受控执行、人工复核，以及生成可追溯报告草稿。Agent 用于辅助建议；确定性服务负责权限、计数、预算和证据。

[当前能力与运行状态](docs/DevPilot_Delivery_Status.md) · [完整模块文档](docs/README.md) · [架构与开发指南](AGENTS.md) · [上游 DeerFlow](README_upstream.md)

源码已包含独立复核、评估修订、历史报告和授权外部 QA 候选；App 迁移头 `eval_0014` 尚未部署。本地加密输出在写入前持久化保留回执，运行期间持锁；[管理命令](docs/DevPilot_Local_QA_Retention_Commands.md)提供只读检查、单独同意的到期处置和原 ID 对账。正式批准、lost Worker 安全处置和新 QA 调度仍未完成。旧部署收据不证明当前本机服务运行。

## 快速开始

新环境推荐 Docker 开发方式。首次构建耗时取决于下载和机器性能；需要 Docker Desktop/Engine 与 Compose 插件、Git、make、Bash，以及生成配置用的 Python。Windows 建议在 WSL2 或已配置 make 的 Git Bash 中运行以下 shell 命令。已有环境请先核对 Compose project、私有配置和数据挂载，不重复初始化或另起同端口栈。

```sh
git clone https://github.com/helloboy829/DevPilot.git
cd DevPilot
docker compose version
make config              # 仅新环境执行；检测到已有配置会拒绝覆盖
```

按 `config.yaml` 的示例选择模型，并在本机私有环境配置对应凭据；不要把 key 写进仓库。模型配置不是 QA 目标授权，也不会自动启用评测执行。完成配置后：

```sh
make docker-init         # 准备所选沙箱模式所需镜像
make docker-start        # 开发 Compose，非现有生产环境升级命令
```

服务启动后访问 `http://127.0.0.1:2026`，按[配置示例](config.example.yaml)中的账号/认证设置完成本地登录。

| 想做什么                   | 入口与前提                                               |
| -------------------------- | -------------------------------------------------------- |
| 管理 QA/请求版本与冻结计划 | Projects & datasets；登录后操作自己拥有的项目            |
| 查看报告/复测草稿          | Reports / Retests；选择完整的冻结历史来源                |
| 对话与代码辅助             | Chats；先配置可用模型                                    |
| 接入外部组件或实际执行 QA  | 独立 operator 目标策略、权限、key 和显式同意；默认不启用 |

宿主开发另需 Python **3.12**、uv、Node/pnpm 与 nginx，准备完成后在根目录执行 `make install`、`make dev`。后端测试使用 `cd backend` 后 `uv sync --frozen --group dev`、`make test-blocking-io`、`make test`；`blockbuster` 已在 dev 锁内，须用项目 venv。安装细节见[安装指南](Install.md)和[贡献指南](CONTRIBUTING.md)。

English: Docker development is the recommended new-machine path. Configure private model credentials separately, then open the loopback entry at port 2026. Candidate code and report drafts do not imply deployment, QA execution authorization or formal approval.

候选升级前可先运行[合成 SQLite 升级与恢复演练](docs/DevPilot_Candidate_Upgrade_Recovery.md)，核验 WAL 在线备份、历史数据和独立还原；它不操作业务数据库，也不代替实际升级验收。

## Workspace appearance and navigation

The evaluation-first sidebar keeps stable Evaluation center and AI collaboration groups. Opening Chats or Custom assistants no longer inserts a new-chat row above the menu; create conversations inside Chats (or use the command palette). Assistant management does not open a conversation.

**Settings → Appearance → Workspace style** offers Precision console, Graphite minimal, Forest lab, Paper studio and Violet atelier. Each works with light, dark or system mode. Preferences are browser-local, not account settings or evaluation facts. Keyboard selection and mobile layouts are supported. [Scope and CI verification](docs/DevPilot_Workspace_Styles_CI.md).

## Available workspace slices

| Page                              | Implemented scope                                                                                                                                                            |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/workspace/evaluations`          | Default evaluation-first landing page with real component inventory and explicit remaining capabilities                                                                      |
| `/workspace/datasets`             | Owner-scoped projects, QA import/review/freeze, existing-component links, immutable inventory-only submissions, frozen QA plans and revisioned human result review           |
| `/workspace/component-tests`      | Existing component registration/effect/performance prototype, plus paste/import/edit/send cURL and inspect/copy bounded responses                                            |
| `/workspace/evaluation-schedules` | One-off/cron/timezone schedules, frozen bounded parameters, pause/resume/history; deterministic evaluation dispatch, not scheduled chat or push delivery                     |
| `/workspace/retests`              | Immutable same-benchmark comparisons of fully reviewed effectiveness runs; explicit paired evidence reads, no automatic execution or acceptance                              |
| `/workspace/reports`              | Verified immutable multi-component QA archives and revisions, plus separate manual/Agent drafts; pinned Chinese/English templates and frozen Markdown/Word draft downloads   |
| `/workspace/models`               | Connection profiles for OpenAI Chat, OpenAI Responses, Anthropic and Gemini; controlled parameters, encrypted write-only credentials, probes and default/report role routing |
| Chat                              | Existing harness conversation and per-conversation model selection, not the evaluation evidence ledger                                                                       |

The unified local entry point is `http://127.0.0.1:2026`. See [Install.md](Install.md), [AGENTS.md](AGENTS.md) and module guides for installation and full-stack `make dev`/Docker commands. Do not commit local configuration, credentials or customer materials.

## Assistants and request templates

Custom assistants are enabled by default for **all authenticated users**, not only administrators. Each account manages its own assistants and private profile; operators can still opt out with `agents_api.enabled: false`. The legacy global `USER.md` is retained but is not exposed through the private profile API. Model-backed conversations still require a configured model; enabling assistant management does not configure one.

The cURL debugger can export a **parameterized request template** (`request-template.v1`) with a structural SHA-256 fingerprint. Full URL/path/query, every header value and the body are replaced with explicit runtime references. Only method, origin and header names remain: review those as potentially sensitive metadata. This configuration-only download is not a persisted request version, executable test script, target authorization, debug-success certificate or evaluation evidence. See [delivery details](docs/DevPilot_Assistants_Request_Templates.md).

## Navigation and outbound baseline

Evaluation pages have one component-test navigation entry. Custom assistant management defaults to enabled for signed-in users; an operator opt-out hides its link rather than leaving a disabled placeholder; it is not the report assistant or evaluation executor. Debug, manual and scheduled component calls now share host/DNS/TLS enforcement. An empty operator allowlist also blocks manual runs. See [scope and remaining work](docs/DevPilot_导航与统一出站基线.md).

## Independent historical report/retest candidate

The working tree now adds **separate backend/API archives and explicit workspace panels** that explicitly select immutable independent assessment IDs, revisions and integrity hashes. Complete historical decisions are never silently replaced by current tasks or owner self-review. Reports pin independent bilingual layouts; same-benchmark comparisons keep every frozen sample and require equal criteria/budgets. All remain drafts, **not approved**. Candidate App head is `eval_0012`; the last verified local deployment is still `eval_0009`. In Reports and Retests, explicitly load an independent project, open a historical assessment revision and stage complete sources before confirming an archive. No revision is selected automatically. Unknown writes retain the same ID for GET-only reconciliation; historical Markdown/JSON downloads are explicit. Independent historical Word/PDF candidates are implemented separately; formal approval, real-user acceptance and a backed-up deployment remain unfinished; CI must be checked for the exact pushed SHA. Existing owner-review routes and exports are unchanged. See [the contract](docs/DevPilot_Independent_Report_Retest_Archives.md) and [current status](docs/DevPilot_Delivery_Status.md).

## Important boundaries

- **Skill safety:** with static scanning enabled, reported analysis/read failures reject skill writes or installs instead of treating incomplete analysis as a clean scan. Deterministic critical findings retain their normal rejection details; scanner-failure responses omit raw internal errors.

- **Project inventories:** link existing owner-owned components to frozen QA revision/hash and create multiple immutable inventory-only submission versions. Server snapshots exclude endpoints, credentials and gold. This is not a locked request/executable plan, test verdict or report evidence. See [inventory delivery](docs/DevPilot_项目组件与提测清单.md).

- **Request debugger:** parses one complete cURL without running a shell or reading files. Review method/URL/headers/body and explicitly authorize sending. Operator host approval, DNS pinning, TLS verification, no redirects/environment proxies, bounded timeout/response. Not a full Postman replacement: no multipart uploads, cookie jar, collections/environments, scripts or runnable test export yet. Debug data is not persisted or automatically promoted into an approved evaluation specification.
- **Off-peak evaluations:** require `scheduler.enabled: true` and approved destination hosts. Plans do not copy component credentials, reject changed target configuration, and recheck owner permissions at launch. Scheduled effect calls collect outputs for manual review, without implicit disclosure to an LLM judge. The existing scheduler provides leases/history/non-overlap, but component execution remains process-local rather than a durable worker queue. Pausing/deleting does not cancel an active run.
- **Project reports:** two separate workflows remain visible. Manual/Agent drafts use unverified page-memory inputs. Verified QA drafts instead persist immutable server-verified run summaries, pinned template snapshots and rendered Markdown, with explicit historical Word draft downloads. Neither is formal approval; do not mix manual facts with verified evidence or average unrelated accuracy/latency. Independent historical Word/PDF are separate candidate exports; full reference-DOCX layout reproduction and formal approval remain unfinished.
- **Reference templates:** only the generic structure of authorized local reports is reused. No private project names, historical measured metrics or source report text is committed. Template ID/version and facts/template hashes are pinned; future template updates must be new versions.
- **Report agent:** reuses the harness model factory and a tool-free LangGraph agent. Explicit opt-in requirements → structured proposed fields/questions → human confirmation → real counters entered by the evaluator. Bounded multi-turn intake (at most 10 rounds) is held in page memory, not persistent dialogue. A separate opt-in advisor sees allowlisted aggregate metrics only. Neither can invent measurements, alter counters or approve reports.
- **Metrics:** effect pass rate uses the full denominator. Errors/pending/not-run remain visible. TTFT applies only to observable content-bearing streaming responses; missing/inapplicable metrics are not zero or automatic PASS.

## Model management

Set `DEVPILOT_MODEL_CATALOG_DIR` to a private persistent Gateway directory. Administrators can add OpenAI Chat, OpenAI Responses, Anthropic Messages or Gemini Developer API model profiles, update metadata, test a fixed non-business prompt with explicit consent, and assign roles. Keys are write-only; an omitted key retains the prior value. SQLite catalog payloads are Fernet-encrypted. Supply `DEVPILOT_MODEL_ENCRYPTION_KEY` through secret management, or protect the generated separate `catalog.key`. Back up the encrypted database and key securely; same-volume encryption is not a KMS, and Windows ACLs require operator care.

`general_agent` controls the default platform model; chat may override it. `report_advisor` enables report intake/advice, still requiring per-call consent. Dataset generation, evaluation judge and review assistant are **reserved bindings only**, not completed pipelines. Platform working models are separate from evaluated targets. No real provider is configured by this change and no customer/provider call is required for mock tests.

Operator models in `config.yaml` remain operator-owned. Preserve the `deerflow` package, compatibility keys/environment variables, upstream attribution and license; user-facing product branding is DevPilot.

## Current delivery status

The report requirements assistant now supports a bounded, visible multi-turn conversation (10 rounds, 24000-character serialized context, page memory only). Every turn requires consent; confirming fields never alters measured metrics. Model profiles support custom provider labels/endpoints/model IDs, duplication without credentials, and explicit credential decisions when changing endpoints or protocols. This borrows connection-management patterns, not full CC Switch compatibility.

Use the [current delivery matrix](docs/DevPilot_Delivery_Status.md) for code, deployment, verification and remaining work; the [implementation log](docs/DevPilot_实现进度与下一步.md) retains historical slice evidence. Owner-scoped projects, frozen QA/request plans and criteria now connect to separately authorized bounded execution, encrypted outputs, revisioned human review, all-sample summaries, immutable report drafts and same-benchmark retests. Execution remains operator-disabled locally; the implemented chain is not an independently approved dataset or formal acceptance. Independent review/arbitration and historical archives now have undeployed candidates; formal approval, safe lost-worker operations, QA-chain scheduling admission, the complete external execution/evidence lifecycle, CV/streaming metrics and reviewed knowledge promotion remain incomplete.

## Next milestones

1. Close full-suite/environment regressions and run an independently observed, synthetic-only deployed workflow before requesting user acceptance.
2. Validate the implemented independent review/arbitration candidates and add versioned formal approval without changing frozen evidence, denominators or report history.
3. Define lost-worker operations that cannot resend unknown deliveries or reclaim a worker still capable of sending; independently admit QA-chain scheduling.
4. Unify remaining legacy adapters with the versioned execution boundary and finish plaintext-copy/crash-artifact governance and the separately authorized external evidence lifecycle.
5. Add explicitly authorized/calibrated CV, streaming-performance and judge-model workflows, dataset governance and reviewed knowledge promotion.

Default backend `make test` excludes real-model cases. Direct pytest runs also require `DEER_FLOW_RUN_LIVE_TESTS=1` before pytest starts; existing keys or a later test-module `.env` read are not authorization. CI always blocks live cases. Local Docker lifecycle integration is separately gated by `DEVPILOT_RUN_DOCKER_TESTS=1`, never probes the daemon during collection, and never implicitly pulls an image. Authorized live tests may incur API costs and create local artifacts; see [test safety](CONTRIBUTING.md#testing).

PostgreSQL URLs with an explicit libpq `sslmode` are adapted to asyncpg's `ssl` only for the derived async ORM URL; the selected TLS mode, original DSN and synchronous psycopg path are preserved. Conflicting or invalid TLS options are rejected rather than silently weakened. This compatibility fix is verified in isolation and is not yet in the last verified local deployment. See the [verification record](docs/DevPilot_CI修复与隔离开发环境.md).

Detector regression fixtures must also work when pytest temporary directories are inside the checkout: root-resolution tests simulate missing ancestor markers without touching real `.git` entries, and JSON report paths remain POSIX (repository-relative where applicable), including on Windows. These offline tooling tests do not require application-image rebuilds.

New features ship with backend tests and frontend browser/API regressions. Backend: Ruff format/check and pytest/toolkit tests. Host pnpm commands go through `scripts/pnpm.py`; frontend: `check`, unit tests and Playwright. See [backend](backend/AGENTS.md), [frontend](frontend/AGENTS.md), [upstream](README_upstream.md) and [LICENSE](LICENSE).

### Manual evaluation assistants

Every signed-in user can use **Custom assistants → Configure manually** to save an assistant without a model call, with bilingual requirements, dataset-design and result-review presets. Conversations still need a configured model. These are advisory configurations, not sandboxed test executors or official acceptance. Private assistants remain account-scoped; the Reports module remains the report-generation entry.

### Encrypted request-definition versions

Project/component request versions can now be saved append-only through the authenticated API. Complete URL, header values and body are encrypted under a separate operator key; public reads return only structural metadata. App migration `eval_0003` preserves earlier tables and ledgers. This is not an execution plan, a successful-debugging attestation, a credential-reference vault or report evidence. The component debugger now offers **Save request version** (current edited snapshot) and **View request versions** (metadata only, no import needed), with project/component selection and separate storage confirmation. Saving does not send a request. Saving requires explicit `DEVPILOT_REQUEST_ENCRYPTION_KEY` provisioning; existing local settings are not changed. See [scope and operations](docs/DevPilot_Request_Versions.md).

Request-version UI boundaries and failure recovery are documented in [the original workspace slice](docs/DevPilot_Request_Version_UI.md); later plan/Worker delivery is tracked in the [current matrix](docs/DevPilot_Delivery_Status.md).

### QA JSON wiring prerequisite

The pure QA JSON binding core now maps input into an existing request string field and extracts response text with explicit bounded pointers, without gold answers or network access. It underpins the frozen-plan API/UI and the separately admitted bounded QA Worker. Its [original slice contract](docs/DevPilot_QA_JSON_Binding.md) remains a historical boundary, not a claim that the Worker is still unimplemented.
