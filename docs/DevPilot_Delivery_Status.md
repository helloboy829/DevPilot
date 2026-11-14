# DevPilot 当前交付状态 / Current delivery status

更新：2026-11-15。本页只列当前能力、验证范围和缺口；逐轮原始记录见[交付历史](DevPilot_Delivery_History.md)。

## 现在能用什么

下表描述仓库代码；使用需要部署相应版本并完成账号、权限和 operator 配置。

| 能力                                                     | 代码状态                       | 使用边界                                                                     |
| -------------------------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------- |
| 项目/组件、QA 导入复核冻结、请求版本、冻结计划/v2 标准   | 已实现                         | 计划/hash 不授予执行权限；请求值与金标分离保护                               |
| 独立准入、有界 QA Worker、加密采集、人工复核、全样本汇总 | 已实现，执行默认关闭           | 未知交付不重发；采集成功/阈值达标不等于批准                                  |
| 历史报告/Word 草稿、同基准复测                           | 已实现                         | 草稿与比较不自动批准、不自动再执行                                           |
| 双盲复核/独立仲裁、评估修订、独立历史报告/复测 Word/PDF  | 候选代码已实现，未部署         | `eval_0010..0012`；旧 owner 路径保持独立                                     |
| 正式批准首切片（具名审批、职责分离、撤销/审计）          | 候选代码已实现，未部署         | `eval_0015`；仅 owner 记录，审批人另行具名；复核完整/阈值达标不等于批准       |
| 授权配置导出与外部技术元数据隔离接收                     | 候选代码已实现，未部署         | `eval_0013..0014`；不接纳敏感输出为可信证据                                  |
| 独立本地 QA 命令、共享核心、锁定软件分发、加密输出       | 候选代码已实现                 | 默认离线；真实发送与输出模式分别同意                                         |
| 未完成/损坏本地输出的保留治理                            | 加密运行时和显式管理命令已实现 | 输出前 durable receipt；原 IDs/两个 hash/单独处置同意；无安全擦除保证        |
| 候选 SQLite 升级与旧备份恢复演练                         | 合成回归已实现                 | 真实双 ledger、39 张历史表、WAL 在线备份与新路径还原；不是业务部署或无损回退 |
| 聊天、私有助手、请求调试、旧定时评测、模型管理           | 兼容入口保留                   | 模型调用需配置与授权；旧调度不代表新 QA 链调度完成                           |

入口与操作见[README](../README.md)、[文档导航](README.md)和[工作台范围](DevPilot_Evaluation_Workspace.md)。

## 代码、迁移与本机运行

| 项目               | 当前事实                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------- |
| Git 源码           | `main`；精确工作区提交用 `git rev-parse HEAD` 查询，不用迁移号代替                        |
| App 候选迁移头     | `eval_0015`；本轮合成恢复矩阵尚无新 SHA CI 收据                                           |
| 最后留存的部署收据 | `0fd689da83a4ac7646250447fb6d044599a823c5` / `eval_0009`，属于历史验证                    |
| 本机 Docker 观察   | 2026-11-15 观察：先前四个 `devpilot-local` 业务容器及其 `criteria-0fd689da83a4` 镜像已不在本机（外部清理，原因未核实）；不做业务恢复或镜像重建推断 |
| 本轮操作           | 创建两个隔离 Python 3.12 容器（专项测试与 venv 恢复，仅挂载公开源码、无业务卷、无发布端口），运行专项/迁移/完整离线套件，并恢复 `backend/.venv`（Linux 3.12.16，gitignored）；两个容器均已按完整 ID 停止并删除。不部署、不复制或迁移业务 DB、不生成生产 key、不调用真实模型/目标 |

只有重新启动并验真相应版本才能声称当前本机可用。历史健康和账号/数据保存记录见[本地升级记录](DevPilot_Local_Recovery_and_Upgrade.md)。

## 最近验证

