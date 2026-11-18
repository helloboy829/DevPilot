# 正式批准首切片 / Formal approval slice

2026-11-15。候选迁移 `eval_0015`（批准/审计）+ `eval_0016`（咨询性签核政策）。本模块在不可变独立评估之上增加**显式人类正式批准**记录：审批人具名、来源固定到具体 assessment revision/hash、职责分离、修订/撤销追加和审计。它是首切片，不是整个批准生命周期，也不改变任何历史证据或自动提升草稿为批准。

2026-11-17 接续：当前工作区增加 `eval_0017` 本人签核候选（未部署，当前验证和精确 SHA CI 未闭环）。所有完成初始化的用户都可被指派，无审批人账号等级；请求只授予读取该固定评估汇总和本人签署/撤销的范围。站内通知是显式加载的事件列表，不包含邮件、IM 或推送。owner 代录 v1 历史继续可读，但与本人认证签署 v2 分开验证；同一 run 一旦有 v2 批准记录，就拒绝追加新的 v1 决定，保留旧 v1 的读取和同 ID 幂等重放，避免有效性状态与 run 级最新索引分歧。v1 可先于 v2 写入，两种路径仍共用 run 锁和全局 revision CAS。

## 范围与对象

2026-11-16 权限规则更新：所有完成初始化的已登录用户均具备项目操作和审核资格，不设置审批人/审核人账号等级。本人签核候选见上方接续说明；项目归属与下面的运行内职责分离条件保持。见[全民审核与 Linux 验收](DevPilot_Equal_Review_and_Linux_Acceptance.md)。

- 对象：某项目内某个已 `recording_finished` 的执行 run 的**具体独立评估修订**（`evaluation_run_assessments` 行）。批准文档固定 `assessment_id`、`assessment_revision`、`assessment_hash`、`summary_hash`，不跟随最新复核或当前任务。
- 决定：`approved` 或 `revoked`，由具名审批人（canonical 账号 UUID）明确给出。`revoked` 必须附理由（`note` 1–2000 字符）。
- 记录人：当前通过鉴权与权限检查的项目 owner。审计 `actor` 记录实际写入的 owner；`approver_id` 与 `recorded_by` 分别保存决策人和记录人。
- 历史 owner 代录 API 仍由 owner-scoped 项目路由暴露。本人签核请求仅向被指派账号开放一份汇总视图，不授予项目成员身份、其他运行或案例读取权。

## 本人签核扩展（候选 `eval_0017`）

- owner 在数据集批准面板中复用已选 run、评估修订和账号，明确同意分享汇总并确认创建请求。账号按精确 ID 校验，不枚举用户目录。
- 被指派用户在审核中心显式加载本人待办/站内事件，明确打开固定汇总后，以当前登录身份签署。汇总仅含 ALL 计数、技术完整性、人工结论、冻结阈值和 hash，不包含案例、金标或原始证据。
- 决定写入既有 append-only 批准/审计账本，v2 文档记录认证签署人和请求来源；旧 v1 owner 代录继续兼容且不冒充本人签核。同一 run 出现 v2 后不再接受新 v1 写入，旧 v1 记录仍可读取及幂等重放。owner 只能取消未签请求；审批人可撤销本人已签决定。
- 到期、来源变化、撤销、被后续决定替代和完整性失败分别投影。未知写入只按原请求/操作 ID 只读对账，不自动重试。
- `eval_0017` 增加请求、事件和明确打开视图凭据三张表。候选需完成 SQLite/PostgreSQL parity、历史恢复、完整后端/前端检查、合成登录流程及当前 SHA CI；没有部署或真实业务数据迁移。
- 能力诊断随候选更新为 `approver_login=assigned_request_only`、`notifications=in_app_only`；多级强制、外部通知投递和批准导出仍是 blocker。签署进度不再把已实现的本人登录签署列为未实现。

## 写入前提（缺一不可）

