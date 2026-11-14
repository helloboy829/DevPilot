# 流式指标纯核心 / Streaming metrics core

2026-11-15。新增 `devpilot.qa_stream_metrics.compute_stream_metrics`：对**单次可观测流**给出固定技术投影（TTFT 与内容吞吐）。缺失、不可观测或不适用的指标显式返回 `unavailable` / `not_applicable`，绝不填 0；它不是质量判定、PASS 或批准。

## 输入

严格字典，字段集合必须完全一致，类型/顺序不合法立即 `ValueError`（失败关闭）：

| 字段                                        | 约束                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------- |
| `mode`                                      | `streaming` / `non_streaming`                                        |
| `outcome`                                   | `collected` / `technical_incomplete`                                 |
| `started_at_ms` / `finished_at_ms`          | 正整数毫秒；`started <= finished`                                    |
| `first_content_at_ms` / `last_content_at_ms`| `null` 或正整数；非空时满足 `started <= first <= last <= finished`   |
| `content_units`                             | 非负严格整数；`content_unit` 为 `chars` / `tokens`                   |

不可观测的时间必须是 `null`，不能用 0 或估算值；`last` 存在而 `first` 缺失属于不一致输入。

## 输出（`qa-stream-metrics.v1`）

- `scope=technical_stream_metrics_only`，`approval=not_approved`。
- `ttft`：`{status, ms, reason}`。streaming+collected+已观测首内容时为 `available`，`ms = first - started`；non-streaming 为 `not_applicable`；其余为 `unavailable`（`technical_incomplete` / `first_content_not_observed`）。
- `throughput`：`{status, unit, units, duration_ms, value, reason}`。仅 streaming+collected+完整生成窗口+`content_units > 0`+`last > first` 时可用：`value = round(units * 1000 / duration_ms, 3)`；non-streaming 为 `not_applicable`；缺失窗口为 `generation_window_not_observed`；零内容为 `no_content_units`；零/负区间为 `zero_generation_interval`。
- 所有不可用/不适用状态的数值字段为 `null`，不是 0；不推算、不插值、不以技术成功代表质量 PASS。

## 明确不包含

- 未接入 App 证据链、API、报告或 UI；不持久化、不参与阈值、批准或导出。
- 不发起模型/目标调用；不包含 CV、模型裁判、TTFT 的非流式估算或 tokens 与服务端计费对齐。
- 不改变现有 QA run、采集、加密输出、复核或批准合同；App 若接入需另立版本化合同与迁移/契约测试。

## 验证

```sh
PYTHONPATH=devpilot/src python -m unittest discover -s devpilot/src/devpilot/evaluation/tests -p 'test_stream_metrics.py' -v
```

覆盖：streaming 可用值、chars/tokens、non-streaming/technical_incomplete 不填零、缺失首内容/末内容、零内容、零区间、类型伪装与不一致时间、exact-fields/未知枚举失败关闭。分发 allowlist 同步包含新源码与测试（39 个第一方成员）。

English: `qa_stream_metrics` returns a versioned technical TTFT/throughput projection for one observable stream. Unavailable or inapplicable measurements are explicit and never zero; malformed or incoherent observations fail closed. It is not wired into App evidence, reports, thresholds or approval, and makes no model/target calls.