- 本地完整后端离线套件（`git archive HEAD` 副本，对应 `abbdde7` 工作树）：**13,495 passed / 2 failed / 77 skipped / 11 deselected / 40 warnings**（1923.14s）。两个失败均属本轮临时容器环境：`config-upgrade.sh` 因容器未装 `uv` 失败（安装后单独复跑 **1 passed**）；`test_local_qa_cli` 隔离源码子进程报 `JSONRunStopped`，该测试未被本轮修改，且在同一 SHA 的 CI Unit 中通过，历史迁移副本的首次全量（tar 复制缺少 `scripts`）另有 7 个 collection 错误、已作废。以上不记为当前源码失败，也不替代精确 SHA CI。
- **精确 SHA CI（批准审计与验收清单，2026-11-15）**：`abbdde738551c8f454265523278edfa08c1c3ebf` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43623795574)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43623795600)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43623795652)、[Replay E2E](https://github.com/helloboy829/DevPilot/actions/runs/43623795521)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43623795524) 共 **5 workflows 全部成功**；该 SHA 包含批准只读审计列表、验收清单补充与诊断收据。
- **精确 SHA CI（诊断聚合，2026-11-15）**：`052a62474f919b0bf7404f545d81c36f74d84246` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43620477366)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43620477377)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43620477429)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43620477352) 共 **4 workflows 全部成功**；Unit 的 `make test` 覆盖新增 `safety.states` 聚合与既有执行/安全回归。
- 执行诊断聚合安全状态（本地离线，Linux venv）：`tests/test_execution_diagnostics.py` **14 passed**（30.00s）；`test_execution_operations_router` + `test_execution_safety` 联合 **40 passed**（61.80s）；锁定 Ruff check/format 通过。`safety.states` 在同一聚合 SELECT 中按固定状态码计数，不返回任何 per-run ID，也不授权释放/回收/重试/调度。
- **精确 SHA CI（执行安全集成回归与验收包，2026-11-15）**：`fa54cbbb522247c6f1ba0a6eb34245623a93f687` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43617913181)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43617913189)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43617913176)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43617913214) 共 **4 workflows 全部成功**；该 SHA 覆盖批准专属迁移回归、候选验收包与执行安全真实生命周期测试。中间 `7ab6478` 的 Unit 被该新推送取代而 **cancelled**（其余 3 项成功），不能记为通过。
- **精确 SHA CI（执行安全合同，2026-11-15）**：`ce6ca15f97c410252100dea4c00a8949ed826a40` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43615345199)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43615345236)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43615345167)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43615345169) 共 **4 workflows 全部成功**；Unit 的 `make test` 覆盖新分类模块与既有执行/调度回归。该 SHA 只增加纯函数、测试与文档。
- 执行安全合同（本地离线，恢复后的 Linux venv）：`tests/test_execution_safety.py` **32 passed**（20.80s，含纯投影矩阵与真实 admit/claim/expire 集成）；关联执行/调度回归 `test_execution_diagnostics`、`test_qa_execution`、`test_qa_execution_lifecycle`、`test_evaluation_schedules` 联合 **66 passed**（54.49s）；批准/迁移/执行安全/恢复矩阵组合 **60 passed**（137.47s）；锁定 Ruff 0.15.12 check/format 通过。只新增纯同步分类与边界回归，没有 API/迁移/UI/后台清理器。
- **精确 SHA CI（正式批准，2026-11-15）**：`18101f9c08f8fbb32d8fbfdde72200aefef26738` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43612739708)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43612739812)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43612739625)、[Replay E2E](https://github.com/helloboy829/DevPilot/actions/runs/43612739710)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43612739705) 共 **5 workflows 全部成功**；Unit 的 `make test` 覆盖新批准模块与 `eval_0009 → eval_0015` 迁移矩阵。该 SHA 只增加批准切片与测试/文档；旧 SHA 的结果不适用于新提交。
- 正式批准首切片（`eval_0015`，本地离线，隔离 Python 3.12 容器，锁文件 dev 组）：专项 `tests/test_qa_approvals.py` + `tests/test_qa_approvals_router.py` + `tests/test_formal_approval_migrations.py` 联合 **26 passed**（53.00s），覆盖批准/撤销、职责分离、审计列表（只用有序元数据）、同 ID/并发/篡改、当前复核重开后仍可基于固定历史评估执行撤销，以及 API 级撤销两 revision 与审计顺序；专属迁移回归验证 downgrade 只移除批准两表、历史行不变、upgrade 重建空表、head parity 与约束/外键；迁移矩阵（候选恢复 + 五组迁移专项）**13 passed / 5 skipped**（146.36s，skip 是原 PostgreSQL 独占服务器门禁），候选恢复链现为 39 → 44 → 45 → 47 → 49 → 51 → **53** 张表并固定新增 14 张表；更新头断言的九个既有文件 **285 passed**（286.45s）；领域测试 **15 / 58 passed**。Blocking IO **72 passed**；锁定 Ruff check/format 通过。
- **精确 SHA CI（2026-11-14）**：`6c67ab58819d5871603a7f21547bec184db55e16` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43600357480)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43600357401)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43600357383)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43600357353) 共 **4 workflows / 全部 jobs 成功**；Unit 含默认安装 collection、`make test`（完整后端离线套件，覆盖候选 SQLite 恢复演练）、软件分发与实际安装导出。该提交只修改三个测试的环境隔离（清除容器 Redis 环境变量对默认存储/uv extras 推断的干扰）与 `overlay_models` 的 `models: None` 处理；没有运行时行为、迁移、依赖或执行开关变更。这是该 SHA 的唯一 CI 收据，不适用于 `eval_0015` 候选。
- CI 日志修复的独立 Python 3.12 冻结 dev 环境：修改前 **13,441 passed / 77 skipped / 11 deselected / 40 warnings，1032.35s**；修改后原 `make test` **同样 13,441 passed / 77 skipped / 11 deselected / 40 warnings，951.44s**，两组领域测试 **15 / 58 passed**。六文件专项 **384 passed**、Blocking IO **72 passed**、完整 Ruff **1,282 files** 通过。相同入口 collection 前后均 **13,524 items**，每个测试函数的用例数一致；11 个超长编号消除，最长 **655,440 → 615 字符**。这是本地离线结果，不代替新提交 CI 或 Windows 验收。
- 候选恢复回归的最终完整离线套件：**13,441 passed / 77 skipped / 11 deselected / 40 warnings**，934.37s；修改前基线为 13,433 passed（906.24s）。本地默认 dev 安装未配置 PostgreSQL extra/独占服务器，相关专项等按原门禁跳过。远端数据库服务门禁单独核验。
- [最终 SQLite 恢复矩阵](DevPilot_Candidate_Upgrade_Recovery.md)专项 **8 passed**（59.15s），验证 39 → 44 → 45 → 47 → 49 → 51 张表及 ALL 历史行/schema、WAL/账号/报告/复测/Word。与五组已有迁移联合 **13 passed / 5 skipped**；Blocking IO **72 passed / 2 warnings**，领域 **15 / 58 passed**，最终完整后端 Ruff check/format **1,282 files** 通过。专项和全量重叠，不相加；skip 不是通过。
- 前一 `7ba1484` 的管理命令/原 retention API 联合 **80 passed**，带实际软件的联合 **241 passed**，六工具构建→12依赖完整离线安装与三条实际管理命令已验证；本轮未改软件源码/依赖或重建分发。档案 SHA256 `27aeb3cdb8df596b63fd2b0d8569e824ea5a13d11c4f36a315b7d1eb48af697f` 只属于前轮构建，当前 allowlist 为 **37** 个第一方源码成员。原始失败与逐轮门禁见交付历史。

