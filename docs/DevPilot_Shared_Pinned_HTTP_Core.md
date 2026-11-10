# 共享固定目的地 HTTP 传输核心 / Shared pinned HTTP transport

> 2026-11-10。候选代码，固定版本 `pinned-http.v1`；不是独立执行器、导出许可或部署证明。

## 范围 / Scope

`devpilot.pinned_http.PinnedHTTPTransport` 承担原 App 的实际 HTTPX 传输机制：固定 origin、每请求重新调用策略解析器、保留原 Host/TLS SNI 并将连接目标固定为已批准 IP、TLS 校验、零重试、禁用传输层环境代理及关闭 inner。App 的 `PinnedEvaluationTransport(config, url)` 是薄适配器，仍按发送时的 config 调用原 `resolve_destination`；`evaluation_client` 的禁重定向/环境代理和原超时不变。调试、人工 component tests、QA 采集及旧调度通过原接口实际共用，不维护第二套线协议实现。

这不是零依赖纯解析器：传输使用已存在的 HTTPX 依赖，不新增依赖或修改锁。独立 wheel 验证必须在含跟踪锁依赖的隔离环境中进行，不能借用请求/响应核心的无 site packages 结论。

## 安全合同 / Contract

1. resolver 是必传 async callback，无默认 DNS、App/config/env/凭据/文件读取。每次发送先校验原 URL，再比较 scheme/host/port；origin 不符或 URL 含凭据/fragment 时，解析器和 inner 均不调用。
2. App 仍拥有显式 allowed_hosts、五秒 DNS 上限和 **ALL DNS answers** 的地址检查；私网 opt-in 不豁免 link-local metadata、multicast、unspecified 或 reserved 地址。策略在每次调用时重读，不冻结成会过期的许可缓存。
3. callback 返回值必须是 literal、无 scope 的 IPv4/IPv6 字符串；拒绝 hostname、bytes/int/空值、host:port、方括号或 zone/scope，generic error 不泄漏返回值。否则 HTTPX 可能二次解析一个未经检查的 hostname。此新增 callback 边界是 fail-closed 加固，不把这些旧非法/非便携 callback 值列入旧/新等价结论。
4. 单次 callback 后最多一次 inner 调用；Host（含原非默认端口）及 TLS SNI 覆盖不可信入参为原 origin，连接 URL 只改 host，保留 method/path/query/headers/body/其他 extensions。TLS verify=True、trust_env=False、retries=0，不新增 fallback/retry/redirect。
5. resolver/inner 的错误和取消原样传播；资源仍由原 HTTPX client 上下文及 aclose 转发关闭，不吞取消、不增加 drain timeout 或自动重发。App 原 `EvaluationPolicyError` import 名称保留为共享异常类，仍是 ValueError；异常不是持久 DTO，不修改存档/计划/hash。
6. callback 对所有 DNS 答案的审核、client 的禁重定向/总 deadline、准入/同意、输入渲染、durable reserve_attempt-before-I/O、run-wide budgets、unknown/no-resend 和加密证据仍是调用方/App 责任。返回 literal IP 或能 import wheel 都不是发送授权；此组件不能独自认证安全 runner。

## 验证 / Verification

旧提交先运行新回归，保留缺模块收集失败。新增用例用 mock inner/策略 callback，并禁止真实 socket/DNS，覆盖 HTTP(S)/非默认端口/IPv6、原样 wire 值、Host/SNI、重复解析和动态撤回、origin 前置围栏、非法 callback 返回、构造前拒绝、resolver/inner 错误与取消、原 client 关闭和 App 实际委托。首次连同原出站/调试/边界/调度/采集回归 **139 passed**。首轮测试参数超过 Ruff 行宽，按原规则格式化后原断言重跑；不放宽测试。

最终本地门禁：新增 **37** 项回归；联合主链 **443 passed**；标准后端 **12,647 passed、18 skipped、11 deselected、40 warnings**；领域单测 **15 / 58 passed**；Blocking IO **72 passed**；backend Ruff **1,255 files already formatted**、共享模块 Ruff/格式及离线锁检查通过。完整前端 **152 files / 1,293 passed**，`pnpm format` 与本模块八份文档 Prettier 通过。

基于上一提交 `ec9c37b262666a80e2083f472ae41b626d510ee1` 的 **188 个旧/新场景**逐一核对实际 inner 构造参数、wire method/URL/headers/body/extensions、resolver 调用、错误类名/消息与关闭：包含 HTTP(S)/显式端口/IPv6、七方法/两种 body、origin 拒绝和 App 全 DNS 答案策略。全部等价且最多一次 inner send，所有已打开响应关闭。新增非法/scoped callback 拒绝是有意加固，未声称旧行为等价；不比较耗时。实际构建 sdist/wheel，七个 wheel 源码成员逐字节核对，在 `-I` 加既有锁定 HTTPX 依赖环境直接 import 该 wheel 并执行 mock send；禁止 App/Harness/DB 等业务导入与真实 DNS/socket。wheel SHA-256：`25363581dcfe717917aeb155317a014a0e413ea5b4e84a81cdf3afaa6dbdfc55`。

最终源码清单需与测试容器及提交归档分别核对；日志/退出码/JSON 导出后核验各成员 hash，才按精确 ID 停止本模块四个专用容器，临时快照保留副本后精确清理。精确 SHA 的 GitHub Actions 推送后另行观察，不把 push 当作 CI 通过。前端无运行时改动，本机不重跑 build/浏览器/性能；GitHub 实际触发的构建检查另列。全平台、授权独立 runner 和真实用户验收仍未完成。

## 排除与回退 / Exclusions and rollback

无新 API/权限、依赖/迁移、私有配置或数据库复制、执行启用、部署、生产 key 或真实模型/目标调用。旧 toolkit 的独立 client 未切换；旧 scheduler 仍不是冻结 QA 的独立准入。无 runnable ZIP、输入/金标导出授权、凭据交付、独立 CLI 预算/时限、结果隔离导入、lost-Worker release 或 formal approval。

撤回需一并恢复 App 传输、共享模块及测试/说明，无 DB 回退。后续完整版本化执行链和导出仍须独立门禁；禁止因为此模块可复用就提前显示实发导出按钮。

## English summary

The real DNS-pinned HTTPX mechanism is shared by the existing App adapter. The caller must supply a fresh per-request policy resolver; App retains allowlists, ALL-answer checks, consent, admission, durable dispatch, budgets and unknown-delivery/no-resend semantics. Literal unscoped IP validation prevents unchecked second DNS resolution. Original Host/SNI, verified TLS, zero retries, errors/cancellation and close forwarding are preserved. Existing HTTPX dependencies are required; an isolated built-wheel smoke is not a full authorized runner/exporter. No dependency, migration, deployment, execution enablement or real target/model call is introduced.
