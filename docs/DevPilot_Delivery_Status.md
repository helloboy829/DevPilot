# DevPilot 当前交付状态 / Current delivery status

> 核对日期：2026-11-10。此页区分**代码已实现、运行已部署、测试证据与未完成范围**，不以功能数量估算完成百分比，也不替代最终用户验收。各切片文档记录当时边界；旧文中的“未部署 / Worker pending / report pending”不是此后的当前状态。

## 2026-11-10：真实登录的合成多账号 QA 回归候选

新增[真实认证离线主链回归](DevPilot_Authenticated_QA_Regression.md)：临时 DB 五个独立合成账号，真实密码登录、JWT/数据库/token-version、CSRF 和启用的 fail-closed RBAC，接通双盲/仲裁、历史评估/报告/复测及 Word/PDF。不挂载旧合成身份中间件，不改运行权限/依赖/迁移。真实账号/浏览器/部署验收与正式批准仍未完成。

- 新模块 **18 项**与既有主链/任务/PDF 路由联合定向 **63 passed，132.04s**。标准 `make test` **12,432 passed / 18 skipped / 11 deselected / 40 warnings，676.37s**；含纯领域 **15 / 58 passed**，与定向不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.61s**；`make lint` Ruff check/format **1,248 文件**与 `uv lock --check --offline` 通过。实际测试的 **1,309** 份后端/领域公开源码逐项核对，缺失/不符均为 **0**。
- 完整 frontend Prettier 与六份变更 Markdown 格式检查通过；本模块不改前端源码，不冒称再次运行前端单测/类型检查/构建/浏览器，也不借用上一提交的 Actions。编写阶段 cookie/路由夹具错误与最终日志均保留，未改运行 cookie、放宽断言、增超时或重试。

本模块仅新增测试/说明，不改运行权限、配置、依赖、迁移或默认禁用执行；候选 head `eval_0012`、历史部署收据 `eval_0009` 不变。推送后须按新精确 SHA 核实全部实际触发的 Actions；本地门禁不等于远端成功。ignored 本机证据在 `.deer-flow/ci/20261110-authenticated-qa/`，测试全部结束、日志导出验 hash 后仅停止本轮启动的四个专用 CI 容器，保留依赖缓存/业务服务/卷，无部署、真实调用或正式批准。

## 2026-11-09 开发 / 2026-11-10 收尾：独立历史报告/重测 PDF 候选

PDF 候选已实际推送 `56c641637d3561f0fa4b5247da01c1549fc2d1d5`，精确 SHA 实际触发七项 Actions **全部 completed / success**：Unit Tests `42651605785`、Frontend Unit Tests `42651606003`、Backend Blocking IO `42651605741`、Lint Check `42651605792`、E2E Tests `42651605830`、Replay E2E `42651605934`、Skill Review CI `42651605943`。这是候选源码 CI，不是本机部署或正式批准。

新增 [独立历史 PDF 草稿](DevPilot_Independent_PDF_Drafts.md)：`independent-qa-pdf-v1` / `independent-retest-pdf-v1` 只读取既有固定 Word-v1 renderer 的内部历史公开投影，分别保持存储 Markdown/历史收据与无 Markdown 的重测公开比较事实。人类 owner + read/review、已查看 hash、off-loop 完整性/渲染、ALL 冻结总体、精确 namespace、显式下载/ref 锁/迟到响应屏障和不重试均保持。旧 Word、档案、模板和 hash 不变。

固定 A4 文字/表格布局，逐页草稿标记、嵌入可重现 OFL 衍生字体、引擎版本/字体 SHA 检查、整文页数/字节上限；不支持的 glyph/组合字符/复杂方向整体拒绝，不静默替换/裁掉样本。无 HTML、外部资源、系统字体回退、链接动作、附件、签章或批准。字体两次独立构建 SHA 一致；PDFMiner/PDFium 独立读取/实际栅格检查不等于人工视觉验收、PDF/A 或 PDF/UA。

- 新旧 renderer/路由、独立档案与 API→真实离线 Worker 定向回归 **178 passed / 1 warning，121.46s**。标准 `make test` **12,414 passed / 18 skipped / 11 deselected / 40 warnings，702.64s**；纯领域 **15 / 58 passed**。定向/领域与全量不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.68s**；`make lint` Ruff check/format **1,247 文件**通过；字体构建脚本单独 Ruff check/format 通过。
- 前端完整单测 **1,206 passed / 148 文件**（最终测试文件复核 14.7s）；完整 Prettier、ESLint、typecheck、生产构建通过。完整模拟 Chromium **226 passed，2.5m**、认证恢复 **2 passed，1.3m**，均零自动重试；桌面/手机 PDF 使用真实合成二进制 fixture，不是真实多账号或模型/目标验收。
- 唯一新增运行依赖 `reportlab==4.4.10`。Dockerfile 固定的 uv **0.7.20** 真实解析锁，且 uv **0.13.7** 检查兼容；两者 offline lock check 均通过。原 249 个包版本全部不变，仅增加一个包；Tenki 可选源只绑定原官方 0.4.0 wheel/同 SHA，应对索引 404，不删 extra、不换 SDK、不启用调用。字体构建工具只用于隔离构建。
- 实际测试源码与待提交文件按文本 LF/二进制原 bytes 核对：后端/领域 **1,308**、前端 **827** 个文件，缺失/不符均为 **0**。初始读取器/夹具失败和最终日志分别保留，未用重试、扩大超时或弱化完整总体断言掩盖错误。

