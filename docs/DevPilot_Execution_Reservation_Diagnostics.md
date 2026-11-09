# QA 执行占用只读诊断 / Read-only execution reservation diagnostics

日期：2026-11-10。状态：候选后端/API，不部署、不启用执行，不是失联 Worker 已可安全回收的声明。

## 目的与边界

运行中取消/过期的已领取 Worker 会保留全局配额，直至原 Worker 排空并完成收尾；超时不能证明旧进程或远端业务已经停止。新增诊断让明确授权的人类管理员读取**全局技术合计**，而不是手工修改执行行或盲目重发。

仅新增 `GET /api/evaluation/operations/reservations`。没有释放、expire、reclaim、requeue、retry、取消、执行、写策略或修改阈值 API，没有 UI 轮询、调度器、后台修复或重试。现有 owner 取消/Worker 生命周期和未知写入同 ID GET-only 保持原样。

## 认证与隐私

- 必须实际认证、`system_role=admin`，且具备独立的 `evaluation_operations:read` 路由权限。已启用的 RBAC 要明确授予此权限（或既有明确通配规则）；read/write/review 项目权限不隐含此权限。
- 即使有管理员 cookie，内部 token/内部来源/内部角色信号仍拒绝。普通 owner、审阅人或仲裁人即使被授予此路由权限也不能通过管理员门禁。
- 既有禁用授权的开发策略不变，仍保留人类管理员门禁。此模块不改变账号角色、授权配置、操作员开关或生产 secret。
- 只返回计数/保留并发/字节与当前服务进程策略；不返回 owner/project/run/plan/assessment ID、来源 hash、claim token/hash、端点、key、Q/A/gold、密文、笔记或个案细节。诊断权限不授予任何项目或敏感证据访问权。
- 路由的成功、拒绝、服务/DB/无效时钟错误均 `private, no-store`；全局认证中间件可能在进入路由前返回既有匿名 401，其响应边界不由此路由更改。持久化错误只记录通用警告，不回显 SQL/参数。

## 快照合同

`app.evaluation.execution_diagnostics.reservation_snapshot` 只对 `evaluation_executions.reservation_held = true` 发出**一条聚合 SELECT**，无需 guard 初始化、不取锁、不调用过期扫描、不读任何密钥或证据表、不写审计/执行/guard。空集返回显式整数零；不是缺失证据自动按零质量指标处理。

| 字段                                                                                     | 含义与限制                                                                                                                         |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `scope`                                                                                  | 固定 `execution_reservations_diagnostic_only`，不是配额许可或批准                                                                  |
| `observed_at_ms`                                                                         | 查询前读取的服务进程时钟；不是锁定全局状态/最新承诺，也不能证明 Worker 心跳                                                        |
| `policy_scope` / `policy`                                                                | `serving_process_only`；当前进程的已校验显式策略，不证明其他 Worker/guard 策略一致，不返回 allowlist/config/key                    |
| `reservations`                                                                           | 当前仍占用的运行数、保留并发/body/response 字节和截止时刻已到的运行数；不是实际流量、可用槽位或安全释放量                          |
| `states`                                                                                 | queued/running/cancel_requested/collected/interrupted 每种状态的占用数、其中 deadline 已到数；保留所有占用状态，不筛掉 interrupted |
| `worker_liveness`                                                                        | 一律 `not_established`；deadline 到达、零计数或 collected/interrupted 状态都不是进程死亡证明                                       |
| `release_authorized` / `reclaim_authorized` / `retry_authorized` / `dispatch_authorized` | 一律 `false`；重新读取不会授予变更或发送权力                                                                                       |

同一 SQL 语句中的合计来自数据库语句快照；返回后即可过时，不将多次读取拼成事务级资源证明。无自动刷新。策略被禁用或与持有配额时的策略不同，仍可观察合计但绝不重写 guard/配额。不会把超过当前进程上限的合计裁剪成上限，也不推算“可释放/可重试”。

## 确定性验证与退出门禁

