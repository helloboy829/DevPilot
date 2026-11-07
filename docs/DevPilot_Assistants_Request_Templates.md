# 已登录用户助手开放与参数化请求模板

日期：2026-11-07。本轮为已交付小切片，不表示完整评测平台已经完成。

## 1. 助手开放

- 默认 `agents_api.enabled=true`，无需管理员身份即可管理自己的助手。
- “所有用户”指所有已登录账号；助手、资料和 feature API 均未加入匿名白名单。
- 用户 A 不能读取、编辑或删除用户 B 的个人助手；同名助手可按账号独立存在。
- 个人资料改为 `users/{user_id}/USER.md`，文件操作移出事件循环，写入采用同目录临时文件原子替换。
- 原全局 `USER.md` 原样保留，不在私人资料 API 中回退读取或自动复制，避免越权泄漏。旧的运营方共享助手只保留现有兼容读取路径，不等于个人助手共享。
- 管理员仍可明确关闭能力；关闭时隐藏导航，直接访问显示说明。发现恢复开启时应覆盖历史关闭缓存。
- 模型接入是独立步骤。没有可用模型时可以管理助手，但不能宣称模型对话已经可用。
- 助手不自动获取报告批准权，不替代接口实测、金标复核或验收。

## 2. 请求模板契约

目的：先为“cURL → 可复用请求配置 → 后续冻结执行方案”建立可测试的基础，不保存含明文凭据的调试历史。

入口：组件测试页，导入或编辑请求后，点击“导出参数化请求模板”。不要求先发送，也不发送到目标。

导出包含：

- `schema=request-template.v1`、`scope=configuration_only`、`request_version=request.v1`；
- HTTP 方法、规范化来源（协议/主机/有效端口）、按顺序保留的请求头名称；
- 完整 URL 引用 `DEVPILOT_REQUEST_URL`（原路径和查询参数不导出）；
- 请求体引用 `DEVPILOT_REQUEST_BODY`（空体也需显式提供空字符串）；
- 每个请求头值引用 `DEVPILOT_REQUEST_HEADER_1` 等，重复头按顺序保留；
- 对以上结构计算的 SHA-256 `fingerprint`。

禁止在主机名或请求头名称里放置秘密。来源和头名称仍属于配置元数据，不保证匿名。测试全部为 synthetic；业务地址不进入仓库。

纯核心 `RequestTemplate.resolve(values)` 只接收调用方显式提供的字符串映射，重新验证 RequestSpec 并拒绝来源漂移；不读取环境变量、文件或密钥库，也不发送请求。返回的配置必须再经过平台出站策略和本次调用授权，不能绕过统一出站边界。

指纹只绑定结构，不绑定运行时值、金标、数据集或调试返回。更换凭据或路径可以保持结构指纹不变，因此不能把它作为执行复现标识。指纹不是签名，不能用于鉴权或防止恶意重算。

## 3. 接口与安全

`POST /api/component-tests/debug/template` 请求为 `{spec: RequestSpec}`，需要登录和 `threads:write`。使用既有 CSRF fetcher、私有验证错误和 `Cache-Control: private, no-store`。输出只含模板。无模型调用、目标调用或数据库写入；失败不回显请求值。

浏览器仍使用页面内存；离开页面不生成服务端调试历史。该功能不自动保存或导出原始凭据。

## 4. 明确尚未交付

- 服务端不可变请求版本表与组件/提测版本绑定；
- 受控凭据库和 owner-scoped `credential_ref`；
- 冻结数据集、请求版本、凭据版本与预算共同绑定的执行方案；
- 可直接运行的效果/性能脚本或平台计划执行；
- 耐久运行队列、逐样本观测、人工复核与报告证据链。

本模板不是上述能力的替代品，更不表示 HTTP 200 或评测通过。后续须建立独立 App migration，不改写 eval_0001/eval_0002。

## 5. 本地升级约束

只更新 DevPilot gateway/frontend，必要时刷新本项目 nginx 上游连接。不得执行 `down -v`、删除 volume、重置账号或影响其他项目容器。升级前执行 SQLite online backup 与完整性检查，升级后比对账号、迁移账本、既有 evaluation 行及外键。

## 6. 验证范围

后端：默认启用、feature discovery、匿名拒绝、跨用户助手与资料隔离、关闭兼容、阻塞 I/O；模板纯函数、结构不可变、严格字段/指纹校验、绑定缺失/来源漂移/非法头拒绝、无网络和无值回显。

前端：旧关闭缓存被实时开启覆盖、助手可点击创建、模板下载不发送目标、原调试授权保留。所有验证不使用真实客户接口或付费模型。

## 7. 本轮验收记录（2026-11-08）

以下数量为**软件回归测试**，不是客户组件的历史评测结果：

- 后端离线全量：11,472 通过、73 跳过；跳过项不视为已验收。
- 纯评测核心：58 + 15 项通过。
- 前端 lint / TypeScript、988 项单元测试、18 项相关浏览器端到端测试通过；生产构建通过。
- 浏览器测试使用模拟接口；修复中文导航测试写死站点的问题，遵循 Playwright baseURL。
- 本地仅替换 gateway/frontend，并刷新本项目 nginx 上游；账号完整字段、迁移账本和既有评测数据与升级前在线备份一致，SQLite 完整性/外键检查通过，原数据卷保留。
- 登录用户 feature / 助手列表 / 私有资料接口只读验证通过；未登录仍受认证保护。未创建生产测试账号、未重置密码、未调用客户接口或付费模型。
- 当前本地验证环境没有配置模型；助手管理可用不等于模型对话已通过验收。真实模型、真实服务商与 PostgreSQL 验收不在本轮结论内。

## English summary

Assistant management is on by default for every authenticated account, with owner isolation and operator opt-out. Private profiles no longer expose the legacy global USER.md. Model readiness remains independent.

Parameterized request-template downloads retain method/origin/header names and replace every URL/body/header value with explicit runtime references. Fingerprints bind structure only, not values, authorization, evidence or approved execution. There is no server persistence, credential vault, executable runner or new migration in this slice.