候选 App head 仍为 `eval_0012`，历史部署收据仍为 `eval_0009`；无迁移、部署、生产配置/key、执行启用或真实模型/目标调用。正式批准政策/角色/生命周期、经授权保留数据升级、真实多账号与最终用户验收仍未完成。上列精确推送 SHA 的七项实际 Actions 已核实，不能将这些结果冒用为后续新提交的 CI；本机合成日志/hash/CI 回执只存 ignored `.deer-flow/ci/20261109-independent-pdf/`。

## 2026-11-09：独立历史重测 Word 候选

独立历史重测 Word 已在 GitHub 远端核实 `a3fb0db9de885a03e9883743216b5aca6c93665f`，六项 Actions 均 completed/success：Unit `42634173580`、Frontend Unit `42634173600`、Blocking IO `42634174621`、Lint `42634173290`、E2E `42634173439`、Replay `42634173556`。此前待推送回执由本次远端核验替代，不推断部署。

新增 [独立历史重测 Word](DevPilot_Independent_Retest_Word_Drafts.md)，以单独 `independent-retest-docx-v1` GET 导出显式打开的历史档案。重测没有存档 Markdown/报告 revision：此处固定双语白名单投影存档公开比较事实，保留全部冻结样本和两侧历史 assessment/任务承诺；不是重新渲染报告或重新计算指标/阈值。人类 owner + read/review、已查看 hash、off-loop 完整性/渲染、大小上限、文字安全、ref 锁/迟到响应屏障和错误不重试均保持。旧 owner/独立报告 Word、档案与 hash 不变，无依赖或迁移。

- 新旧 renderer/路由、独立档案与 API→Worker 定向回归 **148 passed / 1 warning，140.88s**；标准 `make test` **12,384 passed / 18 skipped / 11 deselected / 40 warnings，669.14s**，纯领域 **15 / 58 passed**。定向/领域与全量不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.89s**；`make lint` Ruff check/format **1,244 文件**通过。MarkItDown 独立读取器输出会转义 Markdown 下划线；保留原始 OOXML 精确断言，并按读取器契约精确验证转义内容，不削弱样本总体/收据检查。
- 前端全量 **148 files / 1,182 passed**，完整 Prettier、ESLint、typecheck、生产 build 及本轮 Markdown 格式检查通过。完整模拟 Chromium **220 passed，2.4m**，单独认证恢复 **2 passed，1.6m**；均 retries=0。新导出包含桌面 1440px/手机 390px、键盘下载、真实生成 OOXML fixture、409 不重试与无敏感请求检查。
- Python 测试相关 **1,367 个**、Node 前端 **823 个**公开文件逐项 SHA-256 与工作区一致（共享 fixture 重叠，不相加宣称唯一文件数）；初始失败和最终日志导出到 ignored `.deer-flow/ci/20261109-independent-retest-word/`，包复制后验 hash，不提交私有数据或本地证据。
- 只使用本线程重建的隔离 Python/Node/PostgreSQL/Redis 缓存容器，无业务挂载/发布端口；全部测试退出、证据导出/核对和文档检查后只停止本轮启动的四个精确 ID，保留依赖缓存/业务服务/卷。精确源码 SHA 的实际 Actions 另行核对，成功 push 不等于 CI 成功。

候选 head 仍为 `eval_0012`，历史部署收据仍为 `eval_0009`；本模块没有部署、启用执行、生产 key 或真实模型/目标调用。该 Word 切片当时不含 PDF，后续 PDF 候选见本页首节；正式批准政策、经授权的保留数据升级、真实多账号和最终用户验收仍未完成。

## 2026-11-09：独立主链合成回归候选

新增 [独立主链离线集成回归](DevPilot_Independent_Workflow_Regression.md)，以 HTTP 创建的三个冻结样本、v2 计划和真实有界 Worker 串起独立双盲任务/第三人仲裁、评估修订、历史报告/同基准复测及固定 Word。并发 1/2、六种采集故障、四类写入提交前/后响应丢失，共 16 个参数化用例。无运行时代码、迁移、依赖或前端行为变化；不部署、启用运行、生成生产 key 或调用真实模型/目标。本地门禁完成，已提交并实际推送 `b1fe355c1c924b0a0073f154b7c25ee65f491e64`。精确 SHA 实际触发四项 Actions 均 completed/success：Unit Tests `42625066294`、Frontend Unit Tests `42625066349`、Backend Blocking IO `42625066311`、Lint Check `42625066514`。路径过滤未触发 E2E/Replay，不计为本模块浏览器 CI 通过。

- 新增集成用例 **16 passed，44.11s**；标准 `make test` **12,339 passed / 18 skipped / 11 deselected / 40 warnings，606.06s**，纯领域 evaluation/toolkit **15 / 58 passed**，均 exit=0。定向用例已包含在全量中，不叠加计数。
- `make test-blocking-io` **72 passed，5.50s**；`make lint` 全目录 Ruff check/format **1,241 文件**通过；整个前端 `pnpm format` 与本轮 Markdown 格式检查通过。没有前端运行时变更，本模块没有本地重跑前端单测/build/浏览器，上一模块结果另列而不冒用。
- 实际 Python CI 快照的 **2,178 个**公开源码/测试/静态文件逐项 SHA-256 一致；二进制原始字节和文本统一行尾分别处理。测试编写阶段失败日志和最终结果一起导出，本机 ignored 证据不提交。
- 仅复用本线程重建的专用 Python/Node/PostgreSQL/Redis 容器，internal 网络且没有业务挂载/发布端口。最终收尾在测试进程退出、日志导出/验 hash 和文档格式验证后进行；不停止预存服务，不删容器、卷或镜像，不全局 prune。

