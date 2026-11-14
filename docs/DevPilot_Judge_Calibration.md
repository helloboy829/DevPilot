# 模型裁判校准纯核心 / Judge calibration core

2026-11-15。新增 `devpilot.qa_judge_calibration.compute_judge_calibration`：对成对的人工结论与裁判输出做**技术一致性统计**。只统计双方都给出确定性标签（pass/fail）的配对；缺失或 uncertain 的配对显式排除并计数，绝不当作一致、零差异或批准。它不是质量判定、正式批准，也不调用模型。

## 输入

严格列表（最多 10,000 项），每项必须恰为 `{"human": label|None, "judge": label|None}`，label ∈ {`pass`,`fail`,`uncertain`}；类型伪装、未知标签、多余字段或非列表输入立即 `ValueError`（失败关闭）。

## 输出（`qa-judge-calibration.v1`）

- `scope=technical_judge_calibration_only`，`approval=not_approved`。
- `counts`：`total`、`both_definitive`、`human_missing`、`judge_missing`、`uncertain_excluded`。双方都缺失时优先计入 `human_missing`。
- `confusion`：`pass_pass`、`pass_fail`、`fail_pass`、`fail_fail`（只含确定性配对）。
- `agreement`：`{status, numerator, denominator, value, reason}`。有确定性配对时为 `available`，`value = round((pass_pass+fail_fail)/both_definitive, 4)`；无确定性配对时为 `insufficient`，数值为 **null**（不是 0），reason 为 `no_definitive_pairs`。

## 明确不包含

- 未接入 App 证据、API、报告或 UI；不持久化、不参与阈值、批准或导出。
- 不调用模型/目标，不生成裁判结论，不把一致性当作准确率或批准。
- 不定义抽样/分层/置信区间；如需统计推断另立合同。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover -s devpilot/src/devpilot/evaluation/tests -p 'test_judge_calibration.py' -v
```

覆盖：确定性配对一致/不一致、缺失与 uncertain 排除、空集与无确定性配对 `insufficient`（不填零）、confusion 合计、类型/标签/字段/上限失败关闭。分发 allowlist 同步包含新源码与测试（41 个第一方成员）。

English: a pure, versioned agreement projection over paired human/judge labels. Only definitive pairs count; missing/uncertain pairs are explicit exclusions, and no definitive pairs yields `insufficient` with null values. It is not approval, accuracy or a model call.
