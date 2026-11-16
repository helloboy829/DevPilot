# 全民审核与 Linux 验收接续

更新：2026-11-16。按用户明确要求，所有完成账号初始化的已登录用户都具备项目操作和审核能力，无需单独开通审核人角色或授予审核权限。Linux／容器是本轮主要运行与验收环境，Windows 兼容性单独记录。

## 用户与数据边界

- 普通用户和管理员具有相同的项目读写、复核资格；旧 `evaluation_projects:read/write/review` 名称保留接口兼容，但不再由角色配置决定人类用户是否具备这些能力。
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

阶段 1 尚在推进，后续阶段不因成员权限调整而视为完成。部署现有业务数据、真实用户验收与真实模型/目标调用分别记录，不把合成测试当作这些结果。

## 验证记录

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
- 新提交 CI 仍须按新精确 SHA 核验；候选全业务流程验收及后续阶段仍开放。

English: Every initialized signed-in human is an evaluation member without a reviewer role. Ownership, explicit case assignments and per-run independence remain enforced. Linux/container acceptance is the primary delivery path; Windows compatibility is tracked separately. Runtime acceptance and the remaining approval, scheduling and advanced evidence milestones are still open.
