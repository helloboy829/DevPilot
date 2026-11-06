# 目标交换模板（设计示例）

> 2026-11-06。当前没有完整导入/执行/渲染实现。所有 ID、来源、版本、凭据引用与域名均为示例；不可直接运行或用于正式评分。

- [提测清单 CSV 表头](submission-template.csv)：可用 Excel 打开，填写前按组织要求调整，严禁填明文 key。
- [结构化提测样例](submission.example.json)：域名为不可调用的 example.invalid，授权/负载未获批。
- [数据 JSONL 样例](dataset.example.jsonl)：仅两条 synthetic 候选，pending_review、hash 未计算，不是冻结金标；expected 只供裁判，不能传目标。
- [方案样例](plan.example.json)：draft，门槛只演示格式，min_cases=50，因此两条数据不能直接满足方案。
- [请求规范样例](request-spec.example.json)：声明式输入绑定与内容流提取，不含秘密、不支持任意脚本，所有引用待创建。
- [独立工程导出请求](script-export-request.example.json)：只是目标 API 请求样例，**不是已导出的可运行工程**；execute_only 不代表效果通过。
- [人工复核提交](review-decision.example.json)：展示版本/领取/证据约束；hash 为明确占位，不可提交。
- [报告模板](report-template.md)：事实字段和审批/缺失规则，后续映射真实 DOCX/XLSX。
- [整改/复测模板](remediation-template.md)：保留基准、版本变化与全量/子集范围。

完整规则见[材料与模板规范](../DevPilot_材料与模板规范.md)。示例不含真实凭据，不代表 parser 已支持其中 cURL，能力实现后仍需安全预览、引用解析、授权、审核及冻结。

example_only、notes 及 EXAMPLE hash 用于解释设计，不能当作正式 API schema 或可用运行配置；开发时须发布强类型契约、移除说明字段并进行引用/权限校验。
