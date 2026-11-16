# 多级签核要求纯核心 / Sign-off requirement core

日期：2026-11-16。候选源码；纯核心供本地 CLI 与 App 编排层复用。App 支持项目级咨询策略存储与显式查询参数；两者均不强制批准。

## 范围

`devpilot.qa_signoff_policy.evaluate_signoff_requirement` 只回答一个技术问题：**在调用方显式给出的策略下，现有聚合计数是否满足要求**。它不定义、不保存、不推断策略，也不读取批准文档、账号或审计。

```python
evaluate_signoff_requirement(
    required_distinct_approvers=2,   # None 表示未定义策略
    distinct_approved_approvers=2,
    latest_decision="approved",
)
```

固定输出（`qa-signoff-requirement.v1`）：

- `policy`：`{defined, required_distinct_approvers}`；未定义时 `required_distinct_approvers=None`。
- `observed`：`{distinct_approved_approvers, latest_decision}`。
- `satisfied`：策略已定义且无 blockers 时为 `true`，否则 `false`；策略未定义时为 `null`，绝不当作满足。
- 固定 blockers：`multi_level_policy_not_defined`、`insufficient_approvers`、`latest_decision_not_approved`（排序去重）。
- `approval: "not_approved"`；结果不是批准、证据或验收。

## 失败关闭

- `required_distinct_approvers` 必须是 `None` 或严格整数 1–10；`distinct_approved_approvers` 必须是严格整数 0–1000（批准修订上界，不受 1–10 人的阈值上限影响）；`latest_decision` 必须是 `None`/`approved`/`revoked`。
- 布尔、负数、越界、带空白或未知枚举一律 `ValueError`；不填零、不猜测策略、不把多审批人计数当作多级签核。

## 明确不包含

- 纯核心不保存策略；App 已通过 `eval_0016` 保存项目级追加式咨询策略。显式查询可覆盖它；端点顶层仍固定 `policy=not_defined`，咨询性 requirement 不授权或生成批准。
- 不改变既有批准写入/撤销/链校验语义；本核心只是未来策略层的纯计算积木。
- 无网络、模型、真实数据或部署。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover \
  -s devpilot/src/devpilot/evaluation/tests -p 'test_signoff_policy.py' -v
```

纯核心专项 **7 passed**；同一核心也通过离线 CLI 暴露（`qa_metrics_cli signoff --requirement ...`，CLI 专项 **11 passed**）。evaluation 域合计 **53 passed**、toolkit **58 passed**；分发 allowlist 为 **47** 个成员，分发测试 **72 passed**。

English: a pure requirement evaluator answers whether an explicitly supplied multi-level sign-off policy is met by aggregate counts. The App accepts a query override or loads an append-only advisory project policy; neither enforces nor creates approval. Observed counts allow 1,000 revisions independently of the threshold limit of 10.
