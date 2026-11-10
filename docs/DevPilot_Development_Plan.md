# 开发接续分析与模块计划 / Development continuation plan

> 核对日期：2026-11-10。本计划记录代码/CI/运行的差别，不声称整个平台完成，也不以功能数估计完成百分比。

## 接手基线

- 本地/远端 `main`：`8890bd061f3407b8c187ceaf388dff28aa463b4e`；开始时工作区干净。
- 上一提交实际触发四项 Actions，均成功：Unit Tests `42573792483`、Frontend Unit Tests `42573792602`、Backend Blocking IO `42573792621`、Lint Check `42573792762`。未触发的 E2E 不是这次提交的 CI 成功证据。
- 本机只读 Docker 清单显示 `criteria-0fd689da83a4` 的 Gateway/Frontend 与 nginx/redis 正在运行且 healthy；这只是容器健康元数据，不是重新核验部署、数据库、账号、源文件或模型能力。本轮不操作它们。
- Python 3.12/Node 22 隔离环境由 Git 源码归档和冻结锁文件重新构建；不复制现有 venv、node_modules、私有配置、数据库或账号。测试专用 PostgreSQL/Redis 无业务挂载与宿主端口；后端测试阶段仅 internal 网络。

## 当前代码的实际能力

1. App/FastAPI 负责项目、冻结数据/请求/计划、授权、耐久 dispatch、有界 Worker、加密证据和审计；纯 `devpilot` 领域逻辑与 Harness 保持单向依赖边界。
2. 既有 owner 人工复核链已连接 verified summary、冻结标准、不可变报告/Word 与同基准复测，不等于独立批准。
3. 独立任务提供两名盲审人/第三名仲裁人，独立评估修订和历史报告/复测及显式工作区已进入候选代码。候选迁移 head `eval_0012`；历史部署收据是 `eval_0009`，不能因已拉取最新代码而认定新版已部署。
4. 本轮补齐独立历史报告/重测 Word 与 PDF 候选及合成独立主链回归；新增真实登录的合成多账号离线回归，仍不替代真实用户/浏览器联调；正式批准、保留数据升级/最终验收仍有缺口。旧设计文档里“待开发”的切片以当前交付矩阵为准，不重复重写已实现模块。

## 接续顺序与退出条件

| 模块               | 交付内容                                                                                   | 退出门禁                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 独立历史报告 Word  | 单独固定 renderer/GET、显式历史收据下载，不改旧 Word                                       | 后端回归/全量/阻塞检查，前端单测/完整格式/lint/typecheck/build/模拟浏览器；模块说明与独立提交，精确 SHA 的 Actions |
| 独立主链合成验收   | HTTP 冻结 v2 → 有界 Worker → 多角色独立任务 → 评估修订 → 历史报告/复测，隔离外网与真实模型 | 确定性正反例、全分母、不重试/不重发、历史不可变、授权与敏感数据边界；不替代真实账号验收                            |
| 剩余独立文档导出   | 复测 Word/PDF 的固定模板、可复现字体/布局及安全边界                                        | 先明确文档合同/运行依赖和历史兼容，再逐切片测试交付；不静默扩大已有 renderer                                       |
| 正式批准           | 单独授权角色、审批对象/版本、撤回/失效和审计合同                                           | 不把 PASS、完整性或阈值达标改名为批准；先核准政策与权限，不能用自动执行/owner 票冒充独立授权                       |
| 运行升级与用户验收 | 独立计划、备份/迁移/回滚、多账号桌面/手机只读和显式写入联调                                | 另行授权部署，保留账号/配置/数据/Harness ledger；没有真实模型/目标调用授权就不调用                                 |

每个模块完成后单独记录范围、命令/结果、未运行项、迁移/依赖、回退和排除项；只暂存本模块文件，提交、普通 push 并核验所有实际触发的 Actions。先修复可归因失败再推下一模块。不自动部署，不为测试生成生产 key 或开启执行。独立 CI 资源只在所有进程结束和证据导出验 hash 后按精确 ID 收尾。

## 本轮阶段结果（2026-11-09）

