# Backend Agent 开发指南

## 导航

- [架构概览](#架构概览)
- [开发环境](#开发环境)
- [测试指南](#测试指南)
- [候选功能与模块合同](#候选功能与模块合同)
- [详细架构与历史记录](../docs/Backend_Development_History.md)

本文件负责后端开发入口；仓库通用约定见[根指南](../AGENTS.md)。原指南的详细工程约束完整保留在历史/架构文档，相关约束仍适用；不要将旧通过数或部署收据当作当前状态。

## 架构概览

| 层            | 目录 / import                                          | 职责                                                      |
| ------------- | ------------------------------------------------------ | --------------------------------------------------------- |
| App           | `app/` / `app.*`                                       | Gateway、业务路由、授权、评测存储、IM                     |
| Harness       | `packages/harness/` / `deerflow.*`                     | Agent runtime、模型工厂、工具、中间件、沙箱、记忆和持久化 |
| Extension API | `packages/extension-api/` / `deerflow_extension_api.*` | 第三方扩展的公开契约                                      |
| DevPilot      | `../devpilot/src/devpilot/`                            | 共享评测核心及本地 QA 命令；已有 HTTPX 等显式依赖         |

App 可以调用 Harness 与 DevPilot，Harness 不导入 App。Gateway 的 `RunManager`、`run_agent()` 和 `StreamBridge` 承载统一 Agent 生命周期；通用定时任务复用该生命周期，不能借它绕过独立 QA 准入。QA Worker 与本地执行共用版本化 request/response/attempt/run/transport 核心，由各自适配器保留授权和耐久边界。

所有完成初始化的已登录人类用户都具有项目 read/write/review 基础能力，普通用户与管理员相同，不设审核人角色。Gateway 的权限解析与路由检查均保留这一基础能力，即使旧角色配置遗漏或拒绝这些名称；项目 owner、任务精确指派与运行内独立性仍在业务仓库验证。内部 Agent 不获得人类成员资格；模型/运维/外发边界独立保留。后续审批人本人操作同样面向所有用户。详见[当前接续](../docs/DevPilot_Equal_Review_and_Linux_Acceptance.md)。

中间件处理线程隔离、沙箱、工具和上下文；调整顺序或扩展边界前读[完整中间件链](../docs/Backend_Development_History.md#middleware-chain)及[扩展系统](../docs/Backend_Development_History.md#python-extension-system-runtime-slice)。第三方代码入口 `plugins` 属 operator 控制，不能进入 API 可写配置。

配置推荐放在仓库根目录。主配置解析顺序为显式 `config_path` → `DEER_FLOW_CONFIG_PATH` → 当前目录 → 父目录；扩展配置使用对应的 `DEER_FLOW_EXTENSIONS_CONFIG_PATH`。显式配置路径缺失要报错，不能偷偷回退。基础设施字段按 `STARTUP_ONLY_FIELDS` 重启生效；不要把热重载视为基础设施升级。

## 开发环境

后端使用 **Python 3.12 + uv**；不要用宿主 Python 3.9 或镜像系统解释器代替项目 venv。

```sh
cd backend
uv sync --frozen --group dev
uv run python --version
uv run python -c "import blockbuster; from importlib.metadata import version; print(version('blockbuster'))"
```

`blockbuster` 已属于 dev 依赖组并锁定版本；出现缺模块先核对解释器和安装组，不重复添加依赖、不改锁规避环境问题。PostgreSQL 是默认持久化后端；宿主环境须提供 `DATABASE_URL`。完整开发/测试依赖使用 `uv sync --frozen --group dev --extra postgres`，真实迁移/集成回归只允许连接独占测试数据库；不配置该库时跳过可选 PostgreSQL 实连专项。

Docker 开发从根目录用 `make docker-start`，参见[快速开始](../README.md#快速开始)。`devpilot` 是 sibling editable 依赖：builder 执行 uv sync 前须有 `/app/devpilot`，runtime 保留该目录，开发 Compose 的 sibling mount 必须一致。复制公开源码时不要把镜像已有 `.venv` 用 bind mount 隐藏，也不要复制私有配置/数据库。

## 测试指南

**后端 TDD 必须执行：先失败用例，再实现，再复验。完整离线套件在修改前后运行；有失败不能宣称模块完成。** 测试放在 `tests/test_<feature>.py`，领域用例保留原位置。用当前锁文件环境，不能以旧镜像中的成功代替当前源码验收。

```sh
cd backend
uv run pytest --collect-only -q
PYTHONPATH=. uv run pytest tests/test_<feature>.py -q --tb=short
make lint                 # Ruff check 和 format --check
make test-blocking-io
make test                 # 领域 unittest + 排除 live 的后端 pytest
```

`PYTHONPATH=.` 是 POSIX shell 写法；PowerShell 用 `$env:PYTHONPATH='.'` 后调用 uv。可直接在隔离 Linux Docker 环境执行 POSIX 命令。

- **Blocking-IO runtime gate**：使用项目 venv 的 blockbuster/pytest；异步 I/O 必须 off-loop，并覆盖取消和异常。静态扫描报错不代表干净扫描。
- 默认/CI 禁止真实模型/API 测试。`make test-live` 仅用于已授权的真实 API 验证；`live` 仅在 pytest 启动前显式 `DEER_FLOW_RUN_LIVE_TESTS=1` 且非 CI 才可运行。配置里已有 key 或 `.env` 读取不是授权。
- `/api/model-management/models/discover` 必须保持管理员权限和逐次 `consent: true`；仅由显式 UI 操作触发一次有界模型目录 GET，不调用推理。凭据不能进 URL、日志、错误详情或响应；禁用重定向/环境代理并限制超时、响应体和返回条数。后台只在档案 ID、协议、endpoint 均匹配时复用密钥；自定义模型 ID 永远可手动配置。相关测试只用 MockTransport。
- 无密钥 OpenAI-compatible/Responses 档案使用 SDK 的 `workload-identity-auth` sentinel，防止环境 `OPENAI_API_KEY` 回退并省略 Authorization 头；Anthropic/Gemini 档案必须有显式 key，不能将占位文本当凭据发送。用无网络 SDK 构造回归验证。
- Docker 生命周期集成另需显式 `DEVPILOT_RUN_DOCKER_TESTS=1`，collection 不探测 daemon，不隐式拉镜像；测试仅操作唯一标识的隔离资源。
- 独立软件分发从六个锁定构建工具建立新环境，校验全部 37 源码成员/原始依赖 wheel/hash，再用新 no-system-site venv 完整离线安装。artifact-dependent 的 skip 不证明已安装验收。
- 临时 SQLite / 独占 PostgreSQL、合成身份/key/DNS/wire 与 socket 拒绝构成离线集成；不是部署、真实目标、Windows 或人工验收。数据库操作与线程工作须在重复取消后排空再 finish/close。
- 保留原失败证据，不用重跑、延长 timeout、减弱断言或执行启用隐藏失败。租约测试用受控时钟/事件，不能靠过短真实时钟窗口区分执行分支。
- Windows 保留 Selector 策略。真实子进程用 off-loop、绝对 cwd、有界退出并回收；不可删除真实 `.git`、跳过 Windows 断言或改变生产路径归一化来修测试。
- [候选 SQLite 升级/恢复回归](../docs/DevPilot_Candidate_Upgrade_Recovery.md)覆盖真实双 ledger、ALL 旧表/行/schema、WAL 在线备份与新路径还原。只接受测试创建的临时数据；恢复旧备份会丢失之后的新写，不把合成通过当业务库、PostgreSQL 原生恢复或 Windows 验收。
- 修改跨方言表/候选迁移时，使用 `--extra postgres` 与独占 PostgreSQL 运行 schema parity、历史保留和约束回归；未配置数据库的 skip 不能替代验证。主键已覆盖的唯一性不要再声明同列 UNIQUE，保留真实数据库的唯一性与边界测试，不能忽略反射差异来获得通过。

## 候选功能与模块合同

<details>
<summary>展开模块合同与剩余验收边界</summary>

App 迁移链为 `eval_0009 → eval_0010 → eval_0011 → eval_0012 → eval_0013 → eval_0014 → eval_0015 → eval_0016`，这是迁移编号，不是 Git HEAD 或批准状态。2026-11-17 当前 `deer-flow` 栈已重建为 `b9a2f8d` / `eval_0016`，源码指纹、数据/配置保留和健康检查通过；完整业务运行验收仍未完成。后续运行状态须重新观察，旧 `eval_0009` 收据仅属于历史。

- [独立逐条复核](../docs/DevPilot_Independent_Case_Review.md)：两名盲审、独立仲裁、窄授权与租约。
- [独立评估修订](../docs/DevPilot_Independent_Assessments.md)和[历史报告/复测档案](../docs/DevPilot_Independent_Report_Retest_Archives.md)：ALL 冻结分母、不可变历史、显式 revision/hash；不是正式批准。
- [授权配置导出](../docs/DevPilot_Authorized_QA_Exports.md)和[技术隔离接收](../docs/DevPilot_External_QA_Quarantine.md)：分离同意、原 ID GET-only 对账；技术声明不是平台证据。
- [共享 QA 核心](../docs/DevPilot_Shared_QA_JSON_Run_Core.md)与[本地命令](../docs/DevPilot_Local_QA_Command.md)：同一 runner，未知结果不重发、不续跑。
- [本地输出保护与保留](../docs/DevPilot_Local_QA_Protected_Output.md)及[管理命令](../docs/DevPilot_Local_QA_Retention_Commands.md)：独立 key、分别同意、输出前 durable receipt、运行期间持锁；处置须原 ID/两个 hash/单独同意，未知结果只原 disposal ID 对账，不生成 ID/修复/重试。expiry 不证明安全擦除。
- [执行占用诊断](../docs/DevPilot_Execution_Reservation_Diagnostics.md)：只读观察不是 Worker 死亡证明，不回收配额或重试。
- [正式批准首切片](../docs/DevPilot_Formal_Approval.md)：`eval_0015` append-only 批准/撤销修订、`eval_0016` 咨询性签核政策存储，固定 assessment hash 与 ALL 分母；独立复核完整、冻结阈值（若定义）达标、审批人非 owner 且非该 run 任一盲审/仲裁，且审批人账号须已存在并完成初始化，撤销附理由与审计。另有只读预检（eligible/blockers/分离，不写回执）、项目级最新 revision 索引、有序审计列表、运行级与项目级链完整性校验、签署进度聚合（`policy=not_defined`；可选拟议人数或已存咨询政策仅返回 advisory requirement，不强制；政策存储 append-only、仅 owner 显式；仅元数据），以及数据集页内嵌的批准面板（显式加载/预检/创建/撤销/链完整性/签署进度，未知写只按原 ID 对账）。case PASS/阈值达标不生成批准；无审批人专属登录、多人签核、通知或导出权限。
- [执行安全合同](../docs/DevPilot_Execution_Safety_Contract.md)：`classify_held_reservation` 只读固定投影，恒不授权 release/reclaim/requeue/retry/resend/dispatch；deadline/终态不是 Worker 死亡证明；未知/不一致行失败关闭。调度器与正式批准不得导入或触发执行仓库；运维路由保持聚合 GET。
- [QA 调度准入诊断](../docs/DevPilot_Scheduling_Admission.md)：管理员只读固定拒绝投影，legacy scheduler 仅覆盖 component tests；恒不授权调度/释放/重试，不读 DB/配置/证据。

完整逐模块条款见[原后端指南](../docs/Backend_Development_History.md)及[文档索引](../docs/README.md)。

</details>

## 详细架构与历史记录

[Backend 详细架构与历史](../docs/Backend_Development_History.md)保留原指南的 runtime、配置、Gateway、持久化迁移、工具、沙箱、MCP、IM、记忆和开发工作流全部章节。[当前交付状态](../docs/DevPilot_Delivery_Status.md)负责当前事实；历史命令和候选段落不能单独授予执行、数据外发、升级或批准。

### PERF-07 Worker candidate constraints

- Keep active transport tasks <= min(concurrency, max_in_flight); consume the frozen manifest in phase order and never hold a DB transaction across transport.
- For each ordinal persist claim -> ACK -> send_started before synthetic transport. Unknown after the fence is never resent.
- Serialize observation/evidence writes in the coordinator. On failure stop admissions, drain fenced peers, then interrupt unresolved fences so a single unknown cannot invalidate healthy in-flight responses.
- Reserve request bytes plus max response bytes across concurrent tasks; release only the unused response reservation after observation. Synthetic timings are not target metrics. This slice is not production load testing.

English: Use Python 3.12 and the frozen uv environment. Keep App/Harness dependencies one-way, run TDD and offline gates, preserve all frozen populations and no-resend semantics. Full architecture notes and module contracts remain available separately.
