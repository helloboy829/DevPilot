# DevPilot 文档导航与设计基线

[只读 Docker 诊断](DevPilot_Docker_Diagnostics.md)：有界元数据检查，区分 Docker 无响应、应用状态与磁盘风险；不自动重启、不读取日志/凭据或修改数据。

- [同基准整改复测 / Same-benchmark retesting](DevPilot_Same_Benchmark_Retesting.md)：不可变逐条变化档案、固定分母与按需前后 Q/A；不是正式验收。

## 当前本地状态：已备份更新（2026-11-08）

[Docker 恢复与保留数据升级](DevPilot_Local_Recovery_and_Upgrade.md)：普通重启超时后，经授权官方 force-stop/start 恢复；在线一致性备份后仅更新 gateway/frontend 至功能提交 `59ab6304cd842af3e5222a17dfb41a10d7d52894`，App head `eval_0008`。账号、旧记录、配置和挂载已核验保留；所有既有账号的助手界面只读冒烟通过。没有配置模型、密钥或启用真实评测外呼。下面早期“待恢复/未部署”的段落属于历史切片，不是当前状态。

## 当前：冻结 Word 草稿导出（2026-11-08）

[Word 草稿导出](DevPilot_QA_Word_Draft_Export.md)从历史存档生成真实多组件 DOCX，固定 renderer、模板版本和事实，不重新调用模型/目标、不批准。App head 不变；Docker 重启后已恢复，应用升级需备份和独立核验。存档提交 13ace1d 六项 Actions 均已通过，Word 改动须另核验新 SHA。

## 当前：不可变平台 QA 报告草稿（2026-11-08）

[多组件报告存档](DevPilot_Immutable_QA_Report_Archives.md)追加服务端已验证指标引用、完整模板版本/布局冻结和不覆盖历史的修订。人工填报与 Agent 建议不混入实测事实，全部仍为未批准草稿。代码 head 为 eval_0008，本地最后核验仍为 eval_0006；Docker 管理 API 无响应，未更改账号、配置或数据卷。下节是前一切片的历史说明。

## 当前：独立执行与已验证人工汇总（2026-11-08）

[独立授权执行](DevPilot_Admitted_QA_Execution.md)将冻结计划、有界 Worker、加密输出和复核接通，默认不启用运营外呼；执行提交 `0e56c3b60216350c3f598414b8b4eb02d842494a` 六项 Actions 已通过。[固定分母汇总](DevPilot_Verified_QA_Summaries.md)按全部冻结效果样本与最新人工决策给出已验证预览，不是已批准报告。代码 head 为 eval_0007，本地最后核验仍为 eval_0006，Docker 恢复并完成保留数据升级前不算部署。下面的条目保留各历史切片原有范围，由本节说明当前连接状态。


## 当前追加：加密输出证据与人工复核（2026-11-08）

[逐条证据与复核切片](DevPilot_QA_Evidence_Review.md)增加内部加密输出与技术观测的原子存储、Q/A/预期/来源同屏、人工三态结论及修订历史；App head 为 eval_0006。仅项目 owner 自复核，缺证据不能通过，计数不冒充准确率。没有新增执行入口、目标调用或 Worker；冻结定义仍不是执行批准。

## 当前追加：耐久派发日志（2026-11-08）

[技术派发日志](DevPilot_Durable_Dispatch_Journal.md)实现不可重派序号、同事务预算预留、票据防篡改、未知写入和过期整次中断；该切片引入 eval_0005（当前 head 为 eval_0006）。没有新增执行 API、Worker、输出证据或质量判决，后续先补独立准入再接采集器。


## 当前追加：有界单次采集内核（2026-11-08）

[内部单次 QA 响应采集](DevPilot_Bounded_QA_Attempts.md)实现单次发送、响应/超时边界、取消清理和未知派发不重试。无运行 API、Worker、判分或持久证据，不把采集成功当作效果 PASS。

## 当前追加：请求版本与冻结 QA 计划（2026-11-08）

[加密请求版本界面](DevPilot_Request_Version_UI.md)支持从 cURL 调试器明确保存及浏览元数据；[QA 计划后端](DevPilot_Frozen_QA_Plans.md)与[确认界面](DevPilot_Frozen_QA_Plan_UI.md)固定请求/数据版本、JSON 映射和有限参数。当前仅冻结定义与逐输入预检，不是执行授权、运行结果或报告证据。

## 当前追加：项目组件与不可变提测清单（2026-11-07）

[项目组件与提测清单](DevPilot_项目组件与提测清单.md)记录已实现的 owner 组件关联、冻结 QA 版本绑定、服务端库存快照和 App 迁移 eval_0002。不是可执行方案、验收通过或报告证据；旧文档“尚无组件关联”仅代表上一轮。

## 本轮实现状态（2026-11-07）

[实现进度与下一步](DevPilot_实现进度与下一步.md)：评测优先首页、模型四协议连接、报告有界多轮与[项目/QA数据最小闭环](DevPilot_QA数据最小闭环.md)已落地；完整数据治理/结果复核/耐久执行/正式报告仍待开发。该矩阵是目标路线图与当前代码之间的校准入口。

## 报告 Agent 增补（2026-11-07）

