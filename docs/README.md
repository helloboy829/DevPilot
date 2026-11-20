# DevPilot 文档导航

## 权威入口

- [当前交付状态](DevPilot_Delivery_Status.md)：源码、部署、验证、候选状态及当前主要缺口。
- [实现进度与下一步](DevPilot_实现进度与下一步.md)：模块级 backlog、依赖顺序、当前切片和开发记录。
- [功能实现说明与模块验收矩阵](DevPilot_Feature_Implementation_Spec.md)：功能到代码、API/数据、权限、状态、失败语义和验收用例的映射。
- [根开发指南](../AGENTS.md)、[后端开发指南](../backend/AGENTS.md)、[前端开发指南](../frontend/AGENTS.md)：仓库边界、实施要求和验证命令。

当前状态只在 Delivery Status 维护，功能实现和未完成路线只在实现进度维护。历史成功/失败/迁移/部署收据留在 Delivery History 或明确标注的归档；不得从旧通过数推断当前代码、CI、部署或用户验收。

## 产品与领域合同

- [需求分析](DevPilot_需求分析.md)、[业务流程与迭代计划](DevPilot_业务流程与迭代计划.md)、[系统架构](DevPilot_系统架构设计.md)、[可行性分析](DevPilot_可行性分析.md)。
- [数据集与指标规范](DevPilot_数据集与指标规范.md)：用例/reference、分母、效果结论和适用性。
- [评测数据构建与执行工作流](DevPilot_评测数据构建工作流.md)：项目外材料批次、逐组件候选、归档/审核/冻结及无 expected 执行。
- [效果测试工作台](DevPilot_效果测试工作台设计.md)：结果 DTO、敏感证据访问、逐条效果浏览与开发切片。
- [AI 性能测试工作台](DevPilot_AI性能测试工作台设计.md)：profile、循环负载、停止/排空、指标证据与外部工具评估。
- [前端交互设计](DevPilot_前端交互设计.md)、[工作台交付范围](DevPilot_Evaluation_Workspace.md)、[材料与模板规范](DevPilot_材料与模板规范.md)。

## 技术合同

- [API 接口设计](DevPilot_API接口设计文档.md)、[数据库详细设计](DevPilot_数据库详细设计.md)、[QA JSON Binding](DevPilot_QA_JSON_Binding.md)、[共享 QA 核心](DevPilot_Shared_QA_JSON_Run_Core.md)。
- [LangGraph 工程设计](DevPilot_LangGraph工程设计文档.md)、[RAG 知识库与数据架构](DevPilot_RAG知识库与数据架构设计文档.md)、[技术依据与决策记录](DevPilot_技术依据与决策记录.md)。
- 逐领域复核、评估、签核、报告、复测、导出和运行安全约束，见相应 `DevPilot_*.md` 合同；细节索引见功能实现说明，不重复复制 API/schema。

## 验收与历史证据

- [测试方案](DevPilot_测试方案.md)、[候选验收包](DevPilot_Acceptance_Package.md)、[全民审核与 Linux 验收](DevPilot_Equal_Review_and_Linux_Acceptance.md)、[Windows 验收 Runbook](DevPilot_Windows_Acceptance.md)。
- [交付历史](DevPilot_Delivery_History.md)：按时间保存提交 SHA、测试结果、部署、迁移与失败记录。
- `docs/reviews/` 保存审计/复盘，`docs/upstream/` 保存上游材料；它们是证据或来源，不是当前需求/实现状态。
- [文档导航旧快照](DevPilot_Documentation_Archive_2026-11.md)、[旧开发接手记录](DevPilot_Development_Notes_Archive_2026-11.md)、[旧实现切片日志](DevPilot_Implementation_Slices_Archive_2026-11.md)是历史归档。[旧开发计划入口](DevPilot_Development_Plan.md)只转向当前账本，不作为计划源；过期排期见 `DevPilot_Sprint_Plan.md`，不作为当前 backlog。

## 文档维护规则

- 新增功能先确定一个领域合同 owner；架构/API/数据库/交互文档只写跨域摘要并链接 owner 文档。
- 只保留一份当前状态、一份模块开发进度；日期记录可保留，但必须标出只适用的提交/轮次。
- 代码、测试、部署和候选验证分别记录；失败、skip、定向复测和未知状态都保留原始范围。
- 已替代合同不删除：加 `superseded-by` 与旧版本适用范围，旧数据/证据保持可追溯。

## 合同 Owner

