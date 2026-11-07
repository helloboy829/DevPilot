# DevPilot 数据库详细设计 v3.0

## 报告草稿切片说明（2026-11-07）

本轮 `/api/reports/preview` 无状态，未新增数据库表/迁移，下载快照不等于持久化修订历史。后续模板版本、报告修订、审阅和产物实体及事务边界见 [报告模块设计第 6 节](DevPilot_报告模块设计.md)。归档上线前必须补独立权限、owner/project 隔离及不可覆盖的审批快照。


> 2026-11-06；第 1 节当前，其余为目标逻辑模型，**尚无对应完整迁移**。复用现有 SQLAlchemy/Alembic，不再假设所有场景已用 PostgreSQL/Milvus。

## 2026-11-07 目标数据模型校准

新版方案、运行快照与 assessment 增 evaluation_mode、scoring_method/权重版本、metric_population、source_snapshot_refs。金标状态与结构合法性分离；预测真实标签关联锚定日、跨度和独立实际值来源。source_snapshot 不保存到通用对话记忆。结果指标保存分子、分母、适用/缺失原因；BASELINE 为 INFO_ONLY，不伪造阈值或 accepted 状态。

这是设计补充，尚无对应新增业务迁移；当前迁移测试仅校验已存在的 3fc2ac02a9d4 组件测试表迁移。[材料依据](DevPilot_历史材料分析与设计校准.md)。

## 1. 当前基线

component_tests 与 component_test_runs 位于 backend/packages/harness/deerflow/persistence/component_tests/，迁移为 3fc2ac02a9d4_add_component_tests.py。当前存对象/参数/摘要，raw/report 为文件；无法表达数据版本、审批、知识权限与整改闭环。api_token 明文/序列化问题必须优先修复。

## 2. 目标关系模型

所有业务对象带 id、owner_user_id、project_id（项目表自身除外）、created_at/updated_at；不可变版本仅 created_at。团队化前不凭 project_id 允许跨 owner 读取。JSON 用于冻结配置/观测扩展，不替代 FK 和授权边界。

| 表 | 关键字段 / 约束 |
| --- | --- |
| eval_projects | name、business_status、final_verdict、revision；owner 索引 |
| eval_submissions | project、submitter、material_artifact_id、validated_fields、revision |
| eval_components / eval_component_versions | logical component、task_type、supplier_version、fingerprint、provenance；版本不可变 |
| eval_endpoint_revisions | component_version_id、request_spec/schema_version/hash、adapter/extractor_version、credential_ref、destination_policy_id；不可变 |
| eval_environment_revisions | project、公共变量、execution_zone、credential_version_ref、destination_policy_revision、hash；秘密独立引用 |
| eval_endpoint_checks | endpoint/environment_revision、request_hash、job_id、check_findings、stream_observability、脱敏artifact_refs、status/timestamps |
| eval_endpoint_confirmations | endpoint/check/environment refs、binding_hash、credential_version_ref、actor、valid_until、revoked_at/reason；不可覆盖 |
| eval_credentials | owner、encrypted_secret / external_secret_ref、key_version；不经通用 to_dict 暴露 |
| eval_source_documents | artifact_id/hash、授权/用途/敏感级别、source_version、retention、deleted_at |
| eval_datasets / eval_dataset_versions | dataset、version、status、manifest_artifact_id/hash、quality_card、revision；unique(dataset_id,version) |
| eval_dataset_cases | dataset_version_id、case_id、input/expected refs、split/slices、origin、source_refs、label_status；unique(version,case_id) |
| eval_plans | revision/status、dataset_version_id、endpoint_revision_id、rubric_ref、effect/perf config、thresholds、budgets、snapshot_hash |
| eval_approvals | subject_type/id/revision/hash、decision、actor、role、comment；审批绑定内容，不能复用到新 revision |
| eval_runs | current_assessment_revision、plan_id、component_version_id、test_type、immutable_snapshot/hash、status、verdict、counts、started/finished、revision |
| eval_jobs | run_id(可空)、kind、status、attempt、lease_owner、lease_until、fencing_token、heartbeat、error_code、cancel_requested |
| eval_case_results | run_id、case_id、执行观测/错误类型、raw_artifact_id、timings、response_hash；每个逻辑 case 一个主观测，有效 outcome 来自 assessment |
| eval_request_attempts | run_id、case_id/request_id、attempt_index、attempt_status、timings、token_source、raw_ref；unique(run,request,attempt) |
| eval_judgments | result_id、revision、judge/rubric/model/prompt refs、verdict、evidence；自动裁判不可变，人工决定另表 |
| eval_review_tasks | kind、subject_type/id/revision/hash、policy_ref/hash、round、required_for_acceptance、status、priority、revision；同轮subject唯一 |
| eval_review_assignments | task_id/round、slot、assignee、status(active/submitted/expired/released)、lease_until、claim_token；独立双审slot |
| eval_review_drafts | task/round/actor、body、revision；可清理暂存，不是正式决定 |
| eval_review_decisions | task/assignment/round、actor、action、reason_code/comment、evidence_refs、subject_hash、supersedes_id；不可变 |
| eval_review_resolutions | task/round、revision、policy/adjudicator、decision_refs、effective_outcome/validity、reason/evidence；不可变 |
| eval_run_assessments | run_id、revision、judgment/resolution_refs、counts/metric_refs、verdict/blocked_reasons、aggregation_version/hash；unique(run,revision) |
| eval_metrics | run_id、assessment_revision_ref(可空)、level/repeat/slice、name、value_nullable、unit、applicability、sample_count、aggregation_version；测量基值不改写 |
| eval_artifacts | content_hash、storage_key、media_type、size、sensitivity、retention、publish_status；路径不由用户直接决定 |
| eval_reports | project_id、template_version、run_assessment_refs、snapshot_hash、artifact_id、status、approved_by、supersedes_id；发布版本不可变 |
| eval_script_exports | endpoint/confirmation_ref、plan_snapshot_ref(骨架可空)、mode、authorized_scope、core/exporter_version、manifest_hash、job/artifact_ref、status |
| eval_external_result_imports | export_id(可空)、upload_artifact_ref、declared_manifest/environment、validation_findings、trust_status、review_approval_ref、external_run_ref；与平台证据隔离 |
| eval_remediations | project_id、issue_refs、responsible_party、status、change_note、new_component_version_id |
| eval_retests | baseline_run_id、new_run_id、scope(full/subset)、comparability、change_refs |
| eval_knowledge_entries | source_refs、scope、sensitivity、status、revision、reviewer、index_version；知识版本可回滚 |
| eval_events / eval_outbox | aggregate_id、seq、event_type、payload、delivery_status；unique(aggregate_id,seq) |
| eval_idempotency_keys | actor/route/key、request_hash、response_resource_id、expires_at；unique(scope,key) |

