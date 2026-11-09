# 开发接续分析与模块计划 / Development continuation plan

> 核对日期：2026-11-09。本计划记录代码/CI/运行的差别，不声称整个平台完成，也不以功能数估计完成百分比。

## 接手基线

- 本地/远端 `main`：`8890bd061f3407b8c187ceaf388dff28aa463b4e`；开始时工作区干净。
- 上一提交实际触发四项 Actions，均成功：Unit Tests `42573792483`、Frontend Unit Tests `42573792602`、Backend Blocking IO `42573792621`、Lint Check `42573792762`。未触发的 E2E 不是这次提交的 CI 成功证据。
- 本机只读 Docker 清单显示 `criteria-0fd689da83a4` 的 Gateway/Frontend 与 nginx/redis 正在运行且 healthy；这只是容器健康元数据，不是重新核验部署、数据库、账号、源文件或模型能力。本轮不操作它们。
- Python 3.12/Node 22 隔离环境由 Git 源码归档和冻结锁文件重新构建；不复制现有 venv、node_modules、私有配置、数据库或账号。测试专用 PostgreSQL/Redis 无业务挂载与宿主端口；后端测试阶段仅 internal 网络。

## 当前代码的实际能力

1. App/FastAPI 负责项目、冻结数据/请求/计划、授权、耐久 dispatch、有界 Worker、加密证据和审计；纯 `devpilot` 领域逻辑与 Harness 保持单向依赖边界。
2. 既有 owner 人工复核链已连接 verified summary、冻结标准、不可变报告/Word 与同基准复测，不等于独立批准。
3. 独立任务提供两名盲审人/第三名仲裁人，独立评估修订和历史报告/复测及显式工作区已进入候选代码。候选迁移 head `eval_0012`；历史部署收据是 `eval_0009`，不能因已拉取最新代码而认定新版已部署。
4. 本轮补齐独立历史报告 Word 候选；独立复测 Word/PDF、正式批准、真实多账号联调、保留数据升级/最终验收仍有缺口。旧设计文档里“待开发”的切片以当前交付矩阵为准，不重复重写已实现模块。

## 接续顺序与退出条件

| 模块               | 交付内容                                                                                   | 退出门禁                                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 独立历史报告 Word  | 单独固定 renderer/GET、显式历史收据下载，不改旧 Word                                       | 后端回归/全量/阻塞检查，前端单测/完整格式/lint/typecheck/build/模拟浏览器；模块说明与独立提交，精确 SHA 的 Actions |
| 独立主链合成验收   | HTTP 冻结 v2 → 有界 Worker → 多角色独立任务 → 评估修订 → 历史报告/复测，隔离外网与真实模型 | 确定性正反例、全分母、不重试/不重发、历史不可变、授权与敏感数据边界；不替代真实账号验收                            |
| 剩余独立文档导出   | 复测 Word/PDF 的固定模板、可复现字体/布局及安全边界                                        | 先明确文档合同/运行依赖和历史兼容，再逐切片测试交付；不静默扩大已有 renderer                                       |
| 正式批准           | 单独授权角色、审批对象/版本、撤回/失效和审计合同                                           | 不把 PASS、完整性或阈值达标改名为批准；先核准政策与权限，不能用自动执行/owner 票冒充独立授权                       |
| 运行升级与用户验收 | 独立计划、备份/迁移/回滚、多账号桌面/手机只读和显式写入联调                                | 另行授权部署，保留账号/配置/数据/Harness ledger；没有真实模型/目标调用授权就不调用                                 |

每个模块完成后单独记录范围、命令/结果、未运行项、迁移/依赖、回退和排除项；只暂存本模块文件，提交、普通 push 并核验所有实际触发的 Actions。先修复可归因失败再推下一模块。不自动部署，不为测试生成生产 key 或开启执行。独立 CI 资源只在所有进程结束和证据导出验 hash 后按精确 ID 收尾。

## English summary

The clean continuation baseline is `8890bd061f3407b8c187ceaf388dff28aa463b4e`; its four triggered Actions succeeded. Existing QA execution/review/report flows and independent historical candidates are not a finished platform or a deployment of candidate migrations. Work proceeds in bounded modules: independent Word drafts, a synthetic independent lifecycle regression, remaining pinned exports, separately authorized approval, and explicitly approved deployment/acceptance. Each module requires scoped tests and relevant full gates, documentation, an independent commit/push and exact-SHA Actions verification. No private configuration, databases, real model/target calls, execution enablement or implicit deployment is permitted.