专项、联合和全量有重叠，不相加；skip 不是通过。前端/浏览器历史通过数没有在本轮本地重跑，Linux 验证不代替 Windows 验收。

基线 **`7ba1484b098d7a29a0a737400ff321d0ccbc8001`** 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43558000440)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43558000459)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43558000384)和 [Unit](https://github.com/helloboy829/DevPilot/actions/runs/43558000487)共 **4 workflows / 8 jobs 全成功**，含默认安装全量 collection、带 PostgreSQL 的完整后端、软件分发与实际安装导出。本轮合成恢复回归的 SHA/CI 另行核验，不能沿用基线结果。更早的 collection 超时与有界诊断保留在历史，不宣称已确证根因或改变原门禁。

恢复回归提交 **cd26960455fd1e74e4b698d1d81c5bc6c840ba11** 的 8 个 jobs 中 7 个成功；[backend-unit-tests](https://github.com/helloboy829/DevPilot/actions/runs/43563204085/job/132351247651) 虽打印 **13,499 passed / 19 skipped / 11 deselected**，job 仍超过原 **15 分钟**限制而取消，不能记为 CI 通过。原日志 3,994,360 bytes，11 个超长测试行合计 1,968,573 字符，最长 655,484 字符。修复只为这些边界参数设置简短固定名称；输入、断言、测试数量和超时均保留。新 SHA 的 CI 必须另行核验，日志问题本身不证明已消除所有超时原因。

原始红灯、修复原因和逐轮收据见[交付历史](DevPilot_Delivery_History.md)。push、本地通过、CI 成功和部署是独立事实。

## 下一步优先级

| 优先级 | 工作                                                   | 退出条件                                                                         |
| ------ | ------------------------------------------------------ | -------------------------------------------------------------------------------- |
| P0     | 当前源码 CI、环境与候选升级验收闭环                    | 精确 SHA 门禁、当前镜像源码核对、数据/配置保护、隔离迁移及回退演练；部署另行执行；清单见[候选验收包](DevPilot_Acceptance_Package.md) |
| P1     | 本地明文副本与更广泛崩溃产物治理、Windows 验收         | 分别绑定原身份/用途/保留同意，旧目录不补造回执；新平台实际安装/锁/处置验证       |
| P1     | 独立版本化正式批准                                     | 固定历史来源、职责分离、审批修订/撤销及用户验收；不能把 case PASS 当批准；首切片候选已实现，审批人专属身份/多人签核/通知仍未完成 |
| P1     | Lost Worker 安全处置与新 QA 调度准入                   | 证明旧 Worker 不能发送后再讨论释放；未知请求绝不重发；不能沿用旧调度绕准入；只读分类合同与阻塞回归已实现，释放/准入仍未完成 |
| P2     | 敏感外部证据治理、CV/流式指标/模型裁判、整改与知识闭环 | 各自授权、隔离、证据/计量与人工审查；缺失指标不填零、不判 PASS                   |

开发环境恢复不必等所有 P1/P2 功能完成；正式质量验收依赖独立批准及相应业务能力。具体交付以模块退出条件为准，项目整体尚未完成。

English: Source capabilities, candidate migrations, exact-commit verification and observed runtime are tracked separately. Business containers were observed as absent on 2026-11-15 (external cleanup, cause unverified); no deployment or real calls were performed. Encrypted runtime retention receipts and explicit management commands are implemented; the formal-approval first slice exists as an undeployed candidate, while approver-side identity, multi-level sign-off, plaintext-copy/crash-artifact governance, Windows acceptance and safe lost-worker/scheduling operations remain open.
