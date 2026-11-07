# DevPilot

## 报告工作台（2026-11-07）

侧栏 **报告**（`/workspace/reports`）支持填写组件/版本、效果与性能结果、统计口径和证据说明，按内置中/英文**指定版本模板**生成草稿，下载 Markdown 或包含事实/模板快照的 JSON。修改输入或模板后，旧预览与下载会失效。效果通过率固定为通过数/总数；缺测不补零，非流式不能填 TTFT。

本版是**人工填报、未经核验的 DRAFT**，不输出自动验收结论，**不会在服务端保存报告**；请离开页面前下载。已实现版本固定和快照，不代表已有模板编辑、历史修订库、正式审批或 Word/PDF 导出。后续模板更新应新建版本，不覆盖旧版报告。[模块设计与边界](docs/DevPilot_报告模块设计.md)。


**AI 组件评测工作台 + 自动化评测 Agent**，基于 DeerFlow 二次开发，服务于 AI 模型、CV、LLM 和 Agent 的效果/性能评测。

> 2026-11-06 状态：仓库已有 DeerFlow 底座与初版组件测试工具，**尚不是可无人值守正式验收的完整产品**。本轮更新产品/技术文档，未实现规划中的新 API、UI、数据治理和知识闭环。

## 2026-11-07 材料与工程校准

已本地只读分析授权的历史材料，结论见[脱敏材料分析](docs/DevPilot_历史材料分析与设计校准.md)。目标设计新增摸底 BASELINE/验收 ACCEPTANCE 区分；无金标、无批准标准不得自动给效果验收 PASS，二值通过率与加权评分分开。仓库/包名保留 DevPilot，面向用户使用“DevPilot · AI 组件评测工作台”；以上并非新业务 API 已完成。

开发验证使用独立 Docker 环境（Python 3.12、Node 22），不改 Conda base；参见[CI 修复与环境说明](docs/DevPilot_CI修复与隔离开发环境.md)。生产 Docker 打包问题仍需单独验收。

## 核心业务流程

提测清单/cURL/样例与参考源 → 接口调试与接入确认 → 高质量数据构建与审核 → 冻结方案 → 平台直接执行效果 + 性能（可选导出独立测试工程） → 人工复核与判定 → 整改复测或报告审批 → 审核后知识沉淀。

- **数据优先**：历史真实数据为基础，受控合成补覆盖；来源/授权、标签、切片、去重、防泄漏、盲测和质量卡。
- **判定可信**：效果通过率以冻结总数为分母；错误/待审/未执行单列；缺必要指标不得 PASS。
- **性能可比**：按任务测延迟/QPS/TPS；仅启用且可观测文本内容增量的流式调用测客户端 TTFT。固定负载、token 来源与时间窗口，缺失/不适用不记 0。
- **调试到评测**：目标调试台支持人/Agent 共用请求规范，确认后平台直接跑；独立 Python 测试工程由同版本核心生成，尚未实现。
- **人工复核**：目标为独立待办中心 + 结果页内嵌，对照输入/输出/预期/来源；决定可修订，原始证据不可改。
- **有界自动化**：Agent 辅助规划/生成/解释，确定性 Worker 执行和计数，审批与预算由服务端强制。
- **持续优化**：审核案例、规则和 Prompt 后版本化推广，不自动训练，也不让验收答案污染知识。

## 实际开发状态

| 能力 | 当前状态 |
| --- | --- |
| Gateway、认证、LangGraph、模型/工具/沙箱/聊天 | 底座代码已存在，本机未完成全栈运行验证 |
| 组件 CRUD、四类 transport、基础 effect/perf、JSON 报告 | 已有初版；首批核心判定回归已修复，安全/恢复、能力验证和部署仍有缺口 |
| 提测/数据质量/审批/冻结/整改/正式模板报告/知识体系 | 新版目标方案，尚待分期实现 |
| 接口调试台、独立脚本导出、人工复核中心 | 详细设计已更新，尚无对应完整实现，不是当前可用功能 |
| 评测 UI / DeerFlow 非核心功能裁剪 | 新增报告草稿入口；评测中心整体改造与裁剪仍为设计，未删除底座模块 |
| 自定义纯单元测试 | 73 项通过（15 legacy evaluation + 58 toolkit），非端到端验收 |