- 独立历史报告 Word 已提交并推送 `86c13930cd688b55722020da2b68b74bb61d25c7`，实际触发的六项 Actions 均成功；逐项 run ID 见 [交付矩阵](DevPilot_Delivery_Status.md)。
- 独立主链合成回归已实现 16 个参数化用例，本地标准后端 **12,339 passed**、领域 **15 / 58 passed**、Blocking IO **72 passed**，Ruff 和完整前端格式检查通过。它证明隔离合成链的边界，不是迁移部署或正式批准；已推送 `b1fe355c1c924b0a0073f154b7c25ee65f491e64`，实际触发的四项 Actions 均成功；逐项收据见交付矩阵。
- 独立复测 Word 单独固定 renderer/显式历史下载已通过本地门禁：定向 **148 passed**、标准后端 **12,384 passed**、领域 **15 / 58 passed**、Blocking IO **72 passed**；前端 **1,182 passed**、完整格式/lint/typecheck/build、模拟 Chromium **220 passed** 和认证恢复 **2 passed**。重测无 Markdown，导出存档公开比较事实，不能冒用报告格式；精确提交 `a3fb0db9de885a03e9883743216b5aca6c93665f` 六项 Actions 已核实成功（见下节）。该切片当时不含 PDF；正式批准政策、经授权的保留数据升级及真实多账号验收仍未完成，不能据此宣称整个平台完成。

## English summary

The clean continuation baseline is `8890bd061f3407b8c187ceaf388dff28aa463b4e`; its four triggered Actions succeeded. Existing QA execution/review/report flows and independent historical candidates are not a finished platform or a deployment of candidate migrations. Work proceeds in bounded modules: independent Word drafts, a synthetic independent lifecycle regression, remaining pinned exports, separately authorized approval, and explicitly approved deployment/acceptance. Each module requires scoped tests and relevant full gates, documentation, an independent commit/push and exact-SHA Actions verification. No private configuration, databases, real model/target calls, execution enablement or implicit deployment is permitted.

## 本轮接续：独立历史重测 Word 与 PDF

独立历史重测 Word 已在 GitHub 远端核实 `a3fb0db9de885a03e9883743216b5aca6c93665f`，六项 Actions 均 completed/success：Unit `42634173580`、Frontend Unit `42634173600`、Blocking IO `42634174621`、Lint `42634173290`、E2E `42634173439`、Replay `42634173556`。此前待推送回执由本次远端核验替代，不推断部署。

后续 [PDF 草稿](DevPilot_Independent_PDF_Drafts.md) 独立模块补齐固定字体历史报告/重测 PDF、权限/收据 GET、显式下载及合成回归；定向 **178 passed**、标准后端 **12,414 passed**、领域 **15 / 58 passed**、Blocking IO **72 passed**，前端 **1,206 passed**、完整格式/lint/typecheck/build、模拟 Chromium **226 passed** 和认证恢复 **2 passed**。固定字体两次重建同 SHA，uv 0.7.20/0.13.7 离线锁检查和所有旧包版本不变审计通过；详细限制见合同，实际提交/精确 SHA Actions 另记交付矩阵。旧 Word/档案/hash 和禁止真实调用、默认禁用执行的边界不变。正式批准政策/角色/生命周期不能由 `PASS`、`met` 或报告下载自动补全；经授权保留数据升级、真实多账号与最终验收仍单列待完成。

## 2026-11-10 接续：真实认证的离线多账号回归

PDF 候选已实际推送 `56c641637d3561f0fa4b5247da01c1549fc2d1d5`，精确 SHA 实际触发七项 Actions **全部 completed / success**：Unit Tests `42651605785`、Frontend Unit Tests `42651606003`、Backend Blocking IO `42651605741`、Lint Check `42651605792`、E2E Tests `42651605830`、Replay E2E `42651605934`、Skill Review CI `42651605943`。这是候选源码 CI，不是本机部署或正式批准。

下一测试切片见[真实认证回归](DevPilot_Authenticated_QA_Regression.md)：隔离数据库五个普通账号，真实密码登录/JWT/CSRF/RBAC，接入既有离线 Worker/独立任务/历史档案。不改变运行权力或启用执行；仍缺少另行授权的真实用户浏览器联调/保留数据部署和正式批准政策。

最终本地门禁：新增 18 项，联合定向 **63 passed**；标准后端 **12,432 passed / 18 skipped / 11 deselected**、纯领域 **15 / 58 passed**、Blocking IO **72 passed**；Ruff check/format **1,248 文件**、离线锁检查、完整 frontend Prettier 与六份模块 Markdown 检查通过。1,309 份实际后端/领域源码缺失/不符均为零。无前端运行源码变更，本模块没有重跑前端单测/build/浏览器，不以 PDF 提交的 CI 替代本次推送 SHA 的实际 Actions；最终统计、排除项与本机证据目录见交付矩阵。该测试补齐真实认证的离线主链，不等于真实用户、部署或正式批准。