1. run 当前状态为 `recording_finished`，且被固定 assessment 文档内的 `run_status` 也是 `recording_finished`。
2. assessment 完整性：文档 hash 与行一致（`assessment_hash`），`summary_hash` 与行一致；客户端提交的 `assessment_hash` 必须等于该行，否则冲突。
3. `readiness == "review_complete"` 且 `blockers` 为空——两名盲审/仲裁完整，无 uncertain、无缺失证据、无技术不完整。
4. 若冻结计划带有 `acceptance_criteria`，评估文档内 `criteria_evaluation.status` 必须为 `met`；`not_met`/`incomplete` 一律拒绝。仅阈值达标本身不会产生批准。
5. 职责分离：`approver_id` 不得等于项目 owner，也不得等于该 run 任一已验真任务的 reviewer_1/reviewer_2/arbitrator。任务定义会被重新验签，无法用被篡改的定义绕过。
6. 审批人账号存在且可用：路由在项目归属校验后按精确 ID 查询本地账号，账号不存在或 `needs_setup` 未完成时拒绝写入（409）；预检以 `approver_account_not_found` 阻塞。该查询不创建账号、不枚举目录，也不授予任何权限。
7. 显式确认：`confirmed=true`；布尔伪装（如 `1`）被拒绝。

失败关闭：任一前提不满足返回冲突/未找到；`case PASS`、完整复核、阈值达标或审计/评估历史都不能单独合成批准。

## 追加、修订与撤销

- 批准表 append-only：`(run_id, revision)` 唯一。首个记录 revision 1；撤销是新增 revision（通常 2），不改写 revision 1 的文档或 hash。
- `expected_previous_revision` 必须等于当前该 run 最大 revision；并发首发只有一个成功，其余冲突。同一 approval ID 与完全相同的请求重放返回原回执；不同载荷复用同 ID 冲突，不生成替代 ID。
- 每次追加写一条 `evaluation_approval_audit`（`sequence` 原子递增、`actor`、`action`、`subject_hash=approval_hash`、`at_ms`）。审计失败回滚整次追加。
- 读取：`GET` 单个批准验证该文档 hash；文档被篡改返回保护错误。列表仅返回元数据（不含 counts/document）；审计列表只返回有序技术元数据，不含 note/document/证据。

## API

| 方法 | 路径                                                                                                                  | 权限（全部满足）                  |
| ---- | --------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| GET  | `/api/evaluation/projects/{project}/approvals`                                                                        | read + review                     |
| GET  | `/api/evaluation/projects/{project}/approvals/capabilities`                                                           | read + review                     |
| GET  | `/api/evaluation/projects/{project}/approvals/signoff-policy`                                                         | read + review                     |
| PUT  | `/api/evaluation/projects/{project}/approvals/signoff-policy`                                                         | read + write + review（人类）     |
| GET  | `/api/evaluation/projects/{project}/approvals/integrity`                                                              | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals`                                                      | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/audit`                                                | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/sign-off`                                             | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/integrity`                                            | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}/metadata`                                        | read + review（原 ID 元数据对账） |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}`                                                 | read + review                     |
| GET  | `/api/evaluation/projects/{project}/review-runs/{run}/assessments/{assessment_id}/approval-preflight?approver_id=...` | read + review                     |
| POST | `/api/evaluation/projects/{project}/review-runs/{run}/approvals/{id}`                                                 | read + write + review（人类）     |

以下长段描述 `eval_0016` 时的能力投影；本人签核候选已更新审批人登录和站内事件通知状态，具体以本页上方 `eval_0017` 接续说明为准。

