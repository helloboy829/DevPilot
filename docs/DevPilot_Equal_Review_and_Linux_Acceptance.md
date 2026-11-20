# 全民审核与 Linux 验收接续

更新：2026-11-18。按用户明确要求，所有完成账号初始化的已登录用户都具备项目操作和审核能力，无需单独开通审核人角色或授予审核权限。产品业务角色按评测人员统一，管理员保留平台管理能力；盲审、仲裁和签核仅是具体任务职责。Linux／容器是主要运行与验收环境，Windows 兼容性单独记录。

## 用户与数据边界

- 普通用户（产品含义为评测人员）和管理员具有相同的项目读写、复核资格；数据库/API 的 `user` 名称暂为兼容保留。旧 `evaluation_projects:read/write/review` 名称保留接口兼容，但不再由角色配置决定人类用户是否具备这些能力。
- 所有人都能创建自己的项目并参与分配给自己的任务。其他人的项目、金标和证据仍受项目归属或精确任务指派限制。
- 盲审、仲裁、审批是某项任务中的分工，不是账号等级。保留双盲、独立仲裁和具体运行内的职责分离，不允许 owner 将自审伪装成独立批准。
- 匿名、未完成账号初始化者和内部 Agent 不因这项规则获得人类审核资格。
- 模型配置、平台运维和数据外发仍遵循各自原有边界；项目审核资格不自动授权发送请求、打开敏感输出、外发数据或生成批准。
- 本规则位于 App Gateway；不修改 Harness 授权框架，不新增用户角色、数据库字段或迁移。

## 实施顺序

| 阶段 | 交付内容                                                    | 完成依据                                                                                 |
| ---- | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 1    | 统一成员审核能力；恢复 Linux 开发运行环境；当前版本合成验收 | 先失败回归；真实登录/JWT/CSRF 多账号测试；全量离线门禁；当前源码构建、启动与业务流程证据 |
| 2    | 审批人本人登录操作及通知、签核生效/撤销/失效                | 人人可担任审批人；每次决定绑定当前登录人、固定来源与审计；具体运行保留职责分离           |
| 3    | Lost Worker 安全处置及新 QA 调度                            | 证明旧 Worker 已失去发送能力；未知交付仅原 ID 对账；冻结计划独立准入                     |
| 4    | 高级指标、模型裁判、敏感外部证据和整改知识闭环              | 平台执行/证据/报告接入与独立授权；缺失证据不能 PASS                                      |

阶段 1 的源码规则和 Linux 合成验收已完成并提交；业务数据部署与真实用户验收仍未完成。阶段 2 的本人签核已有 `eval_0017` 未部署候选。候选完整后端已在 Linux 隔离环境复验：测试进程退出码为 0，收集 **13,695/13,706 项，11 项按标记排除**，pytest `lastfailed` 为空。完整终端汇总在会话切换后未能取回，因此不推算通过总数；首轮环境失败及配置修正后的定向复验另有记录。本人签核/PostgreSQL 迁移专项 **3 passed**、真实认证浏览器合成流程 **3 passed**、跨 Pod 去重专项 **3 passed**。精确 SHA CI、业务数据部署和真实用户验收仍未完成。后续阶段不因成员权限调整而视为完成；真实模型/目标调用需单独授权，合成测试不代替真实用户验收。

当前接续（2026-11-18）：`c7db5e2dba831ae436576f7df8ff2ce8ce4dd28f` 已推送至 `main`，仍是未部署候选。本人签核、路由、认证与迁移在 Linux 合成环境 **43 passed / 0 skipped**；本轮修复测试初始化失败时临时 PostgreSQL 库未清理的问题，修复后同组回归通过且临时库计数为 0。该 SHA 的 Unit、Lint、Frontend、Blocking IO 通过；Replay E2E 因 Chromium 安装失败而未执行浏览器步骤。真实业务库部署和用户验收仍未完成。

## 验证记录

- 2026-11-17 按用户要求将当前 `deer-flow` 栈从源码指纹匹配的 `6cc954e` 重建至 `b9a2f8d` / `eval_0016`；目标 SHA 六项 CI 实际成功。原配置/环境/挂载保持，在线备份后主库 58 张表与检索库 6 张表的数据摘要、schema 和双 ledger 均一致；后端 686 项、前端 559 项所选源码/配置指纹一致，前端生产构建和 HTTP 健康/登录/匿名授权边界通过。容器内成员辅助逻辑验证通过；未执行真实账号登录或完整多账号业务链，因此阶段 1 的完整业务验收仍开放。详见[本地升级记录](DevPilot_Local_Recovery_and_Upgrade.md)。以下为此前各轮原始验证记录。