## 2026-11-10 接续：执行占用只读诊断

真实认证回归已实际推送 `55cf3a80d3026f15b0e80399ab8fb9b52f032cc6`，四项实际 Actions 均 **completed / success**：Unit Tests `42659502653`、Frontend Unit Tests `42659502573`、Backend Blocking IO `42659502602`、Lint Check `42659502551`。该测试/文档提交未触发 E2E/Replay/Skill Review，不将未触发当成功；不是部署或真实用户验收。

下一候选为[执行占用只读诊断](DevPilot_Execution_Reservation_Diagnostics.md)，先补全局占用合计观察面，不发明失联进程已死亡的证据、不释放配额、不重发未知请求、不改变执行/调度授权。人类管理员与独立路由权限、一条 SELECT、不读敏感来源/不写状态；正式运维释放仍须独立 fencing/对账合同。本模块没有前端运行变更、迁移或依赖，完整后端/领域与格式门禁、精确 SHA Actions 单独核实。

本模块最终本地门禁：新增 22 项、联合定向 **82 passed / 1 warning**，完整后端 **12,454 passed / 18 skipped / 11 deselected**、纯领域 **15 / 58 passed**、Blocking IO **72 passed**；Ruff check/format **1,252 文件**、离线锁、完整 frontend Prettier 与七份 Markdown 检查通过。1,313 份后端/领域源码与 827 份前端格式快照均零缺失/不符；PostgreSQL 专属 TEMP 表六项合计兼容性通过，不是生产/迁移验收。首次授权固定清单失败已同步新权限的精确断言并完整重跑；无运行授权修改或重试掩盖。每次推送仍须自己的精确 SHA Actions；安全运维释放和平台其余 P1/P2 不因此完成。

## 2026-11-10 接续：管理员只读诊断工作区

上一后端模块已实际推送 `4f94b2c0a73a00a023fffafbcb06f01919c13b4c`，五项实际 Actions 全部成功，逐项 ID 见交付矩阵；E2E/Skill Review 未触发。本切片接续[只读工作区](DevPilot_Execution_Diagnostics_Workspace.md)，只把既有汇总安全地展示给显式加载的管理员，不扩大运维权力，不把 deadline 当进程死亡证据、不推断可释放槽位。

本模块另行执行完整前端/模拟浏览器和相关后端授权回归、文档/独立提交/精确 SHA CI。其后仍应先定义可证明的失联 Worker fencing/不重发对账合同，再讨论有授权的运维释放；调度准入、正式批准、真实多账号浏览器与保留数据升级仍有缺口，不能为了“完成”擅自启用执行或部署。

本模块最终本地功能回归：新增 56 项、完整前端 1,262 passed、Chromium 230 passed、认证恢复 2 passed；完整格式/lint/typecheck/build 及相关后端 82 / Blocking IO 72 / Ruff 通过。**性能预算未通过**：模块前精确提交同环境也失败，本轮仍有小幅资源增长；下一独立模块优先修复六条既有路由 CSS 及 docs/blog JS，不提高预算、不删除路由。完整平台、失联 Worker 安全运维与正式批准仍未完成。

## 当前接续：路由资源预算修复（2026-11-10）

管理员执行诊断 UI 已推送 `833897a367ea8ef0a1a030f4e1e93dc098caec11`，五项实际 Actions 全部成功（逐项 ID 见交付矩阵）；本地性能预算失败仍是该提交的真实记录。

接续[性能模块](DevPilot_Route_Resource_Budgets.md)保留原脚本、六路由和原阈值，解决文档导航过早导入工作台与动态 HTML palette 全局加载。最新原 gate 全部通过，docs/blog JS 约 4.44 MB → 1.01 MB，chat CSS 只有 609 bytes 余量；不是删除完整 lazy palette，也不等于交互或真实用户验收。新增 31 项回归和完整 frontend 1293 项通过；两种生产构建/完整浏览器/源码证据与实际 Actions 分开记录。

下一个功能模块仍须先定义 Lost Worker fencing/不重发的安全合同、冻结 QA 的独立调度准入或统一版本化可执行导出。正式批准需要明确政策/角色/撤回失效合同；部署、配置及真实外呼必须另行授权。不得以性能绿色或诊断观察当作释放、批准或全平台完成。

## 关闭生命周期安全补丁（2026-11-10）