签核政策端点按项目追加 revision（owner 人类显式确认、`expected_previous_revision` CAS）：只保存 `required_distinct_approvers` 1–10 的**咨询政策**，`advisory=true`、`enforcement="none"`；不强制批准、不通知，也不改变签署进度端点既有 `policy="not_defined"`/`multi_level_satisfied=null`。签署进度会在有已存政策时附加 `stored_policy` 与 `requirement.source="stored_advisory"`；显式查询参数优先并标记 `request_only`。能力诊断端点只返回固定投影 `qa-approval-capabilities.v1`：`approver_login=not_implemented`、`owner_records_on_behalf=true`、`multi_level_policy=advisory_only`、`multi_level_enforcement=not_implemented`、`notifications=not_implemented`、`export=not_implemented`、`approval=not_authorized` 与固定 blockers；不读取项目、批准、账号或证据，只做项目归属校验。审计列表按 `sequence` 返回 `approval_id`、`revision`、`action`、`actor`、`subject_hash` 与 `at_ms`，最多 1000 条；不返回 document、note、counts 或证据。签署进度端点只返回聚合计数与固定状态：`policy="not_defined"`、`required_distinct_approvers=null`、`multi_level_satisfied=null`、revision/不同审批人/批准与撤销计数、最新 revision/decision，以及固定 blockers `multi_level_policy_not_defined`、`approver_login_not_implemented`；不返回任何 ID、hash、document 或 note，也不把多审批人计数当作多级签核已满足。可选 `required_distinct_approvers=1..10` 查询参数会附加**咨询性** `requirement`（复用纯核心），仅用于对照当前计数；不强制、不改变批准或 `multi_level_satisfied`，结果不授予批准或授权。链完整性端点只返回 `{status, approvals, events, blockers}`：校验 revision/sequence 连续、事件与批准一一匹配（project/run/approval_id/revision/action/actor/at_ms/subject_hash）、以及每条批准文档 hash 完整；不返回任何 ID、hash 或文档。项目级链汇总按 run 分组复用同一校验，只返回 `{status, runs, verified_runs, broken_runs, approvals, events, blockers}`；存在审计事件但无批准的行标记 `orphan_audit`。超过 5000 条批准/事件或 1000 个 run 时返回 `unverifiable` 与 `project_chain_too_long`，计数仍为真实值但不作逐 run 结论。项目级索引返回每个 run 的最新批准 revision（`run_id`、`id`、`revision`、`decision`、`assessment_id`、`assessment_hash`、`created_at_ms`），最多 200 条，不含文档/备注/计数。

只读预检返回 `eligible`、固定 `blockers` 码（collection/technical/review/criteria/separation/approver account）、`readiness`、`criteria.status`、两个分离布尔与 `latest_approval`（最新 revision/decision 元数据，若存在）；不写批准或审计行，`approval` 恒为 `not_recorded`。`approver_id` 必须是 canonical 账号（否则 422）；预检还按精确 ID 查账号，账号不存在或尚未完成初始化时追加 `approver_account_not_found` 并将 `eligible` 置为 false；未知评估返回 404；所有响应 `no-store`。创建/撤销在项目归属校验后同样要求该账号存在且可用（否则 409），只做精确 ID 查询，不提供账号目录或枚举。

内部调用者、非人类 token、无权限账号均被拒绝；跨 owner 返回 404。未知写入不重试，只按原 ID `GET` 对账（含 404）。错误响应不包含内部异常、SQL 或客户端敏感值；所有响应 `Cache-Control: no-store`。

## 工作台面板

候选 `eval_0016` 的咨询政策表由 `(project_id, revision)` 复合主键保证唯一性，不重复声明相同列的 UNIQUE。2026-11-16 已复现重复声明导致的 PostgreSQL/Alembic schema parity 差异，并在候选迁移和元数据中同步移除重复项；保留政策人数/revision 边界，不新增迁移头或改变咨询语义。此源码修复不执行现有数据库修复或部署。

原 ID 元数据对账成功后，同时清除旧预检、确认勾选和项目索引，避免继续显示写入前的资格与最新决定；索引只在用户显式点击后重新加载，不自动追加请求。仅加载运行列表而未确认原 ID 存在时，不清除未知写入状态。