上一 Word 模块已实际推送 `86c13930cd688b55722020da2b68b74bb61d25c7`，精确 SHA 的六项 Actions **全部 completed / success**：E2E Tests `42620344093`、Unit Tests `42620343936`、Frontend Unit Tests `42620343965`、Backend Blocking IO `42620343994`、Replay E2E `42620343903`、Lint Check `42620343976`。这只是该候选提交的 CI，不是 `eval_0012` 部署或真实身份/目标验收。

## 2026-11-09：开发接续与独立历史报告 Word 候选

本轮接手时工作区干净，本地及实际远端 `main` 为 `8890bd061f3407b8c187ceaf388dff28aa463b4e`。该完整 SHA 实际触发四项 Actions，均成功：Unit Tests `42573792483`、Frontend Unit Tests `42573792602`、Backend Blocking IO `42573792621`、Lint Check `42573792762`；未触发 E2E，不外推其结果。较早章节保留历史状态，不是本轮运行收据。

首个模块新增单独的 `independent-qa-docx-v1`：人类 owner + read/review，显式历史档案 ID/已查看 hash，复用 off-loop 存档完整性验证并 off-loop 渲染。输出只有冻结 Markdown 与公开历史 assessment 收据；不重开证据/当前任务/模板、不重算指标、不替换 owner 票，旧 `qa-docx-v1` 和历史哈希不变。前端独立下载保持大小/MIME/renderer 校验、ref 锁和迟到响应围栏，无重试或写入重发。合同见[独立 Word](DevPilot_Independent_Word_Drafts.md)；整体缺口和接续顺序见[开发计划](DevPilot_Development_Plan.md)。

所有依赖从跟踪源码和锁文件重建到本轮专用 Linux Python 3.12/Node 22 容器；PostgreSQL/Redis 只含合成测试数据、无业务挂载或发布端口。依赖安装后容器仅 internal 网络；不复制本机私有配置、数据库、venv 或 node_modules。本机业务容器只读健康元数据，不据此宣称新版部署。

- 未修改源码基线：后端 `make test` **12,294 passed / 18 skipped / 11 deselected，681.24s**；纯领域 **15 / 58 passed**。前端 **148 files / 1,164 passed**。
- 本模块新旧 Word/独立档案定向回归 **61 passed，39.60s**；独立 Blocking IO **72 passed，28.37s**；Ruff 全目录 check/format **1,240 文件**通过。定向回归与全量有重叠，不叠加计数。
- 修改后前端全量 **148 files / 1,173 passed**；完整 Prettier、ESLint、typecheck 和生产 build 通过。合成 Word 桌面 1440px/手机 390px、键盘下载、真实生成 fixture、409 不重试：**3 passed，4.7s**，retries=0。
- 修改后标准 `make test` **12,323 passed / 18 skipped / 11 deselected / 40 warnings，807.32s**；纯领域 **15 / 58 passed**。完整工作区 Chromium **217 passed，2.4m**；独立认证恢复配置重建并测试 **2 passed，2.1m**，均 retries=0、exit=0。浏览器使用合成 API，不是部署或真实多账号验收。
- 两个实际 CI 容器各 **2,177 个**公开运行/测试文件与工作区逐项 SHA-256 一致（按 Git 统一文本行尾）；失败日志与最终结果一起保留在 ignored 本机会话证据目录。
- 首次基线收集缺少 Git 根标记、一次定向命令文件名错误，以及新增测试的格式/import/空函数 lint 失败均保留原日志；修正环境/命令/代码，不删除或弱化断言、不增加超时或重试。构建的无 Git 历史时间戳警告不是功能验收。

候选 migration head 仍为 `eval_0012`；无新迁移、依赖、生产配置、key、执行启用或真实模型/目标调用。该报告切片当时不含独立复测 Word（后续候选见本页首节）；PDF、正式批准、真实多账号联调、保留数据升级与最终用户验收仍未完成。本模块本地门禁及独立提交/push 已完成，精确 SHA 与六项成功 Actions 见上节；这不替代后续模块自身的 CI。收尾在确认测试进程全部退出、56 份成功/失败日志与退出码导出且六份主要日志验 hash 一致后，只按四个精确 ID 停止本轮专用 CI 容器；保留依赖缓存，没有停止预存服务、删卷、删镜像或全局 prune。

English: the continuation baseline and its four successful runs are explicitly pinned. The new independent historical report Word draft is a separate, bounded, read-only renderer; legacy exports and approval/execution boundaries remain unchanged. New local gates are recorded separately from previous CI and historical deployment; unfinished checks are not success claims.

## 2026-11-09：新电脑 CI 排查与 Worker 取消修复

本地与实际远端 `main` 已核对为 `c7ddbdc1417a589bbb544effb2e65630601823e8`。该 SHA 的六项 Actions 不是全绿：Frontend Unit Tests `42543077302`、Replay E2E `42543077373`、Lint Check `42543077333`、E2E Tests `42543077345`、Backend Blocking IO `42543077363` 成功；Unit Tests `42543077340` 失败，其默认安装收集 job 成功，后端 job `128922108984` 为 `1 failed / 12,291 passed / 18 skipped / 11 deselected`。原始 job 日志已下载并保留，失败是合成并发 Worker 收尾 `JournalWriteUnconfirmed`，不能归咎于换电脑。

新电脑初始仅见四个停止的旧 `deer-flow-dev` 容器；前电脑 `0fd689...` / `eval_0009` 的部署收据仍是历史验证，不宣称此机已有同一部署。未启动旧服务或读取其配置、账号库和日志。宿主默认 Python 3.11、不可执行旧 venv、pnpm 11 与 PowerShell 脚本限制均单独记录，不更改全局策略或降低仓库版本要求。

