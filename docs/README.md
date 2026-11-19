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
- [文档导航旧快照](DevPilot_Documentation_Archive_2026-11.md)、[旧开发接手记录](DevPilot_Development_Notes_Archive_2026-11.md)、[旧实现切片日志](DevPilot_Implementation_Slices_Archive_2026-11.md)是历史归档。过期排期见 `DevPilot_Sprint_Plan.md`，不作为当前 backlog。

## 文档维护规则

- 新增功能先确定一个领域合同 owner；架构/API/数据库/交互文档只写跨域摘要并链接 owner 文档。
- 只保留一份当前状态、一份模块开发进度；日期记录可保留，但必须标出只适用的提交/轮次。
- 代码、测试、部署和候选验证分别记录；失败、skip、定向复测和未知状态都保留原始范围。
- 已替代合同不删除：加 `superseded-by` 与旧版本适用范围，旧数据/证据保持可追溯。