`/workspace/datasets` 的正式批准面板只在显式点击后读取：项目索引、批准能力诊断、项目级链汇总、运行批准与审计列表、运行评估元数据、只读预检、运行级链完整性检查、签署进度分别由独立按钮触发，不自动轮询或读取证据。加载运行评估只读取 `id/revision/summary_hash/assessment_hash` 元数据，选择后填入固定评估 ID/hash 并撤销确认，不读取评估文档。链完整性按钮要求 32 位十六进制 run ID，只显示 `verified`/`broken`、批准/事件计数与固定 blockers；项目级汇总只显示 run 计数、批准/事件计数与固定 blockers；批准能力诊断只显示固定未实现/仅咨询投影与 blockers；签署进度只显示 revision/不同审批人计数、最新决定与“政策未定义”blockers；可选的拟议所需审批人数只附加咨询性 requirement，并明确“不保存、不强制”，不改变批准状态。切换项目时清除项目索引、run 与评估输入；切换 run 时清除运行级结果；修改评估 ID/hash 或审批人时清除旧预检、旧错误/提示并撤销显式确认，成功写入或对账后清除预检、签署进度与旧链汇总；已加载的项目索引在成功写入后本地更新为最新 revision/decision（不额外请求），显式加载运行批准会使已显示的链完整性与签署进度快照失效，需要重新检查。创建/撤销使用页面内存 pending ID，未知结果只按原 ID 只读对账：显式加载若发现原 ID 已存在，则清除 pending、旧链汇总并提示已对账；未发现时继续保留 pending。对账通过原 ID 的 `/metadata` 查询完成，不受最新 100 条列表上限影响，也不打开批准文档；pending 时禁止再次 POST。失败不重试、不写批准或审计；面板不读取 document、note 或任何 Q/A、金标与证据。

## 实现边界

App 的 `ApprovalService` 统一账号就绪、创建与咨询策略计算编排；仓库负责归属、持久化和固定目标验真，算术复用 devpilot 纯核心。前端 `useApprovalWorkspace` 统一请求生命周期与输入失效，运行时 schema 派生 TypeScript 类型，所有审批响应有界读取并校验作用域。CAS 使用实际最大 revision，不使用列表长度。链 hash 计算在线程中执行，避免阻塞事件循环。

## 数据与迁移

`eval_0015` 新增两张表，`down_revision = eval_0014`；`eval_0016` 追加一张咨询政策表，`down_revision = eval_0015`。

- `evaluation_run_approvals`：`id`(32 hex)、`owner_id`、`project_id`、`run_id`、`revision`、`created_at_ms`、`request_hash`、`assessment_id`(FK)、`assessment_hash`、`approver_id`、`decision`、`document`(JSON)、`approval_hash`；复合 FK 到 `evaluation_dispatch_runs(project_id, id)`；`(run_id, revision)` 唯一；revision 1–1000、decision 枚举检查。
- `evaluation_approval_audit`：`(run_id, sequence)` 主键、`project_id`、`approval_id`、`revision`、`actor`、`action`、`subject_hash`、`at_ms`。

`eval_0016` 的 `evaluation_approval_signoff_policies` 以 `(project_id, revision)` 为主键，含 owner、required count、时间、request/document hash；仅追加，不修改批准/审计表。`eval_0017` 候选另增签核请求、请求事件和明确打开视图三张表。增量迁移须保留全部旧表/行/外键与 Harness ledger；恢复矩阵和回退只证明实际执行过的版本，`eval_0016` 的历史收据不覆盖 `eval_0017`。

## 明确不包含

- 不修改 assessment、报告/复测档案、复核决定或任何历史字节；批准不是对数据的编辑权。
- 不新增审批人账号角色或独立登录系统；签核经现有账号认证和明确指派。当前候选不包含双人复核批准、强制多级签核、SLA、外部通知、外部签名或时间戳服务；签署进度端点可计算并展示咨询性要求，但不授权或强制批准。
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

English: `eval_0015` adds an append-only, revisioned human formal-approval ledger and `eval_0016` a stored advisory sign-off policy over a pinned immutable independent assessment. Approval requires finished collection, complete independent review, a met frozen threshold when defined, explicit confirmation, and an approver distinct from the owner and every blind reviewer/arbitrator. Revocation appends a revision with a required reason and audit. This first slice adds no approver-side auth, multi-level sign-off, notification, export authority or deployment, and never rewrites historical evidence.
