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

`blockbuster` 已属于 dev 依赖组并锁定版本；出现缺模块先核对解释器和安装组，不重复添加依赖、不改锁规避环境问题。PostgreSQL 专项另用 `uv sync --frozen --group dev --extra postgres` 和独占测试数据库。

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
- Docker 生命周期集成另需显式 `DEVPILOT_RUN_DOCKER_TESTS=1`，collection 不探测 daemon，不隐式拉镜像；测试仅操作唯一标识的隔离资源。
- 独立软件分发从六个锁定构建工具建立新环境，校验全部 37 源码成员/原始依赖 wheel/hash，再用新 no-system-site venv 完整离线安装。artifact-dependent 的 skip 不证明已安装验收。
- 临时 SQLite / 独占 PostgreSQL、合成身份/key/DNS/wire 与 socket 拒绝构成离线集成；不是部署、真实目标、Windows 或人工验收。数据库操作与线程工作须在重复取消后排空再 finish/close。
- 保留原失败证据，不用重跑、延长 timeout、减弱断言或执行启用隐藏失败。租约测试用受控时钟/事件，不能靠过短真实时钟窗口区分执行分支。
- Windows 保留 Selector 策略。真实子进程用 off-loop、绝对 cwd、有界退出并回收；不可删除真实 `.git`、跳过 Windows 断言或改变生产路径归一化来修测试。
- [候选 SQLite 升级/恢复回归](../docs/DevPilot_Candidate_Upgrade_Recovery.md)覆盖真实双 ledger、ALL 旧表/行/schema、WAL 在线备份与新路径还原。只接受测试创建的临时数据；恢复旧备份会丢失之后的新写，不把合成通过当业务库、PostgreSQL 原生恢复或 Windows 验收。

## 候选功能与模块合同

<details>
<summary>展开未部署候选模块与约束入口</summary>

App 候选迁移链为 `eval_0009 → eval_0010 → eval_0011 → eval_0012 → eval_0013 → eval_0014`，这是迁移编号，不是 Git HEAD 或批准状态。历史部署记录停在 `eval_0009`；本机是否运行另行观察。

- [独立逐条复核](../docs/DevPilot_Independent_Case_Review.md)：两名盲审、独立仲裁、窄授权与租约。
- [独立评估修订](../docs/DevPilot_Independent_Assessments.md)和[历史报告/复测档案](../docs/DevPilot_Independent_Report_Retest_Archives.md)：ALL 冻结分母、不可变历史、显式 revision/hash；不是正式批准。
- [授权配置导出](../docs/DevPilot_Authorized_QA_Exports.md)和[技术隔离接收](../docs/DevPilot_External_QA_Quarantine.md)：分离同意、原 ID GET-only 对账；技术声明不是平台证据。
- [共享 QA 核心](../docs/DevPilot_Shared_QA_JSON_Run_Core.md)与[本地命令](../docs/DevPilot_Local_QA_Command.md)：同一 runner，未知结果不重发、不续跑。
- [本地输出保护与保留](../docs/DevPilot_Local_QA_Protected_Output.md)及[管理命令](../docs/DevPilot_Local_QA_Retention_Commands.md)：独立 key、分别同意、输出前 durable receipt、运行期间持锁；处置须原 ID/两个 hash/单独同意，未知结果只原 disposal ID 对账，不生成 ID/修复/重试。expiry 不证明安全擦除。
- [执行占用诊断](../docs/DevPilot_Execution_Reservation_Diagnostics.md)：只读观察不是 Worker 死亡证明，不回收配额或重试。

完整逐模块条款见[原后端指南](../docs/Backend_Development_History.md)及[文档索引](../docs/README.md)。

</details>

## 详细架构与历史记录

[Backend 详细架构与历史](../docs/Backend_Development_History.md)保留原指南的 runtime、配置、Gateway、持久化迁移、工具、沙箱、MCP、IM、记忆和开发工作流全部章节。[当前交付状态](../docs/DevPilot_Delivery_Status.md)负责当前事实；历史命令和候选段落不能单独授予执行、数据外发、升级或批准。

English: Use Python 3.12 and the frozen uv environment. Keep App/Harness dependencies one-way, run TDD and offline gates, preserve all frozen populations and no-resend semantics. Full architecture notes and module contracts remain available separately.