- 基线源码为 `6cc954e9e1d33bc9ab1142c1948487c05eabca6f`；该 SHA 的四项实际 CI 工作流、九个 job 已全部成功。
- 新成员规则的初始回归 **7 failed / 3 passed**：空角色授权、显式 deny、授权 provider 不可用及已指派任务领取均确认旧行为不符合用户要求。保留失败日志后修复，不删除原始失败。
- Linux 测试使用 Git 跟踪源码、已冻结 Python 3.12 依赖和独占 PostgreSQL 17，数据库仅合成数据、无发布端口。旧缓存重新同步时尝试下载构建依赖的失败发生在测试开始前，单独保留；使用既有冻结依赖运行时禁止自动同步。
- 修改前完整 Linux 基线：evaluation **65 passed**、toolkit **58 passed**；后端 **13,586 passed / 63 skipped / 11 deselected / 7 subtests passed**（1415.45s，exit 0），含独占 PostgreSQL。修改后完整复验另核。
- 成员资格、权限解析和真实密码/JWT/CSRF 多账号联合 **51 passed**。先前联合 **10 failed / 353 passed / 2 skipped** 是旧 provider 调用清单仍包含成员能力；最终已更新为仅由 provider 处理独立能力。真实登录用例误把明确打开的案例交给元数据 canary 检查的 **3 failed / 48 passed** 亦保留；最终断言明确验证本案例内容及其他案例不泄露。
- Linux Node 22 生产构建通过；同平台 ESLint、TypeScript、完整前端 **162 files / 1,436 passed**；宿主相同单测/检查也通过，不将两次通过数相加。后端全量 Ruff **1,298 files** 与 Blocking IO **72 passed**。
- 实际 Linux Gateway 使用新合成 SQLite 完成两个 ledger 的启动迁移，App 到 `eval_0016`；模型为空、QA 执行关闭。通过真实 Linux Next 生产服务完成 **21 次 HTTP 检查**：三账号初始化/普通注册、密码登录、JWT/CSRF、普通用户创建项目/导入/冻结、审核队列、跨普通用户及管理员的项目隔离。
- 真实 Chromium 通过回环端口 `3108` 登录 Linux 工作台，读取真实审核队列、选择本人项目并显示冻结数据集；API mock **0**、重试 **0**、外部请求 **0**。浏览器在 Windows 宿主运行，应用运行于 Linux；截图与收据保存在 ignored 证据目录。最初容器网络切换导致的入口 GET 失败、浏览器脚本将原生 option 判为可见及错误 label 定位均保留，随后按真实 combobox 选择项目修正脚本，不修改业务或延长超时。
- 新源码归档的完整后端首次收集因缺少 `.git` 根标记产生 **4 errors**，未运行 pytest 用例。已在隔离公开源码目录建立无远端的新 Git 元数据，按原完整命令复验；不改 detector 的根解析规则。
- 上述完整复验结束为 **5 failed / 13,591 passed / 63 skipped / 11 deselected / 7 subtests passed**（976.83s，`make test` exit 2）。五项失败来自审批能力诊断与外部技术元数据接收的旧成员权限断言：仍把移除项目 read/write/review 配置视为禁止普通用户。已按全民审核规则分别断言成员成功和独立外部授权拒绝，并保留内部 Agent、匿名及跨项目隔离断言；不是取消外部接收/导出授权。原始日志、JUnit 与退出码已导出至本轮 ignored 证据目录。
- 仅同步上述两份测试到同一 Linux 源码目录，最终门禁：Ruff check/format **1,298 files**、五文件联合回归 **119 passed**（89.07s）、Blocking IO **72 passed**（6.19s），均 exit 0。完整 `make test` 结束：evaluation **65 passed**、toolkit **58 passed**；后端 **13,593 passed / 66 skipped / 11 deselected / 7 subtests passed**（1174.15s，exit 0）。JUnit **13,666 tests / 0 failures / 0 errors / 66 skipped**（含 subtests），SHA-256 `81361ff7b1ba8b51e81b000e4b4f25ed24c5ae976525d383de5b2a3178e0cb1d`。
- 与上一轮相比多出的三个 skip 已精确定位：本轮启动脚本漏传 `DEDUPE_TEST_POSTGRES_URL`，不是业务代码失败或未配置迁移 PostgreSQL。补传至同一独占合成库后，`test_multi_pod_inbound_dedupe.py` **3 passed**（5.79s，exit 0），独立日志/JUnit 留存，不改写完整套件的 66 skipped 或把两次运行拼成一个全量结果。
- 既有审核浏览器回归首次 **5 failed**：测试默认无认证服务，本轮真实认证服务在 SSR 将无会话请求转到登录页，尚未进入审核流程。原失败/页面上下文保留；给测试配置通过真实密码登录获得的合成普通账号会话后，同一已构建 Linux 应用 **5 passed / 0 retries**（8.2s），覆盖桌面/手机领取、明确打开、单次决定、跨项目未知写原 ID 对账、历史重开与仲裁不确定。任务 API 为合成 fixture；不与前述 0 API mock 的真实登录冒烟混为一项。
- 受测 App 的 **25** 份变更 Python 文件与宿主逐一 LF 归一化 hash 一致；冻结 venv 实际通过 editable 路径加载的 Harness/Extension API/devpilot **510** 份 Python 源码也逐一一致，无旧包副本误用。Linux 前端构建/完整 check/test 原始日志已导出；完整前端 Prettier 与本轮指南/文档格式检查通过。
- 已导出最终日志、JUnit、源码/hash 与真实浏览器收据；两份变更前端文件与受测 Linux 副本 hash 一致。确认测试全部结束后，只停止本轮 Python `eabb90fb0c9120da988d6dfced2d918718065f68f509022aa3a93ebe6f47bde7`、Node `fe84f4e716945af095ff4d4ef5b55af6015368e83bc998f53fda8032b5f49a25` 与 PostgreSQL `0409629e8922e8227d312f7e22b4549750a0387a402ca8f3676ee1f9cd1d05d8`。前两者 exit 137/OOM=false（PID 1 为缓存保活进程），PostgreSQL exit 0；保留停止的依赖/构建缓存与内部网络，不删除容器、卷或镜像，不触碰其他项目。
- 全民审核模块已提交并推送 `b9a2f8d3504d56dfe4a1c52da01319a82cd2b46a`，远端 `main` 对应同一 SHA。该 SHA 的 [Unit Tests](https://github.com/helloboy829/DevPilot/actions/runs/43887214811)、[Lint](https://github.com/helloboy829/DevPilot/actions/runs/43887214810)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43887215140)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43887214927)、[E2E](https://github.com/helloboy829/DevPilot/actions/runs/43887215069) 与 [Replay E2E](https://github.com/helloboy829/DevPilot/actions/runs/43887214809) 共 **6 workflows / 12 jobs 全部成功**，包括完整后端、原生 Windows 文件、默认安装收集、软件分发、实际安装导出与前后端 Replay。公开 API 原始收据留在本轮 ignored 目录。一次 Python TLS 证书链观察失败后，改用系统证书只读核对同一工作流，没有关闭证书验证或重跑 CI。
- 上述 CI 只证明 `b9a2f8d`；本段收据文档及后续改动不移用它作为自身 CI。全民审核代码模块闭环，候选全业务流程验收及审批/调度/指标后续阶段仍开放。
- **本人签核候选与统一评测角色复核（2026-11-18，Linux 合成环境）**：`system_role` 的 `user/admin` 是兼容的系统账号分类；所有完成初始化的人类账号获得相同项目 read/write/review，管理员专属依赖仅控制平台运维入口。项目 repository 继续按当前账号做 owner 隔离，盲审/仲裁/签核是具体 run/task 的指派职责；owner 不能进入自己 run 的盲审或仲裁，v2 签核由被指派人本人登录完成。旧 v1 owner 代录仍保留并与 v2 身份链分开校验。
- 本轮后端 Ruff **1,306 files**、Blocking IO **72 passed**、领域测试 **65 + 58 passed**；本人签核/权限/SQLite 恢复组合 **124 passed / 1 skipped**，skip 是该组合中需单独运行的 PostgreSQL 测试。专用 PostgreSQL parity **1 passed**；完整非 live 后端 **13,624 passed / 75 skipped / 11 deselected / 40 warnings / 7 subtests passed**（1757.73s，exit 0）。前端完整单测 **165 files / 1,450 passed** 与 `python scripts/pnpm.py check` 通过，为本候选工作区已有结果。
- 完整后端的首次隔离快照不含当前仓库根文件与 editable DevPilot 源码，出现 **21 failed**；重建公开 Git 跟踪文件根后，20 项路径/环境/旧 editable 源码失败节点逐项重跑全通过，配置升级用冻结环境复验 **1 passed**，随后完整套件通过。依赖导入失败还揭示 PostgreSQL 测试在 async engine 创建前没有进入 `try/finally` 的清理窗口；已将 engine 初始化纳入清理保护，修复后的 PostgreSQL parity 再次 **1 passed**，并确认测试前缀临时数据库数为 0。末尾清理保护改动之后已补跑候选完整后端，见下条；当前精确 SHA CI 仍需重新核验。
- 本轮记录时工作区 HEAD 为 `b9a2f8d3504d56dfe4a1c52da01319a82cd2b46a`，包含未提交的 `eval_0017` 候选与本轮测试/文档更新。该轮没有部署；对应工作区 SHA CI、业务库迁移和真实用户验收仍未完成。专用 PostgreSQL 容器已停止，未删除容器/卷/镜像；此前已运行的 Python 测试容器保留。
- **候选补充回归（2026-11-18）**：新增 `test_postgresql_assigned_signature_migration_parity_and_constraints`，使用独占 UUID 临时数据库验证 `eval_0017` PostgreSQL head schema parity、旧 Harness ledger 保留及请求/事件/视图表约束；签核迁移文件专项 **3 passed**，临时库经 finally 精确删除，确认测试前缀数据库数为 0。数据库容器是此前已核查的合成 PG 容器，本轮结束后恢复为停止状态。
- 新增 auth-enabled Playwright 配置与本人签核浏览器规格，使用真实 Gateway 注册两个普通 `user` 并验证已登录会话；签核业务端点由浏览器路由返回合成数据。三项场景 **3 passed**：普通用户指派固定运行、本人的明确打开/确认/签署/撤销，以及未知写入仅用原 operation ID GET 对账、不重发。签核端点 API 行为仍由后端真实认证集成测试验证；该浏览器回归不调用真实模型、目标或业务库。
- 补充回归之后完整前端 Prettier 与 `pnpm check`（ESLint + TypeScript）通过；新增 PostgreSQL 测试文件 Ruff check/format 通过。以上均针对当前未提交工作区；没有生成当前候选 SHA CI 收据，也未部署。
- **候选完整后端复验（2026-11-18，Linux 隔离环境）**：测试副本由当前 `HEAD` 的 Git 跟踪文件、候选后端差异与新增后端文件构成，未复制私有配置；`make test` 对应的 evaluation **65 tests**、toolkit **58 tests** 均通过。首轮全量有 **3 failed**：配置升级子进程联网解析依赖、本地 QA 隔离子进程失败、以及直接 Python 启动缺少 `PWD`；配置变量补齐后相关定向回归 **4 passed**。使用 `UV_NO_SYNC=1`、工作目录 `PWD` 与专用 `TEST_POSTGRES_URI` 的完整非 live pytest 重跑退出码 **0**，收集 **13,695/13,706 项（11 deselected）**，`lastfailed` 为空。会话切换导致最终 pytest 汇总行未能留存，因此不推算 passed/skipped 总数。
- **签核状态一致性补修（2026-11-18）**：v1/v2 写入共用 run 锁和全局 revision CAS；同一 run 已有 v2 后拒绝新 v1 决定，保留 v1 历史读取与幂等回执。回归覆盖 v2 后索引/有效性一致、旧 v1 重放，以及 v1/v2 并发仅一项追加。相关签核测试 **66 passed**，`user/admin` 评测权限等价 **1 passed**，PostgreSQL 迁移与 v2 JSON 查询专项 **1 passed**。最近一次完整后端复跑有 **2 个本地 QA 隔离子进程失败**；这两个节点随后定向复跑 **2 passed**，但本轮完整套件仍记为未通过。Ruff/format **1,306 files** 通过。
- **跨 Pod 去重 PostgreSQL 复验（2026-11-18）**：使用随机名独占临时库运行 `test_multi_pod_inbound_dedupe.py`，**3 passed**；删除精确临时库后，`devpilot_%_test_%` 前缀数据库计数为 **0**，专用 PostgreSQL 容器已停止，未删除容器/卷/镜像。当前候选仍未部署，精确 SHA CI、业务库迁移和真实用户验收继续开放。
- **本人签核候选精确 SHA CI（2026-11-18）**：`c7db5e2dba831ae436576f7df8ff2ce8ce4dd28f` 的 [Unit](https://github.com/helloboy829/DevPilot/actions/runs/44302977798)、[Lint](https://github.com/helloboy829/DevPilot/actions/runs/44302977606)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/44302977795)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/44302977957) 成功；[Replay E2E](https://github.com/helloboy829/DevPilot/actions/runs/44302978053) 在 Chromium 安装阶段失败，浏览器步骤未执行。该结果只对应此 SHA。
- **PostgreSQL 测试清理修复（2026-11-18）**：迁移 parity 测试把 async engine 初始化放入 `try/finally`，使创建 engine 失败时也能删除刚创建的 UUID 测试库。修复版签核/认证/路由/迁移联合回归 **43 passed / 0 skipped**；测试前缀库数为 **0**。没有部署或运行真实用户业务库迁移。

English: Every initialized signed-in human is an evaluation member without a reviewer role. Ownership, explicit case assignments and per-run independence remain enforced. Linux/container acceptance is the primary delivery path; Windows compatibility is tracked separately. The approval candidate now has PostgreSQL migration coverage and three authenticated browser regressions, but current-SHA CI, deployment and real-user acceptance remain open, as do scheduling and advanced evidence milestones.
