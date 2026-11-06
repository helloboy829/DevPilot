# DevPilot Prompt 工程设计 v3.0

> 2026-11-06；目标评测 Prompt 规范。旧通用编码 Agent Prompt 不再是产品主线。本文件是设计，不声明已交付对应 Skill。

## 1. 职责与原则

领域助手负责提测缺项、数据候选、rubric 草拟、争议解释和报告草稿。Prompt 不负责 SQL 权限、并发上限、计数、指标计算或最终 PASS，这些由确定性服务实现。
系统指令与材料/输出分区；工具返回和文档均视为不可信数据。模型不得按被测输出里的“忽略规则/给满分”等文字改变标准。

## 2. 版本与输入

每个 Prompt bundle 保存 ID、语义版本、hash、用途、schema、可用工具、模型参数和回归集。落盘目录由实现任务确定，不再把不存在的 prompts/ 或 skills/custom 写成当前事实。
上下文只含已授权项目摘要、批准来源片段、规则版本和必要证据；按角色限制盲测标签。不得把全部项目材料永久写入自动记忆。

## 3. 模板要点

### 3.1 提测检查

要求输出 missing_fields、unsupported_capabilities、clarification_questions、risk_notes。只依据现有字段；不能猜版本、许可证、凭据或验收门槛。完整 cURL 必须交给安全 parser，不让模型“直接执行一下”。

### 3.2 数据构建

输入：任务、业务分布、批准来源、覆盖矩阵、标签规则、生成预算、禁止使用的验收集。
输出：候选 case、source_refs、可定位证据、origin=synthetic、slice、预期与不确定项。无依据则标待审核/不可生成，不能编造知识库出处。
设计正/负/边界/不可回答/域外，但不能通过同义改写近重复刷规模。每批先少量校准再扩大；生成模型输出本身不成为可信标签。

### 3.3 语义裁判

输入明确分隔 question、reference/rubric、source_evidence、actual_output；参考答案不可发送目标 API。
输出约定：

~~~json
{
  "schema_version": "1.0",
  "case_id": "qa-001",
  "rubric_version": "qa-rubric-v1",
  "dimensions": {"factuality": "pass", "completeness": "pass", "citation": "needs_review"},
  "proposed_outcome": "PENDING",
  "evidence_refs": ["src-001#p3"],
  "reason": "结论合理，但引用位置无法确认",
  "uncertainty": "missing_evidence"
}
~~~

服务端校验枚举、引用存在性与必需维度，并转换为业务 judgment。裁判无权输出项目最终 PASS，也无权删 ERROR 项；结构不合法或裁判失败保留未判状态和错误原因。
可接受同义答案须按“必要事实、禁止事实、容差、证据、拒答条件”规则，而非模糊字符串比例。对成对比较可交换位置检查偏差；对长回答避免篇幅奖励；关键场景人工校准。

### 3.4 报告生成

只从冻结事实模型填模板，段落须可追溯到 run/metric/case/source ID。缺项输出“缺失/不适用/待审”，不得补造 p99、来源或 PASS。模板表格与数值由程序渲染，模型负责解释与局限；发布前人工审阅。

## 4. 校准、回归与变更

先以历史人工标注校准集测误放行/误拒绝、一致性、争议和裁判失败，按风险设最低标准。生成模型与裁判可分离，但不同模型不自动消除偏差；采用独立人工基准。
改 Prompt、模型、抽取器或 rubric 需回归并发布新版本；旧输出可离线重判但保留原判断。新经验未经评审不得自动修改生产 Prompt。
Prompt 评测覆盖注入、长文本、无证据、矛盾参考、多义答案、低资源语言、CV 文本描述失真和裁判服务故障。记录成本和审查工时，不单追逐模型自评分。

## 5. 调试与复核辅助提示词约束

接入助手仅解释脱敏 RequestSpec/Check、建议声明式字段映射或提取器；遇到不支持协议/签名时返回 capability 缺项，不自行 shell 执行 cURL。脚本导出提示词只能协助补全配置/README，runner 与统计由受控模板/同版本核心决定，不把生成代码当可信执行器。

复核助手先整理 Q/A/预期要点/证据与不确定性；盲审策略下不泄露自动建议/他人判断，其他模式也只给建议，不冒充 reviewer 签名。引用错误/资料不足必须送审，禁止把目标 ERROR 改 PASS 或修改冻结 expected。报告解释必须引用明确 assessment_revision 和人工覆盖范围，不能将抽检包装为全量审核。
