# DevPilot 执行前冻结效果标准 / Frozen Effectiveness Criteria

更新：2026-11-08。本文说明本轮代码范围，不宣称完整评测平台已完成；提交、CI 与本地部署分别核验。仅含合成规则示例，不含客户材料、历史业务指标或项目场景。

## 1. 目标和边界

在效果计划执行前冻结版本化最低人工通过率，将三个概念明确分开：

1. **复核完整**：全部冻结样本都有可验证输出和明确的最新人工决定。
2. **效果阈值达标**：完整证据满足执行前声明的最低人工通过率。
3. **正式批准**：独立的审批职责、权限和证据签批流程；本轮**没有实现**。

`met` 不是正式验收，也不能推导性能合格。Agent 不能批准、修改已冻结阈值或改写人工决定。本轮不增加模型/目标调用，也不自动启用现有 Worker。

## 2. 使用流程

1. 在数据集页选择项目、组件、已冻结 QA 和请求版本，配置效果计划。
2. 可选勾选“冻结效果标准”，填写标准版本名、最低人工通过率；百分比最多两位小数。无隐藏推荐阈值，由评测者负责适用性。
3. 修改任意配置撤销确认，再显式冻结。预检仅验证定义和预算，不发送目标请求。
4. 独立执行仍需操作者启用、目标策略、密钥、权限和逐次授权；阈值不授予执行权限。
5. 逐条人工复核 Q/A/预期，查看汇总的复核完整性与效果标准判定。
6. 需要存档时选支持标准字段的中英文 `1.1.0` 模板。允许如实保存未达标的完整草稿，始终标记未批准。
7. 整改复测必须保留同一冻结标准与其版本，不得降低阈值伪装为同基准复测。

旧探索性计划不强制补阈值；标准变化须新建计划，不允许事后改门槛或重写旧结论。

## 3. 数据合同与兼容性

- 原 `qa-json-plan.v1` 的字段、序列化与哈希保持不变，不加默认 `null` 字段。
- 带标准的定义为 `qa-json-plan.v2`，标准对象为：

```json
{
  "schema": "qa-effectiveness-criteria.v1",
  "version_label": "Synthetic criteria v1",
  "min_pass_rate_bps": 5000
}
```

- `min_pass_rate_bps` 严格整数 `0..10000`；百分比乘 100，拒绝 bool、浮点、字符串和额外字段。这里的数字只是合成合同示例，**不是建议业务阈值**。
- 标准只适用于 `effectiveness`；性能计划、TTFT 和自动审批字段均不接受。
- 定义完整绑定既有 `definition_hash`；存储在已有计划 JSON 中，不增加表/迁移，App head 仍为 `eval_0009`。
- 仅 v2 已验证汇总增加 `criteria_evaluation`，进入既有 `summary_hash`；v1 汇总结构与历史存档保持兼容。
- 本轮版本是计划内不可变快照，不是独立标准注册中心/组织级策略库。

## 4. 精确判定

分母为**全部冻结效果样本**，不是已复核数或请求成功数。分子为最新可验证人工 `pass` 数。比较使用整数：

```text
passed * 10000 >= all_frozen_samples * min_pass_rate_bps
```

不按前端四舍五入显示值判定。采集未完成、技术证据不完整、未复核、`uncertain` 任一存在则 `incomplete`，即使阈值为零也不能称为达标。完整后才区分 `met` / `not_met`。响应固定 `scope=effectiveness_threshold_only`、`approval=not_approved`，整体汇总仍是 `acceptance=not_approved`。

它描述人工复核通过率，不宣称分类任务 accuracy、模型裁判分数或统计显著性。未知写入、缺密钥、证据校验失败仍 fail closed，不用阈值绕过。

## 5. 模板、历史与复测

- 保留原中英文 `1.0.0` 模板的完整布局；新增 `1.1.0`，目录最新版本优先。
- 新模板显示每组件标准版本、最低通过率与判定，旧计划显示 `not_configured`，不回填或跨组件平均。
- 服务端拒绝将含标准来源存到没有标准字段的旧模板；界面禁用不兼容选择并要求重新确认。
- 模板及汇总完整冻结到存档；后续人工复核或模板变化不改写旧文档。Word 仍从固定 Markdown 渲染，保留标准表，而非重新计算。
- 同基准整改复测在既有请求、数据、预算等相等检查上增加 plan schema 和标准快照相等；新旧 schema 或不同标准不能冒充同基准。

## 6. 权限、安全与验证

沿用 owner 私有、human read/review/write 的现有边界；内部 Agent 调用者不能创建计划或复核。没有新增金标浏览缓存、日志原文或真实外呼配置。测试使用合成资料与 mock collector。

覆盖：严格 DTO/错误输入、旧 v1 不变、v2 hash 防篡改、整数边界、零阈值不绕过不完整、独立准入→Worker→人工复核→汇总、1.1 报告与独立 DOCX reader、旧模板门禁、API owner/Agent 隔离、桌面/移动表单与标准展示。

验证结果应以本轮完整 SHA 的 CI 和独立本地部署记录为准，不能借用历史成功提交。当前运行功能基线仍以[本地升级记录](DevPilot_Local_Recovery_and_Upgrade.md)为准。

## 7. 持续迭代（未完成）

后续仍需：独立审批与职责分离、性能标准和真正流式 TTFT/TPS、CV 数据与裁判、模型评分校准、组织级标准注册库、调度准入、整改通知、真实脚本导出及脱敏知识闭环。不要把本轮单阈值比较称为完整 benchmark 或最终验收。

## English summary

This slice freezes an optional, plan-scoped human pass-rate threshold **before** execution. `qa-json-plan.v2` contains strict `qa-effectiveness-criteria.v1` basis-point integers and an explicit version label, bound by the existing plan hash. Legacy v1 plans, hashes and summaries are unchanged; no migration is required.

Only fully collected, verified and decisively reviewed effectiveness samples can yield `met` or `not_met`. The denominator includes every frozen sample. Integer cross-multiplication avoids rounded-display decisions; incomplete evidence blocks even a zero threshold. Every result remains `not_approved`. This is neither formal acceptance nor a performance criterion or an automatic model judge.

Template 1.1.0 adds frozen per-component criteria while preserving 1.0.0 and historical archives. New-criteria sources cannot silently use an old layout. Revisions append rather than overwrite, and the pinned Word renderer exports the already frozen Markdown. Same-benchmark retests require identical criteria/schema in addition to existing benchmark and budget equality.

Existing owner/human permissions, encryption, execution admission, no-retry and no-store boundaries remain. Tests use only synthetic data and a mock collector. Formal approvals, multimodal evaluation, streaming metrics, scheduling admission and the learning loop remain separate unfinished work.