性能模块 `6142029b921319e33c8819713f750ebbc3a497f9` 的五项实际 Actions 全部 completed/success（逐项 ID 见交付矩阵），原六路由本地预算亦通过，未借用上一提交结果。

继续分析安全 Lost Worker 操作之前，先实证修复[重复 Gateway 关闭取消](DevPilot_QA_Shutdown_Drain.md)：原 gather 会二次取消排空中的 Worker。先测旧代码 7 项失败，再只取消一次并 shield 同一等待器；新增 8 项，联合主链 82 项通过。原 Worker 排空前保留配额，硬崩溃仍不回收，不增加重发/释放能力。完整后端 12,462 / Blocking IO 72 / 前端 1,293 passed，Ruff/锁文件/完整格式通过；首轮隔离数据库未启动的失败保留并修正环境后原命令全量重跑。源码/证据和本提交实际 Actions 分别核对，不是安全自动恢复、正式批准或平台完成。

## 共享执行核心第一子模块（2026-11-10）

关闭排空模块已推送 `d7f61efe8dc17fe13e5cb464303a084d3fd9ed92`，四项 push Actions 均成功（Unit `42723748642`、Frontend Unit `42723748670`、Blocking IO `42723748656`、Lint `42723748676`）；同 SHA 的定时 Nightly `42725168993` 为 upstream-only skipped，不能记为通过。原始观察器因合并不同事件而报非全成功，保留原始 JSON，按 event 分类记录，不修改 CI 或把 skipped 改成 success。

本切片采用[共享响应核心](DevPilot_Shared_QA_JSON_Response_Core.md)，先提取纯版本化 JSON 响应 buffer/parser 并让 App 实际共用，验证边界和合成等价、独立解释器/真实 wheel，不复制第二套 runner。其余请求准备/执行适配器、导出数据授权、独立 CLI 出站/预算、结果隔离导入仍须后续独立模块；没有完整 exporter 就不开放导出能力。每次新推送仍须自己的实际 SHA CI，正式批准/运营 fencing/调度/部署边界不变。

本子模块最终验证：90 项新回归、291 项联合主链、49 场景旧版/当前实现对比；修复扩展对比发现的状态 600 兼容性差异后，完整后端 12,552、Blocking IO 72、前端 1,293 passed，Ruff/离线锁文件通过。纯源码与实际 wheel 均在无 site packages 的隔离解释器自检。首候选门禁通过不代替最终源码重跑；新 SHA 推送后仍独立等待实际 Actions，未运行的 build/browser/performance 不借用旧成绩。

## 共享请求准备核心（2026-11-10）

上一响应核心已推送 `e32cb3d81b64ed8f79411f22a049a3f0669c37e2`，四项 push Actions 实际成功：Unit `42731902942`、Frontend Unit `42731902497`、Blocking IO `42731902510`、Lint `42731902918`；未触发 E2E/Replay/Skill Review。证据、最终源码和资源收尾已核验，不推断部署。

本切片[请求准备核心](DevPilot_Shared_QA_JSON_Request_Core.md)冻结已有已渲染请求的 literal projection 与条件 identity policy，App 共用实现，保留原 body 编码时点与 64→65 headers 兼容边界。119 个旧/新实际 HTTPX 请求与响应场景全部等价，源码/真实 wheel 无 site packages 自检通过；新增 58 项回归，349 项联合主链通过；完整后端 12,610 passed、领域 15/58、Blocking IO 72、Ruff 1,254 files、离线锁及完整前端 1,293 项/格式通过。未重跑本地 build/浏览器/性能，实际新 SHA CI 继续独立核验。该子组件不读取数据/凭据、不发送，不提前开放导出；余下共享执行适配/出站/预算/结果隔离、失联 Worker fencing/对账、冻结 QA 调度、正式批准及授权部署仍未完成。

## 共享执行传输适配（2026-11-10）

请求核心 `ec9c37b262666a80e2083f472ae41b626d510ee1` 的四项实际 push Actions 全部成功：Unit `42737409116`、Frontend Unit `42737409596`、Blocking IO `42737409159`、Lint `42737409240`；源码/证据与四个专用资源收尾已核验。

本切片[共享 pinned HTTP](DevPilot_Shared_Pinned_HTTP_Core.md)继续提取实际传输而非复制第二套 runner：由显式 callback 保持 App 的动态 allowed_hosts/ALL DNS answers 策略，共用 origin/Host/SNI/TLS/不重试机制并拒绝会二次 DNS 的非 literal 返回。原授权、耐久派发、预算、未知结果及取消关闭不变，完整门禁和新 SHA CI 独立核验。完整执行/导出、CLI 约束与结果隔离导入、失联 Worker 安全对账、冻结 QA 调度、正式批准及授权升级仍未完成。

