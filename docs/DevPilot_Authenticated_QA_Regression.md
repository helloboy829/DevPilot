# 真实登录的合成多账号 QA 回归 / Authenticated synthetic multi-account QA regression

> 2026-11-10。测试模块，不改变运行功能、权限默认值、迁移或依赖。真实认证实现不等于真实用户/浏览器/部署验收。

## 补齐的边界

既有 API→Worker 回归使用合成身份中间件，能检验执行/复核/档案合同，但不能证明登录 cookie、JWT 数据库身份、CSRF 和 RBAC 在同一链条中工作。本模块的 `backend/tests/test_qa_authenticated_workflow_api.py` 单独覆盖 `api` fixture，复用原 `workflow` 的冻结数据、真实有界 Worker 与离线传输替身；**不挂载原合成身份中间件，不修改 `request.state.user/auth`，不通过 `app.state.actor` 切换身份**。

- 一个临时 SQLite 文件：独立 App Alembic 迁移到 `eval_0012`，只创建测试所需的 Harness 用户/旧组件表。不触碰运行数据库或 Harness ledger。
- 真实 `SQLiteUserRepository` + `LocalAuthProvider` 创建五个随机 UUID 的合成普通用户及真实密码哈希；owner、两名盲审人、第三名仲裁人和无关账号各持独立 HTTP cookie jar。
- 真实 `/api/v1/auth/login/local` 表单、签发 JWT、`/me`、`AuthMiddleware` 的 JWT/数据库/token-version 校验、`CSRFMiddleware` 和 `RbacAuthorizationProvider`。与 Gateway 相同中间件顺序：CSRF 在外。
- 测试只注入临时用户 repository/provider 的依赖缓存、显式合成 JWT/internal key、启用且 fail-closed 的测试 RBAC 策略；保留/恢复原全局状态。不是 mock authenticate、decode、get-user 或授权行为。
- `DEER_FLOW_AUTH_DISABLED` 显式取消；不启动生产 lifespan，不加载私有配置，不读/生成持久 JWT secret。测试源中固定 key/密码仅是合成夹具，不是配置 fallback。

## 覆盖矩阵

| 边界           | 确定性检查                                                                                                                 |
| -------------- | -------------------------------------------------------------------------------------------------------------------------- |
| 登录与 cookie  | 五个独立真实登录及 DB 身份；HTTPS Secure/HttpOnly、既有 Lax session 与 Strict CSRF、相同七天有效期；错误密码与跨源登录拒绝 |
| 会话拒绝       | 缺失、畸形、过期、错误签名、签名有效但用户不存在、token-version 过时均 401；合法 owner 不受影响                            |
| 会话撤销       | 通过真实改密码 API 更新哈希/token-version，旧 cookie 失效、新会话可用；其他账号独立有效                                    |
| CSRF 与隔离    | 空/不匹配 header、缺 cookie 均不能创建项目；owner/无关用户并发 GET 不串号，无关用户列表为空                                |
| RBAC           | allow 中仍存在时，read/write/review 各自显式 deny 必须优先；拒绝不能改变任务 revision/lease；恢复策略后可读取原收据        |
| 指派           | 实际 DB 用户存在性/needs-setup；owner、重复 UUID 或未单独同意分享参考答案均拒绝，GET 同 ID 为 404，无任务落库              |
| 双盲与仲裁     | 并发 1/2 的真实 Worker 各跑两版三样本，两个独立会话盲审；分歧必须由第三会话仲裁；任务授权不是项目成员/证据/结果访问权      |
| 评估与历史     | owner 全 PASS 不进入独立分子；ALL 三样本分母、阈值未达/达标均不批准；归档历史 assessment、报告、同基准复测与固定 Word/PDF  |
| 敏感性与不可变 | 元数据/日志/公开 PDF 不含输入/gold/输出/note/请求 secret；非 owner 不能读取任何档案/导出；重开任务不改历史收据             |

计划、执行、输出、任务、决定、评估和档案全部通过 HTTP + 真实 Worker 生成，没有直接插入生命周期表。只有用户及旧组件是显式合成准备数据。每个两版链条六次 wire send；检查 dispatch 已提交、冻结 build、唯一 run/ordinal、body 关闭、不重试的原 fixture 保持不变。未知写入同 ID GET-only、404 不重发的专用故障矩阵仍由既有回归承担，本模块不把同 ID 的成功读回当成重新发送授权。

## 离线与证据限制

仅使用 ASGI transport；共享出站运输的 DNS 与 wire 由原 fixture 替换，同时 socket connect/connect_ex/sendto 和意外解析 fail-closed。测试中的授权策略启用与 `ExecutionPolicy(enabled=True)` 只存在临时进程/数据库，**不启用运行服务**，不发送真实网络/模型/目标请求。

未覆盖：真实 HTTP/TLS 服务器/反向代理、浏览器 cookie/CORS 行为、OIDC、真实账号、生产 PostgreSQL、生产启动生命周期、保留数据升级、桌面/手机用户操作或正式独立批准。不能把此测试改名为这些验收。现有模拟浏览器与旧模块 CI 另行记录，不冒用为本模块通过。

## 验证与资源

最终本地门禁（2026-11-10）：

- `uv lock --check --offline` 通过，无锁文件/依赖变更。
- `pytest tests/test_qa_authenticated_workflow_api.py tests/test_qa_independent_workflow_api.py tests/test_qa_workflow_api.py tests/test_review_tasks_router.py tests/test_independent_pdf_router.py -q --tb=short`：**63 passed，132.04s**，其中新增真实认证回归 **18 项**。
- `make test`：**12,432 passed / 18 skipped / 11 deselected / 40 warnings，676.37s**；其前置纯领域 **15 / 58 passed**。定向包含在全量内，不累加。
- `make test-blocking-io`：**72 passed / 2 warnings，5.61s**；`make lint`：Ruff check/format **1,248 文件**通过。
- 完整 `pnpm format` 与六份模块 Markdown Prettier 检查通过。无前端运行源码变化，本模块未重跑前端单测、类型检查、build 或浏览器；上一 PDF 模块结果不能冒充本模块验收。
- **1,309** 份实际后端/领域源码快照以文本 LF/二进制原 bytes 核对，缺失/不符均 **0**。最初 SameSite/不存在的项目详情路由假设错误已修正于测试，不改既有运行行为；失败与最终日志同时保留。

本模块最终命令、结果和精确源码/Actions 收据见[交付矩阵](DevPilot_Delivery_Status.md)。编写阶段的错误夹具日志与最终日志都保留在 ignored 本机证据目录，不通过重试/加超时/放松全分母断言掩盖失败。

复用由本线程从跟踪源码/锁文件重建的 Python/Node/PostgreSQL/Redis 测试容器，启动时记录精确 ID；无业务挂载/发布端口，仅 internal 网络。所有测试结束并导出验 hash 后仅停止本模块启动的四个容器；保留依赖缓存与业务服务，不删除容器/镜像/卷或全局 prune。没有运行时变更，回退只需还原测试/文档提交，不涉及数据库降级。

## English summary

This test-only slice replaces the synthetic identity middleware with real local password login, independent cookie jars, database-backed JWT validation, CSRF and enabled fail-closed RBAC. Five synthetic ordinary users exercise owner isolation, blind reviewers, separate arbitration and immutable historical assessments/report/retest Word/PDF through the existing offline Worker fixture. All lifecycle records are produced through HTTP and the real Worker; only users and the legacy component are fixture preparation. Network access fails closed. There is no runtime authorization change, migration, dependency, deployment, real target/model call, production key, browser acceptance or formal approval.