本轮独立 Linux Python 3.12、冻结依赖、PostgreSQL 17/Redis 7、internal 网络复现失败，临时观测确认 monitor SELECT 被取消后留住 SQLite 锁，最终 commit 失败。修复仅将 monitor DB 读取纳入现有排空保护；取消、无重试、未知结果不重发和配额保留语义不变，无迁移、依赖、运营开关或部署改动。

- 最终标准 `make test`：**12,294 passed / 18 skipped / 11 deselected / 40 warnings，596.69s**，exit=0；其中包含新事件屏障取消和重复取消回归。纯领域 evaluation/toolkit 由标准入口分别 **15 / 58 passed**，不与 pytest 数相加。
- 执行、真实 Worker 合成链及附件定向：**63 passed，22.38s**，与全量有重叠，不相加。旧 monitor 的确定性红测试先因提前 finish 失败，修复后通过，不靠增加超时、修改 WAL 或串行化请求。
- 原合成工作流全文件连续三轮各 **8 passed**；独立 Blocking IO **72 passed，6.55s**。这是重复稳定性和独立门禁验证，不与全量叠加计数。
- Ruff 全目录 check/format **1,237 文件**通过；整个 frontend Prettier 和本轮 Markdown 指南检查通过。前端运行源码没有改动，本轮不冒称重跑前端单测、浏览器或构建；Windows 全套也未重跑。
- 初始 slim 容器缺系统 MIME 数据库/Node，首次完整回归为 **3 failed / 12,282 passed / 25 skipped / 11 deselected**；补齐 CI 工具后原 XHTML 附件测试通过，业务 MIME 代码未改。原失败、收集命令引号失败及诊断日志均保留在 ignored 证据目录。

源码收尾核验 **1,360 个**受跟踪非 Markdown 运行/测试文件与实际回归容器逐项 SHA-256 一致，**15 份**日志导出并验 hash。确认测试进程已全部退出后，仅停止本轮三个 CI 容器、移除从未启动的精确 Node 工具来源容器及本轮 internal 网络；四个旧业务容器保持原停止状态，未删卷、镜像或共享缓存。测试证据/资源 ID 只在 ignored 目录保存，不计为部署证据。

当前修复完成后必须按新推送 SHA 单独核对 Actions；本节本地通过不是新 SHA 的远端成功。候选 head 仍为 `eval_0012`，没有业务数据迁移、真实模型/目标调用、正式批准或用户验收。[复现环境](DevPilot_CI修复与隔离开发环境.md)与[执行合同](DevPilot_Admitted_QA_Execution.md)记录细节。

## 1. 版本与运行边界

- 本轮起点：`main`，源码提交 `d2a58a390971`。后续工作区修改不属于该提交的 CI 证据。
- 最近独立核验的本地运行版本：`0fd689da83a4ac7646250447fb6d044599a823c5`，App migration head `eval_0009`。升级前在线一致性备份，保留原账号、配置、数据、挂载与 Harness ledger；详见[部署记录](DevPilot_Local_Recovery_and_Upgrade.md)。这是历史核验收据，不是每次打开本文就重新完成部署。
- 六项触发 Actions 成功仅属于上述完整运行 SHA；不得外推为当前 HEAD 或工作区 CI 通过。Windows 完整回归仍有独立失败，定向复验不能替代全量。
- 按最近部署记录，模型与请求加密 key 未配置，QA 执行保持默认关闭。不得为“完成度演示”自动生成 key、修改策略、调用真实模型/目标或导入客户原件。
- 本轮复用既有 Docker Python 3.12 / Node 22 隔离依赖；只导出 Git 源码与显式变更，不复制私有配置/数据库。测试结束停止本次启动的 CI 容器，缓存不等于过期垃圾。
- 本轮工作区新增 PostgreSQL `sslmode` → asyncpg `ssl` 兼容修复及回归；保留原 TLS 模式和同步 DSN，冲突/无效参数明确拒绝。当前运行部署不包含这项修改；没有改依赖、迁移、生产配置或调用真实目标。

当前工作区新增独立逐条复核后端/API、`/workspace/reviews` 中心及项目内联分配/详情，以及独立全样本评估预览/不可变修订 API 候选，App head `eval_0012`（独立档案追加迁移）；未升级现有 `eval_0009` 运行库。两名盲审人及独立仲裁只获具体冻结 case 的授权，共用同一任务服务；评估修订 UI 已有候选；报告/复测已有显式历史来源绑定后端/API 及独立选择 UI 候选，正式批准尚未交付。[合同与范围](DevPilot_Independent_Case_Review.md)。

## 2. 已实现的评测主链

