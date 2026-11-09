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
4. 本轮补齐独立历史报告/重测 Word 与 PDF 候选及合成独立主链回归；正式批准、真实多账号联调、保留数据升级/最终验收仍有缺口。旧设计文档里“待开发”的切片以当前交付矩阵为准，不重复重写已实现模块。

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