report.status 为 draft/in_review/approved/published/retired；知识 status 为 candidate/in_review/published/retired。与运行 verdict 不混用。Job 为 queued/running/completed/failed/cancelled/interrupted，取消意图另存；Run 使用规范的完整状态含 cancelling。

## 3. 约束和一致性

- 项目下引用对象必须同 owner/project；复用共享知识走显式授权，不靠跨项目裸 FK。
- frozen dataset/plan 不可写内容；审批 hash、run snapshot hash 对齐。
- case 主 outcome 的五类计数守恒；N=0 pass_rate null；不保存 NaN/Infinity。
- 同一 run 的有效主结果通过 unique/版本指针控制，重复 attempt 不重复计分。
- CaseResult 的执行观测与自动 Judgment 不因人工决定改变；有效 outcome/计数来自指定 assessment，五类计数仍守恒。
- task subject 多态引用由服务端做类型白名单、同 project/owner 和不可变 hash 校验；能建具体 FK 的引用优先 FK，不能只靠用户传 subject_id。
- 每个 review slot 同时仅一个 active assignment，DB 唯一约束/事务原子领取；Decision 校验当前 task round/hash/lease，双审 actor 不重复，历史不覆写。
- 自动解析/仲裁产物、新 assessment、run 最新指针和 outbox 同事务更新；使用 run revision/锁避免并发重算丢失。
- 报告固定引用 assessment；变化只标记需重审和新修订，不原地更新已发布内容。
- claim/lease 需原子更新；每次写结果校验 fencing token，过期 Worker 写入被拒绝。
- 请求外部 API 和 SQL 无分布式事务，不承诺目标 exactly-once；记录 ambiguous outcome。
- 成功发布 artifact 前不能登记报告完成；写失败支持重试和孤儿清理。

## 4. 索引与体积

索引覆盖 (owner,project,created_at)、(status,lease_until)、(run,case)、(run,level,repeat,metric)、(aggregate,seq)。不要一次为任意 JSON 建索引；以查询实测选择。
大响应、图像和轨迹存 artifact，DB 存摘要/hash/ref；敏感内容加密/限制下载。性能逐请求原始样本可分片归档，聚合可从原始记录重建。

## 5. 迁移与回退

1. 备份旧 DB/文件，保留原表；新表以 additive migration 建立。
2. 旧 token 迁入 credential store，使用专用 DTO；验证后清空旧明文，轮换已可能泄露凭据。
3. 旧对象显式导入成 legacy 记录，缺版本/授权/冻结数据不伪造；旧 PASS 不自动升级。
4. 新运行只写新契约，兼容读取层可展示旧记录；避免长期无事务双写。
5. SQLite 与 PostgreSQL 分别迁移/幂等/锁竞争测试；生产降级优先应用回滚，不逆向删除已有新数据。

## 6. 保留、删除与审计

原始业务数据、凭据、报告、匿名经验采用不同保留策略，实际期限由组织确认。删除同时处理 artifact、索引、缓存与访问许可；审计仅保留合法必要的 tombstone，不借不可变之名无限保留隐私数据。备份含删除数据的过渡风险须记录。发布报告按 policy 保留版本，撤销访问不等于改写历史结果。

## 7. 新资源一致性与迁移边界

ReviewTask.status 使用 queued/in_review/escalated/resolved/cancelled；assignment.status 使用 active/submitted/expired/released；Decision/Resolution 是不可变记录而非另外一套 run.status。独立任务的 decision 不以 reviewed=true 代替策略满足状态。对 cancelled/旧 round 的提交拒绝并保留审计。
ExternalResultImport 的 trust_status=unverified/under_review/accepted/rejected；采集/校验 Job.status 独立。accepted 只表示获准按标注的范围采信，不意味 run 或项目 PASS。导出状态复用 Job.status，缺 artifact/manifest 时不能 completed。

增加索引：task(project,status,priority)、task(subject_type,id,hash,kind,policy,round) 唯一；assignment(task,round,slot) 的 active 唯一与 actor 防重复；decision(task,round,actor,created_at)；assessment(run,revision) 唯一；check(endpoint,environment,created_at)、export(project,status)、import(export,trust_status)。跨 SQLite/Postgres 的条件唯一约束由迁移测试验证。
凭据明文不进入 RequestSpec、Confirmation hash 输入的可公开副本或 export manifest；只存版本引用。导出金标授权、外部结果采信与复核访问形成独立 audit 记录，可复用现有可审计事件设施但必须覆盖这些动作。
以上是新增逻辑表，不代表迁移文件已经生成；具体实现与[API](DevPilot_API接口设计文档.md)及[专题](DevPilot_人工复核工作台设计.md)同 PR 落地。