| 环节                  | 当前代码能力                                                                   | 必须保留的边界                                                                                       |
| --------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| 项目与组件            | owner 隔离项目、现有组件关联、不可变提测清单                                   | `inventory_only` 不是可执行 RequestSpec 或批准                                                       |
| QA 与请求版本         | JSON/JSONL 导入、自复核冻结、分离金标读取；完整请求显式加密保存                | 自复核不是独立审批；普通元数据不含金标、请求明文或密文                                               |
| 冻结计划与标准        | 请求/QA 版本、严格 JSON 输入输出映射、预算与 v2 效果阈值冻结并绑定 hash        | v1 hash/历史模板不变；冻结本身不授权执行                                                             |
| 独立执行准入          | 人类单独确认、全局 DB 配额、一次 claim、有界 Worker、逐序号持久派发日志        | operator 默认关闭；未知写入/交付不重发，失联 Worker 不回收配额                                       |
| 输出与人工复核        | 加密提取输出、按需打开 Q/A/参考/来源、追加人工决策及修订                       | 采集成功不是 PASS；缺少证据不能 PASS；该路径仍是 owner 自复核                                        |
| 独立逐条复核（候选）  | 两名盲审、第三人仲裁；窄授权、租约/回执、追加结论与历史轮次；中心/内联共享服务 | `eval_0010` 任务切片未部署；不接入原汇总/报告，不是正式批准                                          |
| 独立评估修订（候选）  | 全冻结分母、独立决定验真、阻塞与整数阈值；显式不可变评估修订/CAS               | `eval_0011` 未部署；已有独立评估 UI，后续 `eval_0012` 显式历史来源 API，非正式批准                   |
| 独立报告/复测（候选） | 指定历史 assessment ID/修订/hash、独立固定模板、原子报告与同基准比较           | `eval_0012` 未部署；已有独立选择 UI、报告/复测 Word 与 PDF 候选；正式批准未交付，不切换旧 owner 档案 |
| 已验证汇总            | 逐条验证输出与最新人工决策，固定全量冻结样本分母，整数阈值比较                 | 未复核/不确定/技术缺失阻塞；完整或 `met` 都不是批准                                                  |
| 报告草稿              | 不可变多组件汇总、固定模板全文/版本、冻结 Markdown、历史 Word 草稿下载         | 手工/Agent 建议独立且未验证；无正式出具/审批或 PDF                                                   |
| 同基准复测            | 严格相同基准/预算/标准，两版完整复核运行的逐样本变化与不可变存档               | 非自动再执行/通知；当前复核修订不改写历史判断                                                        |

证据入口：[计划](DevPilot_Frozen_QA_Plans.md) · [阈值](DevPilot_Frozen_Effectiveness_Criteria.md) · [执行](DevPilot_Admitted_QA_Execution.md) · [复核](DevPilot_QA_Evidence_Review.md) · [独立复核](DevPilot_Independent_Case_Review.md) · [独立评估](DevPilot_Independent_Assessments.md) · [独立档案](DevPilot_Independent_Report_Retest_Archives.md) · [汇总](DevPilot_Verified_QA_Summaries.md) · [报告](DevPilot_Immutable_QA_Report_Archives.md) · [Word](DevPilot_QA_Word_Draft_Export.md) · [复测](DevPilot_Same_Benchmark_Retesting.md)。

## 3. 可用但不能混为新链路完成的能力

- 旧组件效果/性能原型及定时评测已有入口；并不等于冻结 QA 新链路的独立调度准入、持久队列恢复或正式验收。
- cURL 调试、手工/Agent 报告草稿、管理员模型管理、私有助手可用。配置助手不等于存在已配置模型，也不授予 Agent 人工确认/批准权限。
- 出站共享 DNS-pinned transport 已覆盖调试/手工/旧调度，但所有遗留适配器、完整版本化 RequestSpec 与独立 runner 还未统一交付。
- Docker 健康信号、只读诊断、账号页面 smoke 证明各自检查范围，不是质量效果、完整数据库验收、长期稳定性或真实目标调用授权。

## 4. 尚未完成与下一阶段门禁

| 优先级 | 工作                                  | 完成前必须证明                                                                                                                                       |
| ------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0     | 当前修复/独立复核候选的 CI 与部署闭环 | 前轮 Linux/前端门禁通过；新增 API→Worker 回归及独立复核后端/共享界面候选，但须按每次推送 SHA 单独核验远端 CI，尚未部署；部署前另备份、保留数据与回退 |
| 维护   | Docker 资源收尾（每轮持续执行）       | 两个旧验证容器及无引用旧镜像已精确退役；每轮测试完停止该轮启动的 CI 容器、精确清临时快照并复查业务健康；保留卷与缓存                                 |
| P1     | 独立档案的正式批准与验收              | 独立复核中心/内联 UI 及全量独立评估 API/修订 UI 已有候选；已有显式历史来源绑定后端/API，已有独立选择 UI；仍须版本化审批，不能把 case pass 当批准     |
| P1     | 失联 Worker 安全运维及 QA 调度准入    | 证明旧进程不再能发送后才考虑运维释放；不按超时盲目回收、不重发未知交付、不借用旧调度绕过准入                                                         |
| P1     | 统一执行适配器与可复现独立导出        | 共用版本化语义、授权/限额/出站边界，导出不泄漏 key/金标且不是模型自由生成 runner                                                                     |
| P2     | QA 治理、CV、流式性能与模型裁判       | 授权数据、跨集防泄漏、真实可观测 TTFT/TPS、显式模型同意与校准；无证据不填零或通过                                                                    |
| P2     | 整改工单/通知与知识闭环               | 明确权限、脱敏与人工晋升；复测档案不是自动整改系统或训练材料                                                                                         |

这些是待交付工作，不因本轮文档校准或测试完成而自动变为“整个项目已完成”。最终验收仍由用户执行。

## 5. 工程验证与运维记录

前一轮修复后 Docker 后端完整回归 **12,118 passed / 18 skipped / 11 deselected**；纯领域 evaluation 15、toolkit 58 分别通过，Ruff check/format 通过（1,220 文件）。前端 format、ESLint/TypeScript、生产构建通过，140 文件 / 1,094 单测、201 常规浏览器测试及 2 独立认证恢复测试分别通过。schema + Node 探针独立补测 26 passed，不能与完整套件相加。

前一轮 Docker 收尾已完成：退役 2 个过期验证容器和对应 2 个无引用旧镜像，停止 4 个 CI 容器，保留依赖缓存/所有数据卷/其他项目；最后业务服务全部 healthy。本轮没有升级生产、提交或推送，后续仍需独立 CI、保留数据部署与用户验收。

### 后续开发轮次：API → 实际 Worker 合成回归（2026-11-09）