- 临时迁移 SQLite 中实际 admit/claim/cancel/expire/原 claim finish：观察 queued、running、取消等待、到期但未 terminalize、到期 interrupted、队列释放、原 Worker 收尾，逐表比较前后状态/审计不变。
- 两个占用的全局合计、边界时钟 `deadline == now`、空集、禁用/变更当前进程策略及 guard 不变；SQL 观测断言一条 SELECT、不含 owner 条件、claim/证据列/连接/锁。
- 复用真实密码/JWT/CSRF/RBAC 的五账号 fixture：DB 角色提升仅为合成准备，非身份中间件；管理员显式权限、deny 优先、普通用户与内部 token 拒绝、项目不可访问、无发送、敏感 canary 不泄漏。
- DB/时钟故障通用失败；路由只有 GET，写方法 405、释放/reclaim 等伪造路径 404。初始测试错误与最终日志分别保留，不改运行认证行为、时间或重试。
- 标准后端/领域全量、Blocking IO、Ruff/离线锁、完整 frontend Prettier 与模块 Markdown；精确源码快照、日志导出逐项 hash；每次新提交的实际 Actions 单列，不继承上一 SHA。

只使用公开源码/冻结锁文件和专用隔离 CI；没有私有配置/数据库/真实账号、生产启动、PostgreSQL 现场验收、HTTP/TLS 浏览器行为或真实模型/目标。最终命令/结果与精确 SHA 记录见[交付矩阵](DevPilot_Delivery_Status.md)。

## 本次本地验证（2026-11-10）

| 命令 / 检查                                    | 实际结果                                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 新模块 + 授权清单/执行/真实登录主链定向 pytest | **82 passed / 1 warning，98.00s**；新增 22 项，不与全量相加                                                  |
| `make test`                                    | **12,454 passed / 18 skipped / 11 deselected / 40 warnings，681.81s**                                        |
| 同一 `make test` 的纯领域 unittest             | evaluation **15**、toolkit **58 passed**                                                                     |
| `make test-blocking-io`                        | **72 passed / 2 warnings，5.60s**                                                                            |
| `make lint` / 离线锁                           | Ruff check/format **1,252 文件**；`uv lock --check --offline` 通过                                           |
| 完整 frontend Prettier / 模块 Markdown         | 通过 / 七份文件通过；无前端运行源码变更，不重复声称单测/类型/build/浏览器                                    |
| 源码快照逐项核对                               | 后端/领域 **1,313**、前端格式 **827**；缺失/不符均 **0**                                                     |
| 独立 PostgreSQL 聚合兼容性探针                 | 会话专属 **TEMP** 表：空集、跨 owner 合计、deadline 相等、interrupted 保留、已释放排除、无敏感投影；六项通过 |

PostgreSQL 探针仅用显式隔离 CI DSN、同列/检查定义的临时技术行，不伪造父运行证据；会话回滚/关闭移除 TEMP 表，没有持久表/数据变更，也不是迁移后的生产 PostgreSQL 验收。SQLite 主回归则使用实际准入/claim/取消/过期/原 claim 收尾链。

编写阶段先修正把全局匿名 401 误认作路由缓存响应的夹具断言；首次全量发现五个旧授权测试的固定权限清单尚未包含新增权限，已逐项补齐精确列表和 provider 请求断言。首次失败、随后定向和完整通过日志分别保留，未改运行时授权、删断言、放宽 SQL/状态验证、增加超时或盲目重试。推送后还须核验该精确 SHA 的实际 Actions；本地通过不是远端 CI 成功。

## 依赖、迁移与回退

没有新依赖、迁移、前端运行变更、执行政策或数据库结构变化；候选 App head 仍 `eval_0012`，历史运行收据仍 `eval_0009`。后续部署需另行授权、备份和保留数据/回滚验证。回退仅还原代码提交，无数据库降级。所有测试/证据导出验真后只停止本模块启动的四个专用 CI 容器；缓存/卷/业务服务保留。

未完成：按运行明细的运维调查、独立的进程隔离/永久出站 fencing 证明、人工对账/释放合同与审计、QA 调度准入、统一执行/导出、正式批准和最终用户验收。此诊断不把这些列为已完成。

## English summary

This candidate adds one human-administrator GET with a separate `evaluation_operations:read` permission. A single aggregate SELECT reads only held technical reservations; no identifiers, claim material, evidence or secrets are selected. Deadline reached never establishes Worker death. The serving process policy is not a global policy-agreement receipt. Every authority flag remains false, and there is no release/reclaim/retry/dispatch path. SQLite lifecycle and real-login synthetic multi-account tests preserve reservation/audit rows, deny-wins and privacy. No migration, dependency, frontend runtime change, deployment, execution enablement, real call or formal approval is added. Safe operational release remains unfinished.
