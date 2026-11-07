# DevPilot 项目组件与提测清单

日期：2026-11-07。本节为已实现切片；不等于冻结执行方案或完整提测工作流。

## 1. 体验流程

入口仍为 `/workspace/datasets`（项目与数据）。先创建项目、导入并自审冻结 QA 数据，然后使用“项目组件与提测版本”：

1. 显式加载清单，从本人在组件测试页已登记的组件中选择，确认类型（LLM、CV、Agent、自研/其他模型），加入当前项目。一个项目可关联多个组件；同一个源组件在同项目只能关联一次。
2. 选择项目组件、填写提测版本名称、选择同项目已冻结的 QA 数据。页面显示服务端组件指纹及数据 revision/hash。
3. 主动确认后创建不可变清单。每个项目组件可有多个版本；同组件的版本名经 NFKC、空白折叠和 casefold 后不得重复。
4. 返回版本 ID、清单 SHA-256、创建者/时间、必要组件库存字段和数据版本。刷新后可重新选择组件读取历史；不依赖浏览器缓存。编辑版本或数据、切换组件、失败或写入后必须重新确认。

这是 **inventory-only** 关联：不锁定 RequestSpec、环境或凭据，不声明 cURL 验证成功，不执行效果/性能调用，不产生 PASS、复核结论或报告证据。当前可绑定的仅是文本 QA 数据，不能因组件类型选了 CV 就宣称图片评测已支持。

## 2. 服务端事实与安全边界

- 只接受 `source_component_id` 与类型，不另建一份由用户自由填写的重复组件配置。每次读取/创建均校验项目、组件来源与当前用户归属；项目组件、数据、版本路径也必须同项目。无团队共享或管理员跨 owner 入口。
- 候选查询在 SQL SELECT 层只取 ID、名称、transport、response_mode、supports_streaming、validation_type。**不加载、不复制**旧组件的 `api_url`、`api_token` 或任意 `acceptance_criteria`。这不代表旧组件 API 的凭据问题已被本轮全局修复；旧入口仍是待迁移原型。
- 创建提测清单时，核对服务端当前库存指纹、数据 frozen 状态、revision、hash、非空；重新校验持久 QA 行和独立金标并重算 hash，不将金标返回或提供给模型。安全库存字段变更、过期或篡改数据会拒绝。
- 请求只接受白名单字段；确认必须是 JSON `true`，不能是数字或字符串。客户端不能指定快照、hash、scope、创建者或创建时间。版本名最多 80 字符，规范化后最多 240 字符，拒绝控制字符。
- 服务端生成 `component-inventory.v1` 快照与 `submission-inventory.v1` binding；范围固定为 `inventory_only`。hash 为 canonical JSON 的 SHA-256，不是签名，也不能防止拥有直接数据库写权限者篡改。
- 旧源组件字段后续改变不改写已有清单；删除源组件不级联删除清单，但已删除来源不能创建新版本。没有修改/删除清单 API，纠错另建版本。源 ID 不建立跨层外键。
- 元数据审计与新增记录在同一事务内提交，唯一约束处理重复/并发；审计仅保存 ID、actor、action、时间，不保存名称、请求、样本或快照。
- 仍采用当前 owner 自审，不是独立审批。受信任内部 Agent 不可提交人工确认；持有效用户凭据的外部自动化不能可靠区分为真人。没有模型、网络发送或新 Agent 工具。
- 前端只保存在页面内存，响应 `private, no-store`；不放入 URL、localStorage、持久查询缓存或聊天。失败明确显示，不伪装成空清单，不自动重试写入。

## 3. 实际 API

前缀 `/api/evaluation/projects/{project_id}`；权限均为 `evaluation_projects:*`。

| 方法与相对路径 | 权限 | 内容 |
| --- | --- | --- |
| GET /component-candidates | read | 本人已登记组件的安全库存字段和指纹 |
| GET /components | read | 当前项目组件关联 |
| POST /components | write | `{source_component_id, kind}` |
| GET /components/{component_id}/submissions | read | 当前组件的不可变版本列表 |
| POST /components/{component_id}/submissions | write + review | `{version_label, dataset_id, dataset_revision, dataset_hash, component_fingerprint, confirmed:true}` |
| GET /submissions/{submission_id} | read | 同项目的清单快照，不含金标/请求凭据 |
| GET /registry-audit | review | 关联与版本创建的操作元数据（本轮无专用审计 UI） |

401 未认证；403 无权限/受信任内部 Agent 禁止确认；404 不存在或非本人/不同项目；409 重复、过期、不满足冻结条件或持久内容 hash 不一致；422 非法输入；503 数据仓储不可用或数据库操作失败。共用 QA 路由的请求大小与异常脱敏边界，不返回 SQL 参数或输入原值。

## 4. 分层与数据库升级

- `app.evaluation.registry`：严格输入契约与 canonical 指纹。
- `app.evaluation.registry_repository`：业务校验、快照和事务。允许 App 读取 Harness 旧组件模型，禁止 Harness 反向导入业务。
- `app.evaluation.tables`：自有 metadata，新增 `evaluation_project_components`、`evaluation_submissions`、`evaluation_registry_audit`。
- 新迁移 **eval_0002** 链接已部署的 eval_0001；独立账本仍为 `devpilot_alembic_version`，不修改 Harness 账本。旧 eval_0001 文件保持不变。
- 数据集增加 `(project_id,id)` 唯一索引；提测表通过复合外键限制项目组件和数据集来自同一项目。版本规范化键唯一；scope 使用 CHECK。没有跨项目更改接口。
- Gateway 启动沿用 App 迁移锁与脱敏错误边界。SQLite 已有从含冻结数据的 eval_0001 升级、重启、并发唯一性、外键和旧账本保持测试。真实 PostgreSQL 部署验收仍待完成。
- 升级前执行数据库在线备份。回退代码/镜像时保留新增表及独立账本，不自动 downgrade 或删卷。

## 5. 验证与下一切片

后端回归覆盖 owner/子资源隔离、字段白名单、服务端快照、重复与并发、draft/stale/tampered 数据、金标不回传、严格确认、版本键长度、事务审计与部署迁移。浏览器覆盖完整关联/创建流程、确认撤销、503、无浏览器持久化及移动端布局；仅使用合成数据。最终结果记录在 [CI 文档](DevPilot_CI修复与隔离开发环境.md)。

接下来先建立统一 RequestSpec 与秘密引用、脱敏调试确认及请求版本，再把提测清单升级为真正可冻结执行的方案；随后接耐久任务、观测/指标、人工结果复核与报告证据。不可直接把本轮清单作为已批准执行计划，也不可拿手工报告草稿冒充清单的实测结果。