新增 `backend/tests/test_qa_workflow_api.py`，**8 项定向通过**：API 创建三样本 QA、两个请求版本及冻结 v2 计划，接入实际 Worker/持久派发/加密证据/人工复核/汇总/报告与 Word/同基准复测。覆盖并发 1/2、发送前提交日志、旧版请求绑定、六类技术失败与未知交付不重发、全量分母/整数阈值、后续复核不改写历史档案和读取权限。

- 这是临时已迁移 SQLite、合成认证/数据/key、DNS/HTTP wire 替身与真实 socket 禁止的离线回归；不是部署 GUI、真实认证/目标效果验收，也不补足独立审批。没有新增生产能力、依赖或迁移。
- 隔离环境修复后，完整变更前 **12,117 passed / 19 skipped / 11 deselected / 40 warnings**；变更后完整回归 **12,125 passed / 19 skipped / 11 deselected / 40 warnings**（430.43s）通过。两组纯领域 **15 / 58** 分别通过；Ruff check/format **1,221 文件**通过。历史与本轮计数独立，跳过不算通过，不能拼接定向与全量。
- 未修改前端源码；前一轮前端全量证据未重跑。当前运行部署不变，尚无本工作区独立远端 CI 或保留数据部署证据。本轮三个本次启动的 CI 容器已停止，Node CI 保持停止；Docker/宿主临时快照、独立 venv、Node 与源码 tar 已精确清理，缓存/卷/其他项目保留，最后四个业务服务 healthy、诊断 ok。无新增镜像清理或业务升级，详见运维记录。

本轮实际运行及失败原因追加在[隔离环境记录](DevPilot_CI修复与隔离开发环境.md)，Docker 资源处理追加在[诊断与维护](DevPilot_Docker_Diagnostics.md)。不得把多个有重叠的测试组相加为完整套件；也不得用镜像显示大小推算实际宿主释放空间或 RAM。

### 后续只读资源复查（2026-11-09 02:14）

四个业务服务 healthy、restart=0、OOM=false，四个 CI 容器均 exited；没有无引用的 DevPilot 标签镜像。显式 dangling 复查发现一项仍被其他项目停止容器引用的镜像，予以保留；构建缓存未验证归属，不清理。本轮未启动/停止/删除资源、未构建或部署，零删除不重复计数为前轮清理。仅更新资源收据与维护约束，没有运行代码变更或测试重跑；上述全量测试仍属于此前工作区证据。

English: the bounded QA path now includes immutable plans/criteria, admitted collection, encrypted evidence, human review, verified summaries, draft archives and same-benchmark retests. Formal independent approval, safe lost-worker operations, new-path scheduling, unified runnable exports and advanced evaluation/governance are still incomplete. Code, deployment, test results and user acceptance are separate claims.

### 历史后端切片：独立逐条复核后端/API（2026-11-09，后续 UI 另列）

两个不同盲审人、第三名不同仲裁人及 owner 分离；明确分享一个冻结 case，不开放项目成员/普通数据权限。领取/释放、30 分钟租约、已看版本回执、原子追加决定/结论/审计、撤销及不覆盖历史的重开已实现。缺输出/技术失败不能 PASS。候选 `eval_0010` 仅追加五表两索引，部署仍为 `eval_0009`；**UI、assessment/汇总/报告接入及正式批准仍未完成**。[服务合同与隐私](DevPilot_Independent_Case_Review.md)。

最终完整变更后复验 **12,191 passed / 19 skipped / 11 deselected / 40 warnings，471.47s**；纯领域 evaluation/toolkit 分别 **15 / 58 passed**。Ruff 全量 check/format **1,227 文件**通过。定向 67、迁移关联复验 24 与完整套件有重叠，不相加；skipped/deselected 不算通过。 变更前首次正确隔离全量发生 1 项 Worker finish 派发回归失败，根因未确认；同文件和完整基线随后通过，原失败保留。第一次变更后完整回归暴露旧库测试错误枚举未来表，修正测试旧表清单后重跑全量，未跳过或削弱数据保留断言。完整历史见[隔离记录](DevPilot_CI修复与隔离开发环境.md)。

本轮没有前端源码/页面交付、远端 CI、提交、推送、生产升级或真实模型/目标调用，不将后端测试通过等同用户验收或整个平台完成。Docker 收尾另按[维护记录](DevPilot_Docker_Diagnostics.md)保存精确资源收据。

本轮资源收尾已核验：三个本次启动的 CI 容器停止、Node 未启动；独占 Docker 快照/venv/Node/辅助文件清理且共享缓存哈希不变；其他容器与镜像未变。无安全可删的过期 DevPilot 镜像，本轮零镜像删除。四业务服务 healthy、诊断 ok；所有失败/通过日志与收据保留，未启用后台自动删除。最终契约 91 项与全量重叠，不相加。

### 后续开发轮次：共享独立复核中心与内联 UI（2026-11-09）

`/workspace/reviews` 与项目 case 的明确分配入口复用同一任务服务；租约、已看版本、双盲/仲裁、owner 历史轮次、unknown write 同 ID 核对及跨项目页内待办 ID 保留已实现。候选 `eval_0010` 不新增其他迁移，尚未部署；assessment/汇总/报告接入及正式批准仍未完成。[当前范围与验证](DevPilot_Independent_Case_Review.md)。

