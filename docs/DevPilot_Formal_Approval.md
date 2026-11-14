# 正式批准首切片 / Formal approval slice

2026-11-15。候选迁移 `eval_0015`。本模块在不可变独立评估之上增加**显式人类正式批准**记录：审批人具名、来源固定到具体 assessment revision/hash、职责分离、修订/撤销追加和审计。它是首切片，不是整个批准生命周期，也不改变任何历史证据或自动提升草稿为批准。

## 范围与对象

- 对象：某项目内某个已 `recording_finished` 的执行 run 的**具体独立评估修订**（`evaluation_run_assessments` 行）。批准文档固定 `assessment_id`、`assessment_revision`、`assessment_hash`、`summary_hash`，不跟随最新复核或当前任务。
- 决定：`approved` 或 `revoked`，由具名审批人（canonical 账号 UUID）明确给出。`revoked` 必须附理由（`note` 1–2000 字符）。
- 记录人：当前通过鉴权与权限检查的项目 owner。审计 `actor` 记录实际写入的 owner；`approver_id` 与 `recorded_by` 分别保存决策人和记录人。
- 仓储层写入 API 由 owner-scoped 项目路由暴露；审批人本人不因此获得项目成员权限或数据读取权。

## 写入前提（缺一不可）

1. run 当前状态为 `recording_finished`，且被固定 assessment 文档内的 `run_status` 也是 `recording_finished`。
2. assessment 完整性：文档 hash 与行一致（`assessment_hash`），`summary_hash` 与行一致；客户端提交的 `assessment_hash` 必须等于该行，否则冲突。
3. `readiness == "review_complete"` 且 `blockers` 为空——两名盲审/仲裁完整，无 uncertain、无缺失证据、无技术不完整。
4. 若冻结计划带有 `acceptance_criteria`，评估文档内 `criteria_evaluation.status` 必须为 `met`；`not_met`/`incomplete` 一律拒绝。仅阈值达标本身不会产生批准。
5. 职责分离：`approver_id` 不得等于项目 owner，也不得等于该 run 任一已验真任务的 reviewer_1/reviewer_2/arbitrator。任务定义会被重新验签，无法用被篡改的定义绕过。
6. 显式确认：`confirmed=true`；布尔伪装（如 `1`）被拒绝。

失败关闭：任一前提不满足返回冲突/未找到；`case PASS`、完整复核、阈值达标或审计/评估历史都不能单独合成批准。

## 追加、修订与撤销

- 批准表 append-only：`(run_id, revision)` 唯一。首个记录 revision 1；撤销是新增 revision（通常 2），不改写 revision 1 的文档或 hash。
- `expected_previous_revision` 必须等于当前该 run 最大 revision；并发首发只有一个成功，其余冲突。同一 approval ID 与完全相同的请求重放返回原回执；不同载荷复用同 ID 冲突，不生成替代 ID。
- 每次追加写一条 `evaluation_approval_audit`（`sequence` 原子递增、`actor`、`action`、`subject_hash=approval_hash`、`at_ms`）。审计失败回滚整次追加。
- 读取：`GET` 单个批准验证整链 hash；文档被篡改返回保护错误。列表仅返回元数据（不含 counts/document）；审计列表只返回有序技术元数据，不含 note/document/证据。

## API

| 方法 | 路径                                                             | 权限（全部满足）                     |
| ---- | ---------------------------------------------------------------- | ------------------------------------ |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals` | read + review                        |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/audit` | read + review                  |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}` | read + review                   |
| POST | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}` | read + write + review（人类）  |

审计列表按 `sequence` 返回 `approval_id`、`revision`、`action`、`actor`、`subject_hash` 与 `at_ms`，最多 1000 条；不返回 document、note、counts 或证据。

内部调用者、非人类 token、无权限账号均被拒绝；跨 owner 返回 404。未知写入不重试，只按原 ID `GET` 对账（含 404）。错误响应不包含内部异常、SQL 或客户端敏感值；所有响应 `Cache-Control: no-store`。

## 数据与迁移

`eval_0015` 新增两张表，`down_revision = eval_0014`：

- `evaluation_run_approvals`：`id`(32 hex)、`owner_id`、`project_id`、`run_id`、`revision`、`created_at_ms`、`request_hash`、`assessment_id`(FK)、`assessment_hash`、`approver_id`、`decision`、`document`(JSON)、`approval_hash`；复合 FK 到 `evaluation_dispatch_runs(project_id, id)`；`(run_id, revision)` 唯一；revision 1–1000、decision 枚举检查。
- `evaluation_approval_audit`：`(run_id, sequence)` 主键、`project_id`、`approval_id`、`revision`、`actor`、`action`、`subject_hash`、`at_ms`。

增量迁移保留全部旧表/行/外键与 Harness ledger；候选恢复矩阵从 `eval_0009` 逐级/直达 `eval_0015`，新增表集合固定为两张。回退是 schema downgrade 或恢复升级前备份；恢复旧备份会丢弃备份之后的新写。

## 明确不包含

- 不修改 assessment、报告/复测档案、复核决定或任何历史字节；批准不是对数据的编辑权。
- 不引入审批人独立登录/专属审批路由、双人复核批准、多级签核、SLA、通知、外部签名或时间戳服务。
- 不把批准写进报告/复测/PDF/Word，不改变导出权限，不自动启用执行、外发或部署。
- 无真实模型/目标调用、无生产 key、无业务数据库迁移；所有测试为合成数据。
- 批准备注目前作为有界明文存入批准文档（与报告草稿的人工备注同类），不进入证据加密域；敏感信息不应写入 note。

## 验证入口

```sh
cd backend
uv run pytest tests/test_qa_approvals.py tests/test_qa_approvals_router.py -q --tb=short
uv run pytest tests/test_formal_approval_migrations.py -q --tb=short
uv run pytest tests/test_candidate_upgrade_recovery.py -q --tb=short
```

专项与全量重叠，不相加；skip 不是通过。精确 SHA 的 Actions 与本地结果分别核验。

English: `eval_0015` adds an append-only, revisioned human formal-approval ledger over a pinned immutable independent assessment. Approval requires finished collection, complete independent review, a met frozen threshold when defined, explicit confirmation, and an approver distinct from the owner and every blind reviewer/arbitrator. Revocation appends a revision with a required reason and audit. This first slice adds no approver-side auth, multi-level sign-off, notification, export authority or deployment, and never rewrites historical evidence.
