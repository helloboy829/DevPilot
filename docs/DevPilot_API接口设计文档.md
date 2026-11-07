# DevPilot API 接口设计 v3.0

## 报告 Agent 增补（2026-11-07）

已实现可选报告助手：GET `/api/reports/assistant` 需要 threads:read，只查询配置；POST 同路径需要 threads:write + runs:create 和 `consent:true`。返回未核验建议及事实 hash/模板绑定，422 输入/授权确认，503 未启用/模型未配置，429 并发槽满，504 超时，502 供应商/输出错误。preview 可选 advisory（结构化建议、模型名、事实 hash、模板 ID/版本、human_confirmed:true）；不匹配拒绝，附录 source 为 client_supplied_ai_advice_unverified，不构成审批或来源认证。全部成功及业务错误 no-store，详细边界见 [报告设计](DevPilot_报告模块设计.md#9-已实现可选报告-agent2026-11-07)。

## 已实现：无状态报告草稿（2026-11-07）

独立于本文其余目标 API：`GET /api/reports/templates`（登录 + threads:read）；`POST /api/reports/preview`（登录 + threads:write）。请求显式 `template_id`、`template_version`、`facts`，响应 `DRAFT/manual_unverified`、事实/模板快照、derived、manifest 和 markdown；业务校验失败 422，未知模板不回退 latest。生成者/UTC 时间取服务端，不接受客户端伪造核验/审批状态。不持久化，无报告 ID/发布/审批/模板上传接口，无数据库迁移；版本/hash 不是审批证明。完整字段与限制见 [报告模块设计](DevPilot_报告模块设计.md)。


> 2026-11-06。第 1 节为当前；其余均为**目标 API，待开发**，不能直接当成现有端点。状态/指标遵循[规范](DevPilot_数据集与指标规范.md)。

## 2026-11-07 目标计划/结果契约补充

新版 /api/evaluation 的计划和运行快照必须显式携带 evaluation_mode（BASELINE/ACCEPTANCE）、scoring_method、metric_population、source_snapshot_refs。ACCEPTANCE 的批准阈值缺失返回验证阻断；BASELINE 返回 INFO_ONLY 及限制，不返回总体 PASS/FAIL。case outcome 与总体 assessment verdict 分离；结果分别暴露 case_pass_rate、rubric_score、contract_valid、value_verified 及其分母/不可用原因。不得给旧 API 悄加默认阈值或将旧报告重新标成新标准通过。

这些字段仍是目标设计，不表示当前 router 已接受它们。[业务依据](DevPilot_历史材料分析与设计校准.md)。

## 1. 当前实际接口

router：backend/app/gateway/routers/component_tests.py。

| 方法 | 当前路径 | 说明 |
| --- | --- | --- |
| GET / POST | /api/component-tests/components | 列表/创建 |
| GET / PATCH / DELETE | /api/component-tests/components/{component_id} | 详情/编辑/删除 |
| POST / GET | /api/component-tests/components/{component_id}/runs | 提交 effect/perf / 历史 |
| GET | /api/component-tests/runs/{run_id} | 状态与摘要 |
| GET | /api/component-tests/runs/{run_id}/report | JSON 报告 |

当前传输：openai_chat、dify_chat、dify_workflow、http_post；不能据此推断已有任意 CV/multipart/cURL 导入。
接口目前允许的 validation_type 多于真正实现的类型，需按审计 F03 修复。旧 API 不自动拥有新版审批/数据冻结保证。

## 2. 新版统一约定

前缀 /api/evaluation。复用现有认证，所有资源通过服务端身份解析项目权限；不接收客户端 user_id 充当授权依据。当前 owner 隔离基础上扩展项目角色须显式建模。
JSON schema_version 固定；时间 UTC ISO8601，单位写入字段名；NaN/Infinity 拒绝；分页 cursor/limit 且限额。列表返回 items/next_cursor，详情返回资源对象，不另套 data。
PATCH 带 If-Match/expected_revision；冲突 409。创建执行/导入/通知等副作用请求带 Idempotency-Key；同键同 body 返回既有结果，同键异 body 为 409，scope 绑定 actor/route。

## 3. 目标资源与动作

| 方法 / 相对路径 | 作用与约束 |
| --- | --- |
| GET /capabilities | 返回可用 transport、任务/validator、上限、UI 能力；只能声明实际实现 |
| POST /projects；GET /projects/{id} | 创建/查询项目 |
| POST /projects/{id}/submissions | 结构化材料或受控上传引用；先校验后提交 |
| POST /projects/{id}/component-versions | 新被测版本，保存提交方版本和指纹可信度 |
| POST /projects/{id}/endpoint-revisions/parse-curl | 无网络纯解析；拒绝 shell/不支持 flags；不在响应回显秘密 |
| POST /projects/{id}/endpoint-revisions | 保存不可变 RequestSpec 与 credential_ref；保存不等于确认 |
| POST /endpoint-revisions/{id}/checks | 批准目的地后异步单次接入检查；非压测 |
| POST /projects/{id}/sources | 授权来源/文件登记；扫描隔离后可用 |
| POST /projects/{id}/datasets | 建立数据集；导入生成新版本 |
| POST /datasets/{id}/versions | 以结构化记录/受控 artifact 创建草案 |
| POST /dataset-versions/{id}/generation-jobs | 仅生成候选；预算/来源用途校验 |
| GET /dataset-versions/{id}/quality | 质量卡/缺项/来源/切片 |
| POST /dataset-versions/{id}/reviews | 整体质量批准/驳回；单条标签走 review-tasks，不能替代整体审批 |
| POST /dataset-versions/{id}/freeze | 仅 approved 版本，计算 manifest hash |
| POST /projects/{id}/plans | 方案草案；效果/性能独立设置 |
| POST /plans/{id}/reviews；POST /plans/{id}/freeze | 审批和冻结；更改内容使审批失效 |
| POST /projects/{id}/runs | 引用冻结计划、组件版本和 test_type |
| GET /runs/{id}；GET /runs/{id}/cases | 执行/验收分离；case 分页返回原观测引用、effective_outcome 与 assessment_revision |
| POST /runs/{id}/cancel | 幂等取消请求，先 cancelling 后终态 |
| GET /runs/{id}/events | 业务 SSE，非 LangGraph token 协议 |
| POST /runs/{id}/judgment-revisions | 用指定规则/裁判对已保存观测重判；人工决定走 review-tasks；均保留旧结论 |
| POST /projects/{id}/reports | 基础/正式报告草稿，引用运行与模板版本 |
| POST /reports/{id}/reviews；POST /reports/{id}/publish | 审批/发布；版本与证据不齐阻断 |
| POST /projects/{id}/remediations | 问题/责任方/整改说明/复测关联 |
| POST /projects/{id}/retests | 新组件版本+旧冻结基准；创建新 run，不覆盖旧 run |
| POST /projects/{id}/knowledge-candidates | 候选知识，复核后才能发布 |
| GET /jobs/{id}；GET /artifacts/{id} | 任务进度/权限下载；不暴露文件系统路径 |

check/generation/import/report 等后台操作返回 202 + job_id/status_url；提交 run 返回 202 + run_id/status。不得返回 200 然后默默排队而无资源 ID。

资源查询：projects/components/component-versions/datasets/dataset-versions/plans/runs/reports/remediations/knowledge-entries 提供权限过滤的 GET 列表和 GET /{id} 详情；可按 project_id 筛选，统一分页，不接收 owner 覆盖。

生命周期：数据、计划、报告提供 submit-review 动作进入 in_review，reviews 才提交 approve/reject。批准前不能 freeze/publish；退回创建修订；知识候选需 reviews 后 publish，同样绑定 hash。
文件：POST /projects/{id}/uploads 受限上传到隔离区，校验后返回 artifact_id；POST /sources/{id}/ingestion-jobs 异步解析；POST /datasets/{id}/import-jobs 导入候选版本。扫描失败不可冻结，不复用无关 thread 上传权限。

## 4. 执行契约示例

~~~json
{
  "schema_version": "1.0",
  "plan_id": "plan-qa-v1",
  "component_version_id": "cv-20261106",
  "test_type": "effect"
}
~~~

服务端从冻结计划读取 dataset_version_id、endpoint_revision_id、rubric、限额、阈值；不接收客户端临时 params 绕过审批。复测允许选已批准的新组件版本，endpoint 如变化须新修订/接入确认；快照记录差异。

~~~json
{
  "run_id": "run-001",
  "status": "completed",
  "verdict": "NEEDS_REVIEW",
  "snapshot_hash": "sha256:example",
  "counts": {"total": 100, "pass": 90, "fail": 5, "error": 0, "pending": 5, "not_run": 0},
  "pass_rate": 0.9,
  "blocked_reasons": [],
  "assessment_revision": 2,
  "required_review_open_count": 5,
  "revision": 7
}
~~~

该例为待复核，0.9 只是暂时观察值，不能因达到门槛就提前 PASS。artifact/hash 的 example 仅说明格式，不是真实有效 hash。

## 5. 审批与错误

审批请求含 subject_revision、decision(approve/reject)、comment；服务端校验 actor 权限及版本。Agent 只能创建待审批事项，无 approve 权限。负载许可记录目的地/最大并发/时段/费用，过期不可启动。

错误体：error.code、error.message、error.field_errors、error.request_id，不返回栈、token 或内部路径。
400 无法解析；401/403 鉴权；404 不存在或无可见性；409 revision/idempotency/冻结冲突；413 文件/请求过大；422 schema/不支持能力/指标不适用；429 配额/队列满；503 依赖暂不可用。
资源存在但证据不齐时返回其 verdict/blocked_reasons；只有尝试非法流转时拒绝请求，不能把所有 BLOCKED 都变 500。

## 6. 安全与兼容

cURL 只做解析，不调用系统 curl；凭据提取后存 credential_ref，响应返回 has_credential 和掩码，不能回传明文。默认 TLS 校验，禁止客户端设置 verify=false 绕过策略。文件仅引用已授权 artifact。
保留 legacy API 读取，逐步迁移创建入口；历史结果标 legacy/unverified。新版统一强类型 schema 逐步从 devpilot 导出并用于 OpenAPI、前端 types 和契约测试。

## 7. 接口调试与脚本导出资源（目标）

以下均在 /api/evaluation 下，沿用权限/分页/revision/idempotency 契约；人和 Agent 调用相同服务，Agent 无权自行批准目的地或确认。

| 方法 / 相对路径 | 作用与前置条件 |
| --- | --- |
| POST /projects/{id}/environment-revisions；GET /environment-revisions/{id} | 受控环境/非秘密变量、Worker 执行域、credential 版本引用；secret 不回显 |
| GET /endpoint-revisions/{id} | 声明式请求、输入绑定、提取/流规则；只返脱敏配置 |
| POST /endpoint-revisions/{id}/checks | 单次有界发送，引用 environment revision/受控样例；202 返回 check_id/job_id |
| GET /endpoint-revisions/{id}/checks；GET /endpoint-checks/{id} | 脱敏请求/响应、各层检查与首内容可观测性；不是压测结果 |
| POST /endpoint-checks/{id}/cancel | 请求取消单次检查，保留已发生副作用/不确定性 |
| POST /endpoint-revisions/{id}/confirmations | 校验匹配且成功的 check、内容 hash/环境、actor 权限；创建不可变确认 |
| POST /endpoint-confirmations/{id}/revoke | 显式撤销，不删除历史；版本改变/过期同样使确认不可用于新执行 |
| POST /projects/{id}/script-exports | mode=skeleton/executable；202 返回 export_id/job_id；可执行模式须冻结计划和对应接入确认、导出授权 |
| GET /script-exports；GET /script-exports/{id} | 状态、版本、manifest、自检/授权范围、下载 artifact_ref；列表按权限过滤 |
| POST /script-exports/{id}/cancel | 未终结生成 Job 取消；已下载工程无法靠此远程停止 |
| POST /projects/{id}/external-result-imports | 受控上传引用、export_id/manifest、环境与来源声明；202 返回 import_id/job_id，先隔离验证 |
| GET /external-result-imports/{id} | 导入检查与 external/unverified 标识；不会覆盖平台 run |
| POST /external-result-imports/{id}/reviews | 人工批准采信/拒绝，记录理由/范围；批准采信不等于免除其他验收门禁 |

script export 状态沿用 Job 的 queued/running/completed/failed/cancelled/interrupted；只有完整产物+manifest+生成自检齐备才 completed。mode=skeleton 不承诺具备全部数据或可完成验收，响应显式返回 missing_prerequisites；mode=executable 不满足条件直接 422/403，不能偷偷降级为空壳。
capabilities 新增支持的 RequestSpec schema/stream protocols/exporter 组合/验证环境、允许数据范围与 review kinds；实现未验收不得宣称支持。

导出请求例见[script-export-request](templates/script-export-request.example.json)，RequestSpec 例见[request-spec](templates/request-spec.example.json)。它们是待实现契约样例，不是当前 API 可执行配置。

## 8. 人工复核资源与修订（目标）

| 方法 / 相对路径 | 作用与前置条件 |
| --- | --- |
| POST /projects/{id}/review-tasks | 人/服务按冻结策略创建单条/有限批任务；唯一 subject hash+kind+policy+round，重复不重复计分 |
| GET /review-tasks | 我的/可领/待仲裁、组件/版本/run/slice/risk/kind 等过滤与分页；不越权返回 expected |
| GET /review-tasks/{id} | Q/A/expected/来源引用、task revision、可用动作、权限与盲审后的决定；仅返回有权数据 |
| POST /review-tasks/{id}/assignments | 获权负责人分配独立 reviewer slot；单人首版可仅支持自领 |
| POST /review-tasks/{id}/claim | 原子领取可用 slot，返回 assignment_id、lease_until、task_revision；并发冲突 409 |
| POST /review-assignments/{id}/renew；POST /review-assignments/{id}/release | 续领/释放，校验身份、有效期、revision；过期不允许提交 |
| PUT /review-tasks/{id}/draft | 仅当前 actor 的暂存意见，幂等且独立 revision；不改变 outcome/覆盖率 |
| POST /review-tasks/{id}/decisions | 不可变提交，带 assignment_id、expected_revision、subject_revision/hash、action/reason/evidence；后端定 actor |
| POST /review-tasks/{id}/adjudications | 授权仲裁、引用冲突决定；满足仲裁条件后由 resolver 生成 Resolution |
| POST /review-tasks/{id}/reopen；POST /review-tasks/{id}/cancel | 有权人显式修订/撤回，保存原因与历史；重开后新增决定，不覆盖旧决定 |
| GET /review-tasks/{id}/history | 访问/分配/决定/仲裁/重开历史；盲审隐藏其他人内容，权限敏感字段过滤 |
| GET /runs/{id}/assessments；GET /runs/{id}/assessments/{revision} | 不可变的计数/指标/verdict/判断引用集合；当前 run 仅缓存最新 revision 指针 |
| GET /projects/{id}/events | 项目级授权 SSE，覆盖调试/导出/复核/报告；重放/去重遵循事件规范 |

ReviewTask kind=dataset_label/case_judgment/measurement_validity；status=queued/in_review/escalated/resolved/cancelled。每种 action 及状态约束按[复核设计](DevPilot_人工复核工作台设计.md)；例如技术 ERROR 送来 action=pass 必须 422 REVIEW_ACTION_NOT_APPLICABLE。资料不足可以完成一份 Decision，但不能自动 resolved 为 PASS。
claim/submit 使用幂等键；变更同时检查 task revision、assignment lease、subject hash/round。已提交决定可通过 reopen+新决定修订；无权限自批/仲裁为 403。报告生成请求必须引用 assessment_revision，不能只引用会变的 run_id。

dataset-versions/{id}/reviews、plans/{id}/reviews、reports/{id}/reviews 是整体 Approval；ReviewTask 决定不能越级成为这些 Approval。人工提交例见[review-decision](templates/review-decision.example.json)。

## 9. 已实现更新：模型连接与报告多轮（2026-11-07）

模型管理 model 增 provider_name、parameters 和只写 clear_credential；provider 支持 openai_compatible、openai_responses、anthropic、gemini。parameters 仅接收 temperature/top_p/max_tokens/timeout_seconds/max_retries。变更 endpoint/protocol 时必须重填或明确清除旧凭据；PUT 仍校验 revision、admin，返回不含 api_key。

POST /api/reports/project/intake 向后兼容不带 history 的旧请求；新增 history: [{message, proposal}]，最多 9 个已完成往返，当前轮使总数不超过 10，序列化上下文不超过 24000 字符。proposal 只允许 title/project_name/components/questions，拒绝任意 role、指标或额外字段。每轮 consent=true 且 threads:write+runs:create，返回 round、conversation_persisted=false；历史不持久、不被当作证据。参见[当前实现矩阵](DevPilot_实现进度与下一步.md)。
