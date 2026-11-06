# AI 组件评测报告（目标模板）

> 模板版本 1.0；以下占位符由已批准事实模型映射，当前尚无对应渲染器。缺必填项应阻断发布，不让模型编造。

## 1. 报告信息与结论

- 项目 / 报告 ID / 版本：{{project_id}} / {{report_id}} / {{report_revision}}
- 被测组件 / 提交版本 / 指纹可信度：{{component_name}} / {{component_version}} / {{fingerprint_status}}
- 总 verdict：{{project_verdict}}；审批人/日期：{{approver}} / {{approved_at}}
- 结论范围与限制：{{scope_and_limitations}}；未决项：{{blocked_or_review_items}}

## 2. 依据与数据质量

来源版本/授权/敏感级别、dataset manifest hash、真实/合成分布、切片覆盖、标注与抽检、去重/泄漏、样本量与统计区间、未覆盖业务：{{dataset_quality_card}}

## 3. 环境、方案与复现

组件/endpoint/adapter/extractor、plan/rubric/裁判模型/Prompt/代码版本、测量环境、输入/输出规模、缓存/流式、seed、负载许可、阈值：{{reproducibility_manifest}}

## 4. 效果

N_total / PASS / FAIL / ERROR / PENDING / NOT_RUN：{{effect_counts}}
通过率 = N_pass / N_total：{{pass_rate}}；规则阈值和结果：{{effect_checks}}
专项指标、关键类别/切片、区间、争议与典型错误证据：{{effect_details}}

## 5. 性能

逐并发档/重复：测量窗、有效样本、成功/错误/重试、mean/p50/p95/p99、TTFT 适用性、QPS、整体输出 TPS 与 token 计数来源、Worker 瓶颈：{{perf_levels}}
缺失/不适用及原因：{{metric_applicability}}；阈值判定：{{perf_checks}}

## 6. 整改与复测

问题/版本/基准、full/subset 范围、条件差异与可比性、未关闭风险：{{remediation_and_retest}}

## 7. 证据与审批

run/job、原始观测/判定/来源/附件 ID 与 hash：{{evidence_index}}
审批记录、发布时间、脱敏/分发范围：{{publication_audit}}

发布校验：全部必测项齐备；判定与证据一致；通过报告无待审/阻断；不含密钥/不必要隐私；文件 hash 和模板版本可追溯。FAIL/BLOCKED 的报告明确标识，不能称通过报告。

## 复核与执行来源补充

- 运行与 assessment 修订：{{ run_assessment_refs }}；复核策略/覆盖：{{ review_policy_and_coverage }}。
- 必需未完成复核：{{ required_review_open_count }}；分歧/仲裁/参考答案修订及局限：{{ review_findings }}。
- 输入/输出/预期/来源的授权证据索引：{{ review_evidence_refs }}；正文按权限脱敏，不自动附全量盲测答案。
- 执行来源与信任：{{ execution_origin_and_trust }}；若为外部工程，附 export/manifest、核心/环境、采信审批与差异。
- 本报告只对应以上 assessment；后续复核变化须新修订/重新审批，原发布件不可覆写。

新增占位符须先映射到实现后的事实模型并校验；当前没有渲染器，不能将此文件直接视为正式报告。
