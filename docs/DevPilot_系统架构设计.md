# DevPilot 系统架构设计 v3.0

> 2026-11-06；当前与目标分开说明。业务口径以[数据集与指标规范](DevPilot_数据集与指标规范.md)为准。

## 1. 当前架构

Nginx:2026 → Next.js:3000 / FastAPI Gateway:8001；Gateway 内嵌 DeerFlow LangGraph runtime。
组件测试 router → ComponentTestService → devpilot.toolkit → 目标 API；SQL 保存摘要，本地文件保存 raw.json/report.json。
这一执行路径已有，不意味着 Agent 已自动完成提测和数据构建。完整问题见[现状审计](DevPilot_现状审计与修复清单.md)。

## 2. 目标：模块化单体 + 独立执行 Worker

~~~text
评测工作台（项目/调试/数据/方案/运行/复核/报告） + 上下文助手
                  │ REST + 业务事件 SSE
FastAPI 业务层：权限/版本/审批/任务/证据/凭据引用
    ├── DeerFlow Agent：规划、生成候选、检索、解释、报告草稿
    ├── 领域核心 devpilot：RequestSpec/adapter、数据检查、裁判、指标、结果模型
    ├── 导出服务：受控模板 + 同版本核心 → 独立测试工程（不打包 Gateway）
    ├── 复核服务：任务/分配/决定/仲裁 → 新 assessment → 报告修订
    └── 持久化 Job → 有界 Worker → 经批准的目标 API
                  │
      SQL（业务真相）+ Artifact Store（不可变证据）
                  │
      审核知识索引（权限过滤，可选向量检索）
~~~

首版允许 Gateway 与 Worker 同部署进程，但必须 DB 持久化/租约/恢复；生产压测宜独立进程，避免负载影响交互和 Agent。后续扩容不需要改业务契约。

## 3. 层次与依赖

- backend/app：router、鉴权、业务服务、Job/Worker 调度、DeerFlow 工具适配与审批。
- devpilot/src/devpilot：领域 schema/数据质量/判定/性能统计/transport/报告结构，不依赖 app 或 DeerFlow。
- backend/packages/harness：通用 Agent/模型/工具/沙箱/运行设施；不得反向导入 app 或 devpilot 业务逻辑。
- backend/packages/extension-api：公共扩展契约；插件由 operator 配置加载。

**App → Harness / App → devpilot**；App 把模型调用以 callable/协议注入纯核心。既有 runner 的懒导入兼容暂留，逐步迁移，不扩大反向耦合。
现有 component_tests ORM 位于 harness 属历史落点；新领域表优先业务层，迁移复用现有 engine/session/Alembic，不在一次重构中移动全部旧表。

## 4. 关键边界

- Agent 建议不能直接改已冻结数据、阈值、凭据、外网权限或发布结论。
- 工具返回类型化 ID、摘要、阻断原因；不向模型灌入海量 raw/图片/密钥。
- Job 与 Run 在业务 DB 持久化；LangGraph checkpoint 负责助手上下文，不替代 Job 状态。
- 执行观测、裁判结果与验收判定分层；重判/重算不重复调目标。
- 性能采样独立于 LLM 编排，循环中不调用 Agent 逐个发请求。
- 调试请求同样经 Worker 出站控制；人和 Agent 共享 RequestSpec，不从浏览器直连被测接口。
- 接入检查/确认、平台运行、导出绑定相同版本语义；导出不复制另一套统计算法。
- 复核任务服务与聊天/runtime 解耦；原始观测、自动判断、人工决定和解析后结果分层。

## 5. 执行与一致性

提交事务创建不可变 run snapshot、job 和 outbox 事件；Worker 原子 claim、持有 fencing lease、心跳；租约失效旧 Worker 不得覆盖新结果。
效果按 case/attempt 写证据，恢复仅重试明确允许的未完成项；目标副作用无法保证 exactly-once，Agent 场景默认不自动重放。
性能任务重启标 interrupted，新 run 重开完整测量窗，不拼接压测。
DB/文件无法同事务：临时写→校验 hash→原子发布→登记 manifest；失败留下可清理孤儿，不能宣称报告成功。

## 6. 数据与技术选型

本地 SQLite + 文件存储；多人/并发 Worker 推荐 PostgreSQL；Redis 仅作为后续通知/速率限制/队列优化，非真相源必选项。
检索先结构化元数据和全文；验证召回需求后选 pgvector 或专用向量库，**Milvus 非 MVP 前提**。不先引入微服务和九个常驻 Agent。
外部压测器以可选 backend 接口集成：workload → 执行器 → 原始观测 → 统一指标，未完成等价性校准前不能混算。

## 7. 安全与可观测性

身份/资源权限→输入校验→目的地策略→凭据注入→有界执行→脱敏证据→发布审批。私网目标可由管理员授权；默认 TLS 验证，支持受信企业 CA。
日志关联 project/run/job/attempt/trace，指标记录 Worker 负载、成功/错误、队列、租约和预算；输出/来源视为不可信数据，防 prompt injection。

## 8. 兼容迁移

保留 /api/component-tests 为 legacy；新领域走 /api/evaluation。旧运行保留历史事实和 legacy/unverified 标记；显式重跑后才能生成新版 verdict。新导航渐进切换，保留聊天兼容入口；迁移附备份和回退，不立即删除上游模块。

## 9. 新增领域服务与执行边界

目标代码落点：app 中增加 endpoint-debug/export/review 应用服务及有界 Job；devpilot 中增加 RequestSpec、共享 runner、导出模板、review resolver 和 assessment schema。具体包名由实现 PR 确定，不提前声称目录已经存在。

- EndpointCheck 是一次有预算的接入观测，Confirmation 是绑定内容的人工确认，两者不等于压测批准。
- ScriptExport 读取已授权的冻结快照生成 artifact，独立于平台部署可运行；外部结果走隔离导入，不能冒充 Worker 认证结果。
- ReviewTask 指向明确 subject revision/hash，HumanDecision 不覆盖 Judgment；事务生成新 Resolution/RunAssessmentRevision、指标与 outbox。报告绑定特定 assessment，变化后重新审签。
- 项目级业务 SSE 承载调试/导出/复核待办变化；run SSE 保持运行事件，不把目标 SSE、助手 token 和工作台业务通知混成一条协议。

详见[调试与导出](DevPilot_接口调试与脚本导出设计.md)、[复核工作台](DevPilot_人工复核工作台设计.md)。
