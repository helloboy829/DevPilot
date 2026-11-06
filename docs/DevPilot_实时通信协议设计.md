# DevPilot 实时通信协议 v3.0

> 2026-11-06；目标业务事件协议，待实现。现有 LangGraph 聊天流保持原协议，不把聊天 token 当评测进度。

## 1. 通道职责

REST 创建/审批/取消并查询权威快照；GET /api/evaluation/runs/{id}/events 传该运行通知，GET /api/evaluation/projects/{id}/events 传项目调试/导出/复核/报告待办。首版不另造 WebSocket。若 SSE 不可用，前端轮询 project/run/job/review 快照降级。
所有流与下载均做同等资源权限校验；事件不含原始 token、完整答案/图像、内网凭据或文件绝对路径。

## 2. 事件包

~~~text
id: 42
event: run.progress
data: {"schema_version":"1.0","stream_type":"run","stream_id":"run-001","project_id":"project-001","run_id":"run-001","seq":42,"occurred_at":"2026-11-06T08:00:00Z","subject_type":"run","subject_id":"run-001","subject_revision":7,"payload":{"completed_cases":95,"total_cases":100}}

~~~

上述为 run 流示例。统一 envelope 含 stream_type(run/project)、stream_id、project_id、seq、occurred_at、subject_type/id/revision 和 payload；run_id 对无运行的调试/数据复核可为空。seq 为各 stream 内持久递增序号，id 等于其十进制字符串；客户端按 (stream_type,stream_id,seq) 去重。run 的 revision 是主体修订，不等于 seq；同一业务事件同时投影到两条流时附 event_id，客户端只做缓存失效，不重复执行操作。不承诺网络 exactly-once。

## 3. 事件种类

| event | payload 摘要 |
| --- | --- |
| run.queued / run.started | snapshot_hash、job_ref、started_at |
| run.progress | 各 outcome 计数、当前阶段；允许节流但终态必须准确 |
| case.completed | case_id、outcome、result_ref；大内容另取 |
| review.required / review.task.updated | task_ref、kind、reason、status、subject_revision；详情按 REST 权限取 |
| review.resolved | task_ref、resolution_revision、affected_run_refs；不推送完整决定或金标 |
| endpoint.check.completed / endpoint.confirmation.updated | check/confirmation_ref、status、binding_revision；不传 raw 响应 |
| script.export.completed / script.export.failed | export_ref、job_ref、artifact_ref 或安全错误码；下载仍鉴权 |
| external_result.review.required | import_ref、验证摘要、待采信范围 |
| perf.level.started / perf.level.completed | concurrency、repeat、窗口、metric_refs |
| run.cancelling | actor、reason |
| run.completed | status=completed、verdict、summary_ref、blocked_reasons |
| run.failed / run.cancelled / run.interrupted | status、错误/中断类别、恢复指引 |
| run.verdict.updated / run.assessment.updated | 人工复核或重判后的 verdict、assessment_revision、required_review_open_count |
| report.ready / report.review.invalidated | report_id、status、assessment_refs、需重审原因；不等于已发布 |

completed ≠ PASS。审批/人工复核属于独立资源，通过 approval/task_ref 获取并经 REST 决策；不在 SSE 里执行状态变更。run.completed 后可有 review/verdict/report 事件，不能因执行结束永远停掉业务更新。

## 4. 重连、丢事件与终态

- 服务先鉴权再流式发送；heartbeat 使用 SSE 注释，不计业务 seq。
- Last-Event-ID 重放保留期内事件；前端先拉快照再订阅，重放后按 revision/seq 合并。
- 游标超出保留范围/无效时返回 409 EVENT_CURSOR_EXPIRED，前端取全量快照和新游标，不能猜状态。
- outbox 提交与业务状态同事务；广播失败可重发，客户端不依赖每个 progress 必达。
- 客户端断开不取消任务；取消须显式 REST；浏览器关闭后任务仍由 Worker 负责。
- SSE 空闲/网络断开采用有界退避重连；auth 失效停止重连，避免无限请求。

## 5. 前端一致性与代理

TanStack Query 管理快照；事件触发定向 invalidation/受控合并。不直接累加 received_count，避免重复事件污染分母。
Nginx 对 SSE 关闭缓冲与压缩，配置合理超时；不要同时全站禁用静态资源压缩。沿用当前 /api/langgraph/* 的重写，仅新增业务路由；部署测试覆盖代理后的重连而非只测本机 FastAPI。
