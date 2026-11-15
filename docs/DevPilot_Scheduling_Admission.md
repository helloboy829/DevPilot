# QA 调度准入只读诊断 / Scheduling admission diagnostic

2026-11-15。新增 `app.evaluation.scheduling_safety.scheduling_admission` 与 `GET /api/evaluation/operations/scheduling-admission`：明确当前**没有**将 legacy scheduler 绑定到已准入 QA 执行链的版本化合同。该接口只返回固定拒绝投影与阻塞原因，不调度、不释放、不重试、不发送。

## 范围

- legacy scheduler 仍只覆盖 component tests；它不是 QA 链准入，也不能被复用来绕过独立准入。
- 没有版本化准入合同、没有旧 Worker 不可再发的证明、没有配额释放/回收/重调度授权。
- 端点要求实际认证的**人类管理员**且具备独立 `evaluation_operations:read` 权限；内部 token、非管理员与匿名请求均被拒绝。响应 `private, no-store`。

## 固定输出（`qa-scheduling-admission.v1`）

```json
{
  "schema": "qa-scheduling-admission.v1",
  "scope": "qa_scheduling_admission_diagnostic_only",
  "scheduler_scope": "component_tests_only",
  "qa_chain_admitted": false,
  "dispatch_authorized": false,
  "release_authorized": false,
  "blockers": [
    "no_versioned_admission_contract",
    "scheduler_not_bound_to_qa_execution",
    "worker_liveness_not_established"
  ]
}
```

- 每次调用返回独立列表副本；修改返回值不影响后续调用。
- 不读取数据库、执行仓库、配额、Worker、配置、证据或 key；没有可变的授权状态。

## 未来准入前提（本切片未实现）

至少需要：版本化调度合同、目标/数据/操作员授权绑定、旧 Worker 不能发送的证据与 fence、CAS/竞争与取消语义、配额处置和独立审计。无法证明时保持阻塞；未知请求绝不重发，不能以 deadline 或历史健康代替证明。

## 运维工作台展示

`/workspace/operations` 在执行预留诊断下方提供独立的“加载调度准入诊断”按钮：只有管理员身份渲染，点击后才通过既有 authenticated fetcher 以 GET + `no-store` + AbortSignal 读取固定端点。`core/evaluation/scheduling-admission.ts` 使用共享有界 JSON 读取器（成功 JSON MIME、声明与实际流均 ≤16 KiB、严格 UTF-8），并以 strict schema 校验固定 scope、`component_tests_only`、三个 literal `false` 与固定 blocker allowlist（不重复）；未知字段、类型伪装、越界或篡改一律失败关闭。错误只显示通用文案，不读取或反射响应 body，不自动重试；切换账号、角色、auth refresh 或卸载时 abort 并在 await 后 fence 旧结果，页面不持久化快照。

该展示只是诊断读取，不新增释放/调度/重试控件，也不改变服务器 admin + `evaluation_operations:read` 的安全边界。

## 明确不包含

- 无调度、释放、回收、重排队、重试、发送、执行或开关变更；无迁移、依赖、部署或真实调用。
- 不把该端点作为批准、验收或 Worker 存活证明；管理员读取也不授予项目/证据权限。

## 验证

```sh
cd backend
uv run pytest tests/test_scheduling_admission.py -q --tb=short
```

覆盖固定投影、返回值隔离、管理员+显式权限 200/`no-store`、缺权限/内部 token/非管理员/匿名拒绝、仅 GET（POST 405）。前端工作台展示由 `tests/unit/core/evaluation/scheduling-admission.test.ts`、`execution-operations-panel.dom.test.tsx` 与 `tests/e2e/execution-operations.spec.ts` 覆盖。

English: a fixed read-only projection states that QA-chain scheduling is not admitted, keeps the legacy scheduler scoped to component tests, and never authorizes dispatch, release or retry. The operations workspace reads it only on an explicit admin click with strict bounded validation and no retry; it is a diagnostic, not a scheduling contract or liveness proof.