本模块本地最终门禁：新增 37 项；联合 443 / 后端全量 12,647 / 领域 15、58 / Blocking IO 72 / 前端 1,293 passed，Ruff 1,255 files、离线锁与完整格式通过。188 个实际旧/新传输对照和真实 wheel 隔离 mock-send 验证通过；源码/证据 hash、精确资源收尾和新 SHA 的 Actions 分别核验，不借用上一提交，也不宣称独立执行/导出或平台完成。

## 共享有界单次采集候选（2026-11-10）

共享 pinned HTTP 模块 `3b193d69007c097a71aad16135617775f09a6949` 的四项精确 SHA push Actions 均 completed/success：Unit `42743465228`、Frontend Unit `42743465248`、Blocking IO `42743465295`、Lint `42743465225`；源码/证据与四个专用资源收尾已核验。

接续[完整单次采集核心](DevPilot_Shared_QA_JSON_Attempt_Core.md)，共享现有 deadline/流生命周期/分类/观测与关闭，App 保留动态 client 政策、准入、耐久派发及预算。先前隔离审批超时/502 的两次命令未执行；后续经单独只读核验与显式启动审批恢复验证。已完成联合、全量后端/领域/前端和实际旧新对照/wheel 门禁；最终资源/提交/精确 SHA CI 另行核验，未借用上轮结果。不提前开放独立 runner/export；正式批准、lost-Worker 安全对账、冻结 QA 调度及授权升级仍未完成。

本模块本地最终门禁：新增 **44 passed**；联合 **487 passed**；后端全量 **12,691 passed / 18 skipped / 11 deselected / 40 warnings**；领域 **15 / 58 passed**；Blocking IO **72 passed**；后端 Ruff **1,256 files**、共享核心 lint/format 与离线锁通过；前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。399 个旧/新实际行为对照及实际 wheel 的隔离 mock-send 通过。最终源码/提交归档、证据 hash、精确资源收尾及新 SHA Actions 独立核验；本轮没有重跑本地前端 build/浏览器/性能，不借用历史结果，不部署/启用执行或调用真实模型/目标。

## 共享完整有界 run 编排（2026-11-10）

共享单次采集模块已推送 `5d070b3f4d000c09366bf0ac628c76a2fa6973ae`，该 SHA 四项 push Actions 实际 completed/success：Unit Tests `42750837938`、Frontend Unit Tests `42750837894`、Backend Blocking IO `42750837936`、Lint Check `42750837889`。E2E/Replay/Skill Review 未触发；46 份导出证据、1,370 Python/858 Node/文档源与提交归档核对通过，四个专用 CI 容器已停止，未部署。

接续[完整 run 核心](DevPilot_Shared_QA_JSON_Run_Core.md)，一次性提取原 Worker 的 ordinal/并发/monitor/deadline/unknown/关闭流程并让平台实际共用；不再以孤立 DTO 或下载按钮充当完整 exporter。App 数据库排空和最终释放、动态政策/准入/配额/加密证据不移动。先做旧实现失败和 barrier/真实 DB/实际 wheel 验证，再做完整门禁与独立提交/精确 SHA CI。

本模块本地最终门禁：新增 **62 passed**；最终联合 **549 passed**；完整后端 **12,753 passed / 18 skipped / 11 deselected / 40 warnings**，领域 **15 / 58 passed**，Blocking IO **72 passed**；后端 Ruff **1,257 files**、共享 run/attempt lint/format 与离线锁通过。前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。28 组旧/新真实 Worker 数据库/HTTP 行为逐字段对照及实际 wheel 完整 mock run 通过；静态 AST 另证原 DB-drain/serve、consumer/timeout/cleanup 保留。最终源码/提交归档、证据 hash、专用资源收尾及新 SHA Actions 分别核验。未重跑本地 frontend build/browser/performance，无部署、执行启用或真实模型/目标调用。下一阶段才讨论授权 exporter/manifest 的来源与数据交付合同、显式实发 CLI 和 external/unverified 结果隔离；不可隐式启用或部署。冻结 QA 的独立调度、Lost Worker fencing/不重发对账、正式批准和授权用户验收仍需独立模块，不因共用核心可 import 而完成。

## 独立本地 run 的耐久适配（2026-11-10）

