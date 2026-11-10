# 外部 QA 技术元数据隔离接收 / External QA technical metadata quarantine

## 范围与状态 / Scope and status (2026-11-11)

这是外部技术声明的持久隔离档案，不是外部输出/证据导入、真实性证明、平台 run、独立评估或正式批准。
本模块新增后端 API、不可变技术档案和审计；不包含 workspace UI。当前模块本地最终门禁已通过；资源、独立提交/推送和精确 SHA Actions 分别核验，不是已部署功能。
候选 additive migration 为 `eval_0014`，新增两表、两索引；旧迁移不变。历史部署收据仍为 `eval_0009`，不能代表本机当前运行状态。

## 显式授权与 HTTP 边界

- 创建：`PUT /api/evaluation/projects/{project_id}/external-qa-intakes/{intake_id}`。
- 同 ID 对账：`GET /api/evaluation/projects/{project_id}/external-qa-intakes/{intake_id}`。
- 元数据审计：`GET /api/evaluation/projects/{project_id}/external-qa-intakes/{intake_id}/audit`。
- intake ID 是调用方显式保留的 32 位小写十六进制 ID；没有 update/delete、latest、上传 SQLite/ZIP 或恢复执行接口。
- 所有接口要求已认证人类与项目 owner。创建另外要求 project read/write/review、exports read 和独立 `evaluation_external_qa:create`；读取/审计要求 project read 与独立 `evaluation_external_qa:read`。
- 创建确认 `confirmed`、`technical_metadata_only_confirmed`、`untrusted_source_acknowledged` 必须分别为精确布尔 `true`；不接受字符串或整数替代。
- 两份 receipt/reconciliation JSON 各不超过 **8192 UTF-8 bytes**；完整 HTTP body 在缓存前限制为 **32768 bytes**，超过后不继续读取后续 chunks。
- DTO 不剥离技术文档首尾空白，避免改变已查看的原始 bytes hash。外层重复 JSON key 也拒绝。
- 所有响应 private/no-store，验证与存储故障使用通用错误，不回显原始内容、密钥或数据库异常。

## 历史来源与 ALL 冻结总体

来源必须显式指定已查看的历史 export ID/receipt hash、原始 canonical run UUID 和 manifest fingerprint。
只接受完整 `baseline_inputs` 历史授权导出；`skeleton`、验收/gold 输入、不完整输入均不受理。
当前 export grant 不授予导入权；历史 grant 到期不阻止另行确认、单独授权的技术声明归档。

读取仅使用 export 安全元数据和不可变 plan definition，不读取 encrypted bundle、request ciphertext、QA samples、参考答案、输出或 encryption key。
重新验证历史 export receipt 和 plan，并绑定 schema/hash、QA revision/hash、request-version/protected hash、ALL input/request counts。
声明的已预留请求总 bytes 不得超过冻结 plan 的总 body budget。
这些检查只是内部结构/配置对齐，不能证明外部请求值、接收者身份、真实执行或逐 ordinal 事实。

## 不可信声明与不可变保存

复用 `external_qa_metadata.inspect_local_metadata` 的严格解析器：拒绝重复/缺失/额外字段、过深 JSON、非整数计数、错误 UUID/hash、总体和 aggregate 不一致，以及任何输出/批准声明。
ALL 冻结样本始终保留；不会把成功或已观测子集当分母。
一套完全一致的伪造声明也只能成为 **NOT_EVALUATED** 技术档案，所有 provenance/output/per-ordinal/evidence/approval/dispatch/resume/resend 标志保持 false。

原始未解析 JSON 和空白不持久保存。仅保存校验后的 canonical 技术 JSON，分别记录 **canonical SHA** 与**声明的原始 bytes SHA/长度**。
读取时对 canonical bytes 重新运行严格解析器，再恢复原始 SHA 声明并与不可变档案比对；不能声称重新验证已丢弃的原始 bytes。
公开 hash 是完整性约束，不是认证签名或平台真实性证明。

同 ID 不可覆盖；同 export/original-run/canonical-pair snapshot 不得通过更换空白重复存储。
同一原始 run 的不同技术快照可以显式追加，但不声称可信时间顺序，也不更新旧记录或平台 run 状态。
创建审计仅包含技术元数据，GET 不写入新的事件；审计 pagination 有明确上限。

## 原子性、并发与取消