全量前端单测 **1,125 passed / 144 文件**，生产构建通过；完整模拟浏览器 **206 passed**，登录/设置恢复 **2 passed**，均零自动重试。四文件 31 项与浏览器定向 5 项已经包含在对应全量中，不重复计数。最初测试工具/快照错误及移动端溢出失败已留存，修复后按原门禁重跑。没有真实多账号/后端连接 UI 验收、模型/目标调用、提交、推送或部署；本轮不冒称重新跑过后端全量。最终完整 frontend Prettier（含前端指南）、lint/typecheck 及 1,125 项单测再次通过；833 份隔离快照文件与宿主清单逐项 SHA-256 核对无差异。最终资源收尾及其后的纯文档追加另记录，不能据此声称重新运行后端或完成真实验收。

本 UI 轮资源收尾已完成：37 份日志/收据已导出并逐项校验；独占 Docker 快照、辅助文件及宿主 staging 精确清理，五个明确的共享缓存标识哈希未变。仅停止本轮 Node CI，其他三个 CI 保持停止；全部其他 13 容器及镜像引用清单未变。无可删的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除。最终业务四服务 healthy、诊断 ok；未改配置、迁移生产或启用模型/目标。详见[维护记录](DevPilot_Docker_Diagnostics.md)。这段是全量测试后的纯文档追加，不代表再次运行完整套件或候选已经部署。

### 后续开发轮次：全样本独立评估与不可变修订（2026-11-09）

候选 `eval_0011` 新增独立评估预览和显式追加的评估修订 API：全部冻结效果样本参与分母，全部当前轮次任务验真，不读取 owner 自复核决定；缺证据、待处理、撤销、分歧及技术失败阻塞完整性。整数阈值、off-loop 验真/锁内整快照复查、revision CAS、事务审计与不可变历史已实现。允许 provisional 归档，但一律非正式批准，不切换旧汇总/报告/复测。[合同](DevPilot_Independent_Assessments.md)。

最终 Docker 后端完整回归 **12,231 passed / 19 skipped / 11 deselected / 40 warnings，489.52s**；变更前基线 12,191 passed。纯领域 **15 / 58 passed**、Ruff check 与 format **1,232 文件**通过；104 项定向与完整套件重叠，不相加。2,472 份公开源码与测试快照逐项 SHA-256 一致。早期 fixture/迁移测试失败与修正完整留档，历史 Worker 偶发失败根因未确认。本轮没有前端源码变更或前端门禁重跑；资源收尾后的修改仅为文档和 ignored 证据。

本轮三个 CI 已停止，Node 保持停止；独占 Docker 快照/辅助文件、已导出并验真的证据副本和宿主 staging 精确收尾，共享缓存/全部卷保留。全部 14 容器最终 ID/镜像/状态/restart/OOM 与测试前一致，镜像清单不变；无可安全删除的过期 DevPilot 镜像，镜像/容器/卷零删除。业务四服务 healthy、诊断 ok。停止输出断言失败经独立只读检查确认最终状态，未重复破坏性操作；原记录保留。[资源边界](DevPilot_Docker_Diagnostics.md)。

当前候选未提交/推送/远端 CI/部署，运行 head 仍为 `eval_0009`；评估 UI、报告/复测显式绑定与正式批准待开发，真实多账号联调与最终用户验收仍待进行。测试通过不等于整个平台完成。

### 后续开发轮次：独立全样本评估 UI（2026-11-09）