已新增默认关闭的受限报告 Agent：显式授权、汇总指标 allowlist、复用模型工厂/无工具 LangGraph、人工确认附录与输入变更失效。未配模型仍可人工报告；不代表整个评测 Agent 闭环已完成。

## 报告模块增补（2026-11-07）

[报告模块设计与实施边界](DevPilot_报告模块设计.md)：已实现人工填报、计数/指标校验、指定模板版本草稿及 Markdown/JSON 下载；未实现持久历史、模板管理、正式审批、Word/PDF 或平台结果引用。该实现不代表 I0 全部门禁已退出。


> 基线日期：2026-11-06。定位：**AI 组件评测工作台 + 自动化评测 Agent**。
> 2026-11-06 建立文档基线，2026-11-07 开始 I0 首批核心判定修复（见现状审计）；不代表运行时代码已实现全部目标方案。旧版“通用研发 SaaS / 九 Agent / Milvus 必选”设计由新版取代，历史可通过 Git 查询。

## 2026-11-07 增补

- [历史材料分析与设计校准](DevPilot_历史材料分析与设计校准.md)：授权历史材料的脱敏结论、摸底/验收和数据/评分口径。
- [CI 修复与隔离开发环境](DevPilot_CI修复与隔离开发环境.md)：真实失败原因、可复现命令及验证范围。

## 阅读顺序与事实来源

1. [可行性分析](DevPilot_可行性分析.md)：可行条件、范围和投入边界。
2. [现状审计与修复清单](DevPilot_现状审计与修复清单.md)：代码证据、已复现问题与环境限制。
3. [需求分析](DevPilot_需求分析.md) → [业务流程与迭代计划](DevPilot_业务流程与迭代计划.md)。
4. [数据集与指标规范](DevPilot_数据集与指标规范.md)：数据质量、分母和判定的唯一规范。
5. [系统架构](DevPilot_系统架构设计.md) → [DeerFlow 改造方案](DevPilot_基于DeerFlow的改造方案.md)。
6. [前端交互设计](DevPilot_前端交互设计.md) → [接口调试与脚本导出](DevPilot_接口调试与脚本导出设计.md) → [人工复核工作台](DevPilot_人工复核工作台设计.md) → [材料与模板规范](DevPilot_材料与模板规范.md)。
7. 详细设计：[LangGraph](DevPilot_LangGraph工程设计文档.md)、[Prompt](DevPilot_Prompt工程设计文档.md)、[API](DevPilot_API接口设计文档.md)、[实时通信](DevPilot_实时通信协议设计.md)、[数据库](DevPilot_数据库详细设计.md)、[知识库](DevPilot_RAG知识库与数据架构设计文档.md)。
8. 交付保障：[测试方案](DevPilot_测试方案.md)、[部署运维](DevPilot_部署与运维设计.md)。
9. [技术依据与决策](DevPilot_技术依据与决策记录.md)。

事实优先级：已验证代码/测试优于现状描述；目标契约以数据与指标、API、数据库设计为准。发生冲突应修改文档和契约，不能让模型临场解释。

## 状态标记

- **已存在**：找到代码，不等于完整验收。
- **已复现**：本地最小用例已观察到问题。
- **静态发现**：代码推导，尚未运行对应服务或构建。
- **目标设计 / 待开发**：不可当作当前可用能力。
- **已验证**：须附环境、命令、结果与范围；纯单元测试不能写成端到端验收。

## 不变的产品决策

- 数据质量、证据和复现优先，不追求 Agent 数量。
- Agent 辅助规划、生成和解释；确定性程序负责执行、计数、阈值与状态流转。
- 首版受控内部部署，不做计费型 SaaS；保留用户隔离，团队共享需单独授权设计。
- 不新增第二套通用 Agent Runtime；复用 DeerFlow，新增领域业务和有界 Worker。
- 参考答案/验收集不能进入目标提示词或不受控的聊天记忆。
- 缺失必要证据不得自动 PASS。
- 一份 RequestSpec/执行核心连接调试、平台评测与可选独立脚本导出；不让 LLM 临场生成两套统计逻辑。
- 独立人工复核中心与结果页共享任务；人工决定、自动裁判与原始观测分层，不改写原始证据。

## 维护规则

只维护中文、英文项目文档；保留中文 DevPilot 入口与中英上游参考，不保留日/法/俄项目 README。此约定不限制被测材料、数据或 UI 支持的语言，也不删除开源许可/版权。frontend/public/demo 的历史对话快照包含旧上游 README 文本/路径，保留原貌，不作为现行文档入口或当前能力依据。

开发同时更新测试与相关文档；PR 标明完成/未完成、迁移影响、回退办法。里程碑仅随验收证据更新，不因日期到达自动完成。[templates/](templates/) 是目标格式示例，接口实现前不能直接上传执行。

## Current implementation update

See [DevPilot evaluation workspace delivery and configuration](DevPilot_Evaluation_Workspace.md) for the implemented cURL debugger, off-peak evaluation scheduling, multi-component drafts, opt-in field-intake agent and administrator model catalog. This update supersedes older “planned only” statements for those specific slices, not the remaining lifecycle roadmap.

## 导航与执行安全补充

- [导航与统一出站基线](DevPilot_导航与统一出站基线.md)：单一组件入口、可选自定义助手及调试/手动/定时统一出站策略；不代表完整评测流水线。