严格解析和完整性重检在线程中运行。最终按 **project → export → plan** 锁顺序重新核对整个来源快照，档案与审计原子提交。
相同 ID 或相同语义快照并发创建，只能产生一份档案及一份审计；来源变化拒绝提交。
沿用 `_drain` 排空数据库 reads/writes 和线程任务，重复取消后仍传播 `CancelledError`，不让 pooled locks 或后台写入逃逸。
未知 PUT 结果（包括后续 GET 404）只允许 GET 原 intake ID；不重发 PUT、不自动生成新 ID、不重试或恢复发送。
404 只说明当前读取结果，不是此前没有提交或没有外部发送的证明。

## 验证记录与证据边界

- 原始红灯：此前 HTTP 路径为 404，说明尚无持久接收能力；日志保留。
- 修改前完整基线：后端 **13,260 passed / 19 skipped / 11 deselected / 40 warnings**；前端 **155 files / 1,312 passed**，整个 frontend Prettier 通过。此基线不是新实现的验证结果。
- 初版专项 **66 passed**；补强历史来源 fingerprint/body budget 与 read 权限边界后，最终专项 **68 passed，30.75s**，包括 foreign-keys ON 的 SQLite、独占临时 PostgreSQL、旧数据与 Harness ledger 保留、完整 schema/index parity，以及 API 导出 → 共享本地执行核心 mock → 回执/对账 → 隔离接收链。
- 首次实现后测试保留分母夹具失败：应先通过结构校验再验证来源冲突；修正 aggregate 并增加解析器前置断言，没有放宽错误码或来源条件。
- 联合回归 **317 passed / 1 warning，187.18s**；最终标准后端 **13,332 passed / 19 skipped / 11 deselected / 40 warnings，863.98s**，领域 **15 / 58 passed**，Blocking IO **72 passed**。专项/联合/领域包含在相应门禁中，不相加宣称独立覆盖数。
- Ruff check/format **1,276 files**、离线 lock 通过。首次完整门禁在格式阶段发现 `tables.py` 需格式化：保留诊断，仅格式化该文件，重新同步并逐项核对最终源码后才运行上述完整回归；没有删测试、放宽断言或跳过失败。
- 本轮前端运行时代码未变：完整 **155 files / 1,312 passed**、ESLint、typecheck 和整个 frontend Prettier 通过；最终七份公开模块指南另行格式检查。本轮未本地重跑 build/browser/路由性能，不借用前轮结果。
- 最终受测 **1,396** 份 Python/domain/scripts 与 **852** 份 frontend 公开源码逐项与宿主一致；提交归档、证据复制 hash、精确四个 CI 资源收尾与新 SHA Actions 另行闭环。CI 实际触发范围按路径核对，成功 push 不代表 CI 成功。原始红灯/夹具/格式失败和助手命令转义诊断均保留，不改写原始日志或退出标记。
- 本机证据只存 ignored `.deer-flow/ci/20261111-external-quarantine/`，不提交私有配置、数据库或客户资料。

## 未完成与禁止外推

本模块不改变平台 run/review/assessment/report/dispatch/reservation/quota；无执行启用、部署、真实模型/目标调用或新增运行依赖。
独立 [workspace UI 候选](DevPilot_External_QA_Quarantine_Workspace.md) 已通过本轮本地专项/完整门禁，提交与精确 SHA CI 单独核验；外部敏感输出/证据治理、本地输出加密/保留、冻结 QA 调度、失联 Worker 安全、正式批准和授权部署/真实用户验收仍待完成。

## English contract

Persist only separately authorized, immutable **untrusted technical declarations** bound to an explicitly viewed historical complete-baseline export and its frozen plan. All frozen denominators, request budgets, owner/human boundaries and three exact confirmations remain mandatory. A coherent forgery is still NOT_EVALUATED and never evidence, approval or send authority.

Bound each document before UTF-8 inspection and bound the streamed HTTP envelope before buffering. Retain validated canonical technical JSON, not original whitespace or sensitive output. Original declared byte hashes/lengths and canonical hashes are distinct; read-time inspection cannot reauthenticate discarded original bytes.

Perform verification off-loop, recheck the whole source under ordered project/export/plan locks, and atomically append archive/audit. Repeated cancellation drains database reads, writes and thread work before propagating. Unknown writes, including GET 404, reconcile only by GET of the same intake ID; never automatically resend or create a replacement ID. No runtime enablement, deployment, real calls, formal approval or sensitive-evidence import is included.