| 合同范围 | 权威文档 | 其他文档的职责 |
| --- | --- | --- |
| 当前源码/部署/验证事实 | [交付状态](DevPilot_Delivery_Status.md) | 交付历史保存逐轮收据；进度账本只引用结论，不复制收据。 |
| 模块 backlog、依赖与开发记录 | [实现进度与下一步](DevPilot_实现进度与下一步.md) | 功能矩阵列验收切片，不维护第二份进度状态。 |
| 功能到代码/测试的索引 | [功能实现说明](DevPilot_Feature_Implementation_Spec.md) | 领域合同拥有行为、schema 和权限细节；矩阵不得另立冲突定义。 |
| API 路由、通用协议、错误与兼容行为 | [API 接口设计](DevPilot_API接口设计文档.md) | 领域 owner 文档拥有本域资源 DTO 和业务语义；API 文档维护路由映射与通用 wire 约定，不复制领域字段表。目标 API 必须标注待开发。 |
| 持久化 schema 与迁移约束 | [数据库详细设计](DevPilot_数据库详细设计.md) | 领域合同说明状态转换和不变量，不复制完整表定义。 |
| 数据集质量、reference 与指标分母 | [数据集与指标规范](DevPilot_数据集与指标规范.md) | 数据构建工作流引用其质量/指标判定；模板规范只拥有交换文件格式。 |
| 项目外材料到冻结评测数据的流程 | [评测数据构建工作流](DevPilot_评测数据构建工作流.md) | 材料与模板规范定义输入/输出文件格式，不重复审批状态机。 |
| 不可变 RequestSpec 版本、凭据隔离与请求版本访问 | [请求定义版本](DevPilot_Request_Versions.md) | API 文档只维护路由映射和通用协议；模型连接/调试文档不得把连接成功当成冻结执行授权。 |
| QA 执行授权、占用与未知 Worker 安全 | [执行安全合同](DevPilot_Execution_Safety_Contract.md)、[耐久派发日志](DevPilot_Durable_Dispatch_Journal.md) | 授权、派发、观察、排空和未知结果分别建模；deadline 不证明 Worker 已停止，诊断接口不授予处置权限。 |
| QA 调度准入与调度器边界 | [调度准入诊断](DevPilot_Scheduling_Admission.md)、[已准入 QA 执行](DevPilot_Admitted_QA_Execution.md) | legacy component-test scheduler 不作为 QA 主链；共享编排核心不接管 App 授权、持久化和耐久边界。 |
| 版本化 QA JSON 请求、attempt、response 与有限 run 核心 | [共享 QA JSON 核心](DevPilot_Shared_QA_JSON_Run_Core.md)及同目录下 Request/Attempt/Response 合同 | 纯核心负责确定性协议与有界编排；平台、本地适配器分别拥有授权、配额、密钥、存储和耐久回执。 |
| 已采集 QA 输出、技术观测与 owner 自复核 | [加密输出证据与人工复核](DevPilot_QA_Evidence_Review.md) | 人工复核工作台只定义跨页面体验目标；独立任务另有窄授权合同，不覆盖 owner 自复核。 |
| 独立逐条双盲复核任务与仲裁 | [独立逐条人工复核](DevPilot_Independent_Case_Review.md) | 人工复核工作台定义更广的产品目标；当前资源、角色、状态和访问约束以本合同为准。 |
| 正式评估签核请求与本人签署 | [正式批准首切片](DevPilot_Formal_Approval.md) | [全民审核与 Linux 验收](DevPilot_Equal_Review_and_Linux_Acceptance.md)维护全局成员/审核规则；逐条独立复核不构成正式批准。 |
| 效果运行结果、逐条浏览与证据访问 | [效果测试工作台](DevPilot_效果测试工作台设计.md) | 效果工作台合同拥有领域 DTO 与证据语义；API 文档维护路由/通用协议；前端交互文档只维护跨功能视觉与交互约定。 |
| 性能 profile、负载、指标和外部工具适配 | [AI 性能测试工作台](DevPilot_AI性能测试工作台设计.md) | 性能工作台合同拥有领域 DTO、指标适用性与负载语义；API 文档维护路由/通用协议；技术依据记录只链接选型结论。 |
| 本地 QA 命令、隔离输出、保留与处置 | [本地 QA 命令](DevPilot_Local_QA_Command.md)、[本地输出保护](DevPilot_Local_QA_Protected_Output.md)、[本地输出保留命令](DevPilot_Local_QA_Retention_Commands.md) | 本地适配器复用版本化 QA 核心，但授权、密钥、耐久回执和处置独立于平台；历史 run journal 仅保留逐轮证据。 |
| 外部 QA 技术声明隔离与授权导入/导出 | [外部 QA 隔离接收](DevPilot_External_QA_Quarantine.md)、[授权 QA 导出](DevPilot_Authorized_QA_Exports.md) | 技术元数据隔离声明不是外部运行结果导入，也不构成平台验证、执行或批准；API 文档维护路由摘要。 |
| 报告事实来源、模板快照、修订和草稿 | [报告模块设计](DevPilot_报告模块设计.md) | 报告 owner 定义事实/来源和修订语义；API 文档维护路由；模板文件只定义交换/渲染输入格式。 |
| 导出文件与报告模板格式 | [材料与模板规范](DevPilot_材料与模板规范.md) | 不拥有审核或执行状态机；实际报告事实及修订规则由报告合同维护。 |
| 跨服务组件职责与依赖方向 | [系统架构设计](DevPilot_系统架构设计.md) | 领域设计可细化本域内部组件，不反向定义跨服务依赖。 |

发现重复描述时保留各文档对自身范围必要的摘要，但只在 owner 文档修改规范性定义；旧合同、归档和交付历史不因内容相似而删除。
