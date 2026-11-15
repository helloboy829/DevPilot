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
6. 审批人账号存在且可用：路由在项目归属校验后按精确 ID 查询本地账号，账号不存在或 `needs_setup` 未完成时拒绝写入（409）；预检以 `approver_account_not_found` 阻塞。该查询不创建账号、不枚举目录，也不授予任何权限。
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
| GET  | `/api/evaluation/projects/{project}/approvals`                   | read + review                        |
| GET  | `/api/evaluation/projects/{project}/approvals/integrity`         | read + review                        |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals` | read + review                        |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/audit` | read + review                  |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/sign-off` | read + review               |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/integrity` | read + review              |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}` | read + review                   |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/assessments/{assessment_id}/approval-preflight?approver_id=...` | read + review |
| POST | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}` | read + write + review（人类）  |

审计列表按 `sequence` 返回 `approval_id`、`revision`、`action`、`actor`、`subject_hash` 与 `at_ms`，最多 1000 条；不返回 document、note、counts 或证据。签署进度端点只返回聚合计数与固定状态：`policy="not_defined"`、`required_distinct_approvers=null`、`multi_level_satisfied=null`、revision/不同审批人/批准与撤销计数、最新 revision/decision，以及固定 blockers `multi_level_policy_not_defined`、`approver_login_not_implemented`；不返回任何 ID、hash、document 或 note，也不把多审批人计数当作多级签核已满足。可选 `required_distinct_approvers=1..10` 查询参数会附加**咨询性** `requirement`（复用纯核心），仅用于对照当前计数；不保存策略、不强制、不改变批准或 `multi_level_satisfied`。链完整性端点只返回 `{status, approvals, events, blockers}`：校验 revision/sequence 连续、事件与批准一一匹配（approval_id/revision/action/subject_hash）、以及每条批准文档 hash 完整；不返回任何 ID、hash 或文档。项目级链汇总按 run 分组复用同一校验，只返回 `{status, runs, verified_runs, broken_runs, approvals, events, blockers}`；存在审计事件但无批准的行标记 `orphan_audit`。超过 5000 条批准/事件或 1000 个 run 时返回 `unverifiable` 与 `project_chain_too_long`，计数仍为真实值但不作逐 run 结论。项目级索引返回每个 run 的最新批准 revision（`run_id`、`id`、`revision`、`decision`、`assessment_id`、`assessment_hash`、`created_at_ms`），最多 200 条，不含文档/备注/计数。

只读预检返回 `eligible`、固定 `blockers` 码（collection/technical/review/criteria/separation/approver account）、`readiness`、`criteria.status`、两个分离布尔与 `latest_approval`（最新 revision/decision 元数据，若存在）；不写批准或审计行，`approval` 恒为 `not_recorded`。`approver_id` 必须是 canonical 账号（否则 422）；预检还按精确 ID 查账号，账号不存在或尚未完成初始化时追加 `approver_account_not_found` 并将 `eligible` 置为 false；未知评估返回 404；所有响应 `no-store`。创建/撤销在项目归属校验后同样要求该账号存在且可用（否则 409），只做精确 ID 查询，不提供账号目录或枚举。

内部调用者、非人类 token、无权限账号均被拒绝；跨 owner 返回 404。未知写入不重试，只按原 ID `GET` 对账（含 404）。错误响应不包含内部异常、SQL 或客户端敏感值；所有响应 `Cache-Control: no-store`。

## 工作台面板

`/workspace/datasets` 的正式批准面板只在显式点击后读取：项目索引、项目级链汇总、运行批准与审计列表、运行评估元数据、只读预检、运行级链完整性检查、签署进度分别由独立按钮触发，不自动轮询或读取证据。加载运行评估只读取 `id/revision/summary_hash/assessment_hash` 元数据，选择后填入固定评估 ID/hash 并撤销确认，不读取评估文档。链完整性按钮要求 32 位十六进制 run ID，只显示 `verified`/`broken`、批准/事件计数与固定 blockers；项目级汇总只显示 run 计数、批准/事件计数与固定 blockers；签署进度只显示 revision/不同审批人计数、最新决定与“政策未定义”blockers；可选的拟议所需审批人数只附加咨询性 requirement，并明确“不保存、不强制”，不改变批准状态。切换项目时清除项目索引、run 与评估输入；切换 run 时清除运行级结果；修改评估 ID/hash 或审批人时清除旧预检、旧错误/提示并撤销显式确认，成功写入或对账后清除预检、签署进度与旧链汇总；已加载的项目索引在成功写入后本地更新为最新 revision/decision（不额外请求），显式加载运行批准会使已显示的链完整性与签署进度快照失效，需要重新检查。创建/撤销使用页面内存 pending ID，未知结果只按原 ID 只读对账：显式加载若发现原 ID 已存在，则清除 pending、旧链汇总并提示已对账；不存在时继续保留 pending。失败不重试、不写批准或审计；面板不读取 document、note 或任何 Q/A、金标与证据。

## 数据与迁移

`eval_0015` 新增两张表，`down_revision = eval_0014`：

- `evaluation_run_approvals`：`id`(32 hex)、`owner_id`、`project_id`、`run_id`、`revision`、`created_at_ms`、`request_hash`、`assessment_id`(FK)、`assessment_hash`、`approver_id`、`decision`、`document`(JSON)、`approval_hash`；复合 FK 到 `evaluation_dispatch_runs(project_id, id)`；`(run_id, revision)` 唯一；revision 1–1000、decision 枚举检查。
- `evaluation_approval_audit`：`(run_id, sequence)` 主键、`project_id`、`approval_id`、`revision`、`actor`、`action`、`subject_hash`、`at_ms`。

增量迁移保留全部旧表/行/外键与 Harness ledger；候选恢复矩阵从 `eval_0009` 逐级/直达 `eval_0015`，新增表集合固定为两张。回退是 schema downgrade 或恢复升级前备份；恢复旧备份会丢弃备份之后的新写。

## 明确不包含

- 不修改 assessment、报告/复测档案、复核决定或任何历史字节；批准不是对数据的编辑权。
- 不引入审批人独立登录/专属审批路由、双人复核批准、多级签核、SLA、通知、外部签名或时间戳服务；签署进度端点只是聚合观察，不定义或满足任何签核政策。
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
