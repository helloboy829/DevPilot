# Lost Worker 安全合同与最小回归 / Execution safety contract

2026-11-15。本切片只增加**只读技术分类与明确阻塞**：`app.evaluation.execution_safety.classify_held_reservation` 与边界回归测试。不新增释放、回收、重排队、重试、重发或调度 API，不修改 Worker、配额、取消或计时行为。

## 目的与边界

执行 run 到期后，旧 Worker 可能仍在发送请求，也可能已经死亡；deadline、队列状态、零计数和终态都不能证明其停止。运行中/取消等待的占用会保留全局配额，直到原 Worker 排空并由原 claim 收尾。本模块把单行占用的技术状态映射为固定投影，并**永远**返回未授权标志，供诊断、文档和未来实现使用；它不是 liveness 证明，也不是配额处置许可。

## 分类合同

输入为一行执行记录（可含额外列）与调用方时钟 `now_ms`。必须严格满足：`state ∈ {queued, running, cancel_requested, collected, interrupted}`；`reservation_held` 为真正的布尔；`deadline_ms`、`reserved_*` 为非负/正严格整数；`queued/running/cancel_requested` 必须持锁，`collected` 必须不持锁，`interrupted` 允许两种（过期保留配额与原 Worker 收尾都合法）。任何缺失、类型伪装（如 `1`/`True`）、未知状态或不一致组合立即 `ValueError`（失败关闭，不做猜测）。

| 输出 `state`              | 条件                         | 保留配额 | 含义                               |
| ------------------------- | ---------------------------- | -------- | ---------------------------------- |
| `queued_ready`            | queued，deadline > now       | 是       | 尚未领取，可能被原队列领取         |
| `queued_deadline_reached` | queued，deadline ≤ now       | 是       | 过期排队；清理只由原 `expire()` 执行 |
| `running_within_deadline` | running，deadline > now      | 是       | 旧进程可能仍在发送                 |
| `running_deadline_reached`| running，deadline ≤ now      | 是       | 到期不等于旧进程死亡               |
| `cancel_requested_pending`| cancel_requested             | 是       | 已请求取消但原 Worker 未排空       |
| `collected_terminal`      | collected，未持锁            | 否       | 原 Worker 已完成收尾               |
| `interrupted_terminal`    | interrupted（持锁与否）      | 视情况   | 可能是失败收尾或过期保留           |

固定投影键：`scope`、`observed_at_ms`、`state`、`reservation_held`、`deadline_reached`、`terminal`、`worker_liveness`（恒为 `not_established`）、`reservation{concurrency,body_bytes,response_bytes}`、`blockers`、以及恒为 `false` 的 `release_authorized`、`reclaim_authorized`、`requeue_authorized`、`retry_authorized`、`resend_authorized`、`dispatch_authorized`。不返回 owner/project/run/plan/execution ID、claim token/hash、端点、key、Q/A/gold 或密文。

固定阻塞码：`worker_liveness_not_established`（持锁时）、`deadline_is_not_worker_death`（持锁且到期）、`quota_retained_until_original_worker_drains`（running/cancel_requested）、`terminal_record_grants_nothing`（未持锁时）。阻塞码是结论，不是可执行建议。

## 现有运行时语义（未改动）

- `ExecutionRepository.claim()` 先执行 `expire()`，只领取 `deadline_ms > now` 的 queued 行；领取时写 claim hash 并把状态改为 running。
- `expire()` 只处理到期且 queued/running/cancel_requested：queued 排队行释放配额，running/cancel_requested 仍 `reservation_held=true`，run 标记 `execution_expired`；不重发、不产生新 claim。
- `cancel()`：queued 直接 interrupted 并释放；running 变为 cancel_requested 并保留配额。
- `finish()` 只接受原 claim token，并在 `_fenced(active=False)` 后写 collected/interrupted 与释放配额；审计失败与数据库未知结果不得重试。
- 调度器（`app/evaluation/schedules.py`）不导入执行仓库、不调用 `admit`，不能绕过独立 QA 准入；正式批准（`qa_approvals.py`）同样不能触发执行或释放。

## 未来任何释放/回收的前置条件（本切片明确未实现）

至少需要：可独立验证的旧进程死亡/排空证明（不是 deadline 或状态推断）、外部 fence/CAS 防止旧 Worker 重发、原 claim 之后无在途发送的证据、配额处置的职责分离与审计、显式 operator 同意。无法证明时必须保持阻塞；未知状态绝不自动处置，未知请求绝不重发。

## 明确不包含

- 无新 API/路由、无 UI、无后台清理器、无调度器变更、无迁移、无配置/权限变更。
- 不修改 `reservation_snapshot` 的聚合口径；不把分类结果写入审计或执行表。
- 不涉及真实模型/目标调用、部署、生产 key 或业务数据。

## 验证

```sh
cd backend
uv run pytest tests/test_execution_safety.py -q --tb=short
uv run pytest tests/test_execution_diagnostics.py tests/test_qa_execution.py tests/test_qa_execution_lifecycle.py tests/test_evaluation_schedules.py -q --tb=short
uv run ruff check . && uv run ruff format --check .
```

回归覆盖：七种状态与到期边界、配额保留、固定投影键、敏感字段不泄漏、类型伪装/未知状态/非一致行失败关闭、模块纯同步且无 I/O 依赖、调度器与正式批准不能绕过/触发执行、运维路由只有聚合 GET。

English: this slice adds a pure, synchronous classifier over one held execution row that never authorizes release, reclaim, requeue, retry, resend or dispatch. Deadline, queue state and terminal flags remain non-proofs of worker death; malformed or incoherent rows fail closed. Boundary regressions pin that the scheduler and formal approval cannot bypass or trigger QA execution and that operations expose only an aggregate GET.