不再以旧“通用研发 SaaS、九 Agent、Milvus 必选、五个已交付研发 Skills”描述当前产品。

2026-11-07 首批修复：新增主通过率 `pass_rate = passed / total` 与 `not_run`；待审/未执行不能放行；无成功请求或必需性能指标缺失/覆盖不全不能 PASS。新报告带 `assessment_version=component-test.i0.v1`，保留历史报告，不把旧 PASS 自动升级为新版结论。当前仍用原型的 PASS/FAIL/REVIEW 状态，并未实现目标生命周期或正式人工复核模块。具体范围与未完成项见[审计清单](docs/DevPilot_现状审计与修复清单.md)。

## 文档入口

- [文档总索引](docs/README.md)
- [可行性分析](docs/DevPilot_可行性分析.md)、[需求](docs/DevPilot_需求分析.md)、[现状审计/修复](docs/DevPilot_现状审计与修复清单.md)
- [业务流程与迭代](docs/DevPilot_业务流程与迭代计划.md)、[数据集与指标](docs/DevPilot_数据集与指标规范.md)
- [系统架构](docs/DevPilot_系统架构设计.md)、[DeerFlow 改造](docs/DevPilot_基于DeerFlow的改造方案.md)、[评测 UI](docs/DevPilot_前端交互设计.md)
- [接口调试与脚本导出](docs/DevPilot_接口调试与脚本导出设计.md)、[人工复核工作台](docs/DevPilot_人工复核工作台设计.md)
- [材料/模板](docs/DevPilot_材料与模板规范.md)、[技术依据/决策](docs/DevPilot_技术依据与决策记录.md)

## 仓库边界

~~~text
backend/app/                      Gateway 与业务服务
backend/packages/harness/         DeerFlow 通用 Agent 底座
backend/packages/extension-api/   通用扩展契约
frontend/                         Next.js UI（当前仍以聊天为主）
devpilot/src/devpilot/toolkit/    初版效果/性能工具
devpilot/src/devpilot/evaluation/ legacy 编码任务七字段评分
docs/                            新版领域方案、审计与模板
~~~

App → Harness / devpilot；不得让 Harness 反向依赖业务层。开发规则见 [AGENTS.md](AGENTS.md)、[backend/AGENTS.md](backend/AGENTS.md)、[frontend/AGENTS.md](frontend/AGENTS.md)。

## 环境与启动说明

依赖 Python 3.12+、uv、Node.js 22+、项目锁定 pnpm；安装见 [Install.md](Install.md)，底座使用说明见 [README_upstream.md](README_upstream.md)。保留[中文上游参考](README_zh.md)与英文上游参考，项目文档只维护中英文；它们介绍底座，不代表 DevPilot 领域功能已实现。

配置文件从根目录 example 复制，密钥不入 Git；完整环境下根 make dev 启全栈，make up 为 Docker。**当前 devpilot 本地依赖的 Docker 打包缺陷须先修复，不能把命令存在当成构建已验证。** 统一入口默认 loopback:2026。

host 前端命令经 runner：

~~~powershell
python scripts/pnpm.py check
python scripts/pnpm.py test
~~~

## 推荐实施顺序

可信度/安全/部署修复 → 接口调试与历史问答平台闭环 → 已验证适配器脚本导出 → 数据构建/审核 → CV 与真实报告模板 → 知识推广/复测增强 → 深度 Agent 自动化。

欢迎先提供脱敏提测模板、QA/CV 各一代表项目、历史标签/报告、合法参考源、负载与验收要求；用于校准数据和规则，不直接无差别喂给外部模型。