共享完整 run 模块已推送 `f8cd909db191949a69e3fb04d0339a6bea6aae96`，该 SHA 四项 push Actions 实际 completed/success：Unit Tests `42756807606`、Frontend Unit Tests `42756807999`、Backend Blocking IO `42756807779`、Lint Check `42756807505`。47 份证据与 1,372 Python/858 Node/文档源和提交归档核验通过，四个专用 CI 容器已停止；E2E/Replay/Skill Review 未触发，未部署。

接续[本地 journal/实际共享核心适配](DevPilot_Local_QA_Run_Journal.md)，补齐独立运行的发送前耐久确认、未知不重发、累计字节预算及重复取消下全部 DB 读写排空，不新建第二套 runner，不提前开放 API/CLI。严格区分声明 source hash、实际请求值相等和平台 provenance；未来 manifest/数据交付授权/依赖 pin、动态出站与显式实发、敏感结果保存/隔离仍独立未完成。正式批准/冻结 QA 调度/lost Worker 对账/授权升级不因本地适配可运行而完成。本模块最终门禁、资源收尾与新 SHA Actions 独立核验。

本模块最终本地验证：新增 **79 passed**（最终源码复核 5.58s）；联合 **636 passed**（130.45s）；标准 `make test` **12,832 passed / 18 skipped / 11 deselected / 40 warnings**（756.54s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.57s）；Ruff **1,258 files**、新领域模块单独 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（11.4s），完整 Prettier 与七份模块文档格式独立核验。真实 sdist→wheel 的十个公开成员逐 bytes 相等，实际 wheel 在 `-I` 解释器中使用锁定 HTTPX 完整 mock run，禁止 business imports、真实 DNS/socket；不是无 site packages/零依赖或授权 exporter。联合开始后的最后源码编辑仅纠正文档字符串；最终新增回归、wheel 和完整后端均覆盖该最终源码。

本模块修复真实 WAL 读写/最后连接清理竞争，保留失败、实际 commit 后 ACK 丢失和硬进程退出证据；无事务 anchor 仅为连接生命周期，不授予恢复，全部 DB/任务/finish 排空后 close 撤销 claim。最终源码/证据/专用资源与新 SHA Actions 分开闭环。无本地 build/browser/performance 重跑或部署/真实调用。

## 显式独立本地命令（2026-11-10）

前序 journal 的远端 SHA `95ddbbacb3c051db471d877b8ec6227e47ef10b6` 已独立核对，实际四项 push Actions 全绿（Unit `42765155874`、Frontend `42765155959`、Blocking `42765156239`、Lint `42765155889`）；不把先前权限超时视为实际推送。

本模块新增[实际本地 execute-only 命令](DevPilot_Local_QA_Command.md)，而非再写一个 DTO 或第二套 runner。默认离线、分离显式 files、无环境凭据 fallback；实发需结构 fingerprint/输入/私有明文输出同意、host policy 和新私有目录。共享 collector/run/transport/journal 实际 mock sends 覆盖 dispatch-before-wire、完整冻结分母、一次性预算和未知不重发；DNS policy rejection 被记录后停止本地 run，不冒充未知交付，不更改 App 语义。文件/落盘失败、重复取消、创建期取消、隔离实际模块/wheel 属门禁；失败证据保留。

本命令是独立执行能力的前置模块，**不是**平台授权 exporter、锁定依赖交付或外部结果导入。下一步应明确导出来源/数据授权和依赖 pin、输出保密/结果隔离合同，再增加平台入口；不能把自建 manifest 或声明 hash 当作平台 provenance。正式批准/冻结 QA 调度/lost Worker 对账/授权升级继续独立规划。无真实模型/目标调用或部署。

本模块最终本地门禁：CLI 新增 **83 passed**，journal 专项 **82 passed**（含新增三项确定性锁回归），联合 **722 passed**（141.92s）；标准 `make test` **12,918 passed / 18 skipped / 11 deselected / 40 warnings**（761.90s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.72s）；Ruff **1,259 files**、两份领域源独立 lint/format、offline lock 全通过。前端完整 **152 files / 1,293 passed**（13.3s），完整 Prettier 与八份模块文档格式独立核验。实际 sdist→wheel 十二个公开成员逐 bytes 相等，`-I` 实际模块离线/完整 mock run 均通过，真实 DNS/socket 与 business imports 禁止。最终源码、证据、提交归档、专用资源收尾与新 SHA 的实际 Actions 另行闭环；未重跑本地 frontend build/browser/performance，无部署/执行启用/真实调用。