`IndependentAssessmentPanel` 已接入项目工作区，独立于旧 owner 汇总：明确加载预览/历史、严格全量 DTO、provisional 非批准归档、hash + revision CAS、页内唯一待办 ID、未知写入同 ID GET-only、跨范围迟到响应隔离及固定历史打开。无报告/复测来源切换、正式审批、新迁移或依赖。[界面合同](DevPilot_Independent_Assessments.md#8-独立评估工作区-ui2026-11-09)。

完整 frontend Prettier、lint/typecheck、生产构建通过；**1,152 单测 / 146 文件、210 完整模拟浏览器、2 登录恢复**均通过，浏览器零自动重试。定向 27 / 4 项与全量重叠；本轮后端未重跑，早期开发/环境错误完整留档。不等于真实多账号联调、远端 CI、部署或用户验收；候选 `eval_0011` 未部署，独立报告/复测绑定与正式批准仍未交付。

本 UI 轮资源收尾已独立核验：30 份 Docker 日志/JSON 先导出并逐项验 SHA-256，834 份公开源码/测试/指南与测试快照一致；随后仅删除本轮独占快照、12 个辅助文件及已备份证据副本，宿主 staging 亦精确删除。仅停止本轮 Node CI，其余三个 CI 始终停止；最终全部 14 容器的 ID/镜像/运行或停止/restart/OOM 签名恢复测试前状态、9 行镜像标签清单不变。无可安全删除的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除；业务四服务 healthy，诊断 ok。五个明确 Node 缓存标识哈希未变，不声称整个缓存树已审计。资源收尾后的追加仅为文档，不代表重跑完整套件或已部署。

### 当前开发中工作与 Docker 收尾（2026-11-09 06:51）

独立评估修订显式绑定报告/同基准复测已开始 TDD 和仓库扩展，但仍是 **WIP，不可作为已交付 API 使用**：新模块依赖的独立表、追加迁移及路由尚未完成，定向绿灯和变更后全量也未完成。没有新增 `eval_0012` 迁移，候选迁移 head 仍为 `eval_0011`，部署仍为 `eval_0009`。不回滚或删除工作区中的既有和开发中修改。

本次接手后确认基线测试自然结束：**12,224 passed / 37 skipped / 40 warnings，537.19s**，完整日志保留；这是变更前基线，不能覆盖之后两个报告/复测仓库文件的改动及新增未完成模块/测试，也不替代此前 UI 的验证或真实多账号验收。新模块缺失时的预期导入红灯亦保留，尚无本轮实现后通过结果。

本轮资源已独立核验收尾：四份日志/JSON 先导出验 hash，再清理本轮独占 Docker 快照/临时文件/已归档结果副本及宿主 staging；三个共享 editable 和 51 个 launcher 明确哈希不变。本轮启动的三个 CI 均已停止，Node 始终停止；14 容器最终签名及镜像清单恢复开始状态。无安全可删的闲置 DevPilot 镜像，唯一无标签镜像仍有容器引用；镜像/容器/卷零删除。业务四服务 healthy、诊断 ok，数据/配置/共享缓存与其他项目保留。[操作与证据边界](DevPilot_Docker_Diagnostics.md)。

下一开发门禁仍是完成独立历史评估来源的严格表/API/原子存档与回归，再推进显式 UI、正式批准、真实多账号联调、独立 CI 及保留数据的备份升级；并非整个项目已经完成。

### 2026-11-09：独立历史评估绑定报告/复测的后端门禁

本轮已实现独立命名空间的历史评估修订绑定后端/API，候选 App head 为 `eval_0012`，未部署，现有运行 head 仍为 `eval_0009`。来源显式固定 assessment ID / 修订 / hash，不追随任务重开或最新意见；保留 ALL 冻结样本分母、严格同基准/预算/标准、历史不可变及 `not_approved`。独立选择 UI、独立 Word/PDF、正式批准和真实多账号联调仍未交付。

- Docker Python 3.12 变更后完整离线回归：**12,284 passed / 26 skipped / 11 deselected / 40 warnings，593.12s**，exit=0。未运行项不计为通过；此前 12,224 项仅是变更前基线。
- 最终定向 **104 passed，86.21s**，覆盖新服务/API/SQLite 与独占 PostgreSQL 迁移、既有 owner 档案兼容；包含于全量，不与全量相加。两组纯领域测试另为 **15 / 58**，分别通过。Ruff 全目录 check 与 format **1,237 文件**通过。
- 整个 frontend Prettier 及本轮 root/backend/文档指南检查通过；没有前端运行源码改动，也没有重跑前端单测、浏览器或构建。此前前端证据保留为各自历史切片，不冒称本轮新结果。
- 运行/测试源码已逐项 SHA-256 核对，与实际回归快照一致；文档在回归后单独格式检查/同步。早期字段/严格类型/事件循环/迁移测试失败及后续修正日志均保留，不弱化断言或丢弃失败。

此结果属于未提交工作区的隔离后端候选，不是远端 CI、生产数据迁移、保留数据升级、真实模型/目标效果或用户最终验收。未知写入仍只能同 ID GET 对账，不能自动重发。合同见[独立档案范围](DevPilot_Independent_Report_Retest_Archives.md)，资源收尾另记在[Docker 运维](DevPilot_Docker_Diagnostics.md)。

本轮资源收尾已于 **2026-11-09 07:45（Asia/Shanghai）** 独立核验：19 份日志/JSON 导出并验 hash，2,484 份最终公开文件与快照一致后，精确清理本轮独占快照/四个辅助文件/已归档副本及宿主 staging；共享缓存和所有卷保留，三个本轮启动的 CI 已停止、Node 始终停止。全 14 容器的 ID/名称/镜像/状态/restart/OOM 签名恢复测试前状态，9 行镜像标签清单未变；无可安全删除的闲置 DevPilot 镜像，被引用的无标签镜像保留，镜像/容器/卷零删除。业务四服务 healthy、诊断 ok；不声称宿主 RAM 即时全部归还或 VHDX 已缩小。此后仅文档/ignored 证据更新，不算新一轮完整回归或部署。

### 2026-11-09：独立历史报告与复测选择 UI 门禁

Reports/Retests 新增独立区块：明确打开历史 assessment ID/修订/hash，complete 来源单独加入报告或 baseline/retest；不默认最新，不替换 owner 档案。同步页内待办 ID、写锁、迟到响应隔离及同 ID GET-only 对账涵盖未知写入与 404；固定历史纯文本、Markdown/JSON 下载，独立 Word/PDF 与正式批准仍未交付。

- 最终全量前端单测：**1,164 passed / 148 文件**。
- 生产构建、lint/typecheck 通过；完整模拟浏览器 **214 passed**，登录恢复 **2 passed**，均零自动重试。归档定向 12 / 4 项已包含在全量内，不叠加。
- 手机长按钮溢出修复后重新构建并全量复验；保留失败及通过日志。旧报告 capability GET 不等于 advisor POST，后者仍被禁止。
- 本轮后端未重跑；1,267 份 backend 非 Markdown 文件与前轮 12,284 passed 的源码 manifest 相同。候选 `eval_0012` 未部署；模拟浏览器不等于真实多账号/后端联调或最终验收。
- 按用户要求，完成模块并通过测试后提交/推送，按精确 SHA 核对 Actions；若仍运行，下一模块推送前先检查上轮并修复归因失败。成功推送不等于 CI 成功，不自动部署。

本轮 UI 资源收尾已于 **2026-11-09 08:50（Asia/Shanghai）** 独立核验：840 份公共源码/指南与快照逐项一致，34 份日志/JSON/artifact 先导出并验 hash，再精确清理本轮快照、八份临时辅助文件、结果副本及宿主 staging。只停止本轮启动的 Node CI，另三个 CI 全程停止；14 容器签名及9行镜像标签清单恢复原状，业务四服务 healthy、诊断 ok。共享缓存/卷/其他项目保留；镜像、容器、卷零删除，无安全可删的无引用 DevPilot 镜像。详情见[运维收据](DevPilot_Docker_Diagnostics.md)。收尾后仅文档更新和格式核验，不冒称重跑完整套件或已部署。
