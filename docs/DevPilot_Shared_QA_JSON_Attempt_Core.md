# 共享有界单次 JSON 采集核心 / Shared bounded JSON attempt collector

> 2026-11-10。当前为本地候选，版本 `qa-json-attempt.v1`。本地完整门禁已通过，源码/证据/资源与新 SHA CI 分别核验；不是独立 runner/export、部署或验收证明。

## 范围 / Scope

将实际 Worker 使用的单次采集逻辑整体置于 `devpilot.qa_json_attempt`：严格限额、请求/绑定防御性快照校验、同一 attempt deadline、单次流式发送、有界 raw-response 读取、正常结束后的 off-loop JSON 解码/提取、错误分类、敏感内部 observation 与 response/client 关闭。它调用现有共享请求准备、响应 buffer/parser 和策略异常，不复制第二套 runner。

App 的 `collect_json_attempt(request, binding, config, limits)` 保留原签名，以薄适配器显式提供每次调用的原 `evaluation_client(config, url, timeout_seconds=...)`。Worker 的准入、dispatch-before-I/O、run-wide 预算、取消排空、加密证据及未知结果不重发仍在 App；不把仓储、鉴权或调度迁入共享包。

## 合同 / Contract

1. `client_factory(url, *, timeout_seconds)` 是必传能力，无默认 client、DNS、App/config/env、凭据或文件读取。factory 可调用不等于安全/授权；调用方仍须保证 ALL DNS answers 策略、固定目的地、TLS、禁代理/重定向、准入、预算与耐久 dispatch。没有该能力不能隐式实发。
2. 版本、factory、输入类型及请求/绑定/限额快照在任何 client 创建前校验。请求投影准备一次，body 编码保留在原 client 上下文与 attempt deadline 内，不提前读取金标/凭据或重新渲染输入。
3. 保留原 `asyncio.timeout`、HTTPX client timeout、默认限额和错误语义，不放宽/叠加超时或加重试。异步 deadline 是协作式取消，不承诺中断同步阻塞 callback、底层 read-ahead 或线程计算。
4. 原始流只保留 maximum+1 个已 yield 的 raw bytes；不是 wire/read-ahead/billing 统计。只有正常 end-of-body 才 off-loop decode/extract；部分流失败或取消即使已有完整形状 JSON，也不产生可用输出。timeout/HTTPX/ValueError 为 `delivery_unknown`，策略异常为 `policy_rejected`；都不是重发许可。
5. `CancelledError` 与未捕获异常原样传播，保留原 response/client 上下文关闭顺序。取消 `to_thread` 等待不能杀死线程；此线程只解析有界内存，不能发布输出/证据。测试必须释放并等待其自身线程，不把它宣称为数据库排空或新增 hard-death/fencing 机制。
6. `AttemptKind`、`AttemptLimits` 和 `AttemptObservation` 从 App 原路径重导出同一共享类型，现有证据 `isinstance` 仍一致。output 保持 `repr=False`，无 headers/raw body/凭据公共 DTO、verdict、批准或持久化格式变化。不可把内部 dataclass 打包为受信外部结果。

## 回归与当前验证状态 / Verification status

新增 44 项回归以 fail-closed DNS/socket、MockTransport 和 event/barrier 覆盖必传 factory/版本/防御校验、HTTP 状态/错误/不重发、观测隐私/不可变、client 创建/进入/退出失败、部分流、超时/取消、关闭等待及 off-loop 取消。实际 App 请求准备测试只将 monkeypatch 注入点改到新所有者，保留 prepare-once、client 内编码、原 wire 及实际 collect 的全部断言。

本地 Python 语法编译、`git diff --check` 和 AST 对照已完成：限额/观测/进度/读取定义不变；collector 除版本/factory 守卫及显式 factory 调用外，控制流 AST 与基线一致。这只是静态证据，不替代回归、运行取消或 wheel 证明。

隔离容器授权审查先超时、后 502，两次命令均未执行；后续经单独只读资源核验和显式启动审批恢复。记录四个专用无挂载/宿主端口的 CI 容器；Python/PG/Redis 在已验证 internal 网络中，沿用本机由 tracked locks 建立的独立依赖缓存，不复制业务数据库/私有配置。

运行证据：旧实现运行新回归实际缺模块 ImportError；修正一次新模块导入排序（保留失败，不加忽略）后，首次小组合 274 passed，最终联合主链 487 passed。399 个基线/候选场景对照实际请求、factory/config/timeout、分类/状态/留存字节/输出、异常类型/消息、流与实际 `client.is_closed`，最多一次发送；不比较精确 elapsed，deadline/取消由独立 barrier 测试覆盖。实际 sdist 构建 wheel，逐字节核对 8 个共享模块；`-I` 从该 wheel 实际 import 并 mock-send，拒绝 App/Harness/DB/Web 依赖及真实 DNS/socket。使用既有锁定 HTTPX，不宣称 no-site/零依赖。

本模块本地最终门禁：新增 **44 passed**；联合 **487 passed**；后端全量 **12,691 passed / 18 skipped / 11 deselected / 40 warnings**；领域 **15 / 58 passed**；Blocking IO **72 passed**；后端 Ruff **1,256 files**、共享核心 lint/format 与离线锁通过；前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。399 个旧/新实际行为对照及实际 wheel 的隔离 mock-send 通过。最终源码/提交归档、证据 hash、精确资源收尾及新 SHA Actions 独立核验；本轮没有重跑本地前端 build/浏览器/性能，不借用历史结果，不部署/启用执行或调用真实模型/目标。

复现门禁：backend `make test`（含两个领域 unittest）、`make test-blocking-io`、`make lint`、共享模块 Ruff check/format、`uv lock --check --offline`；frontend `pnpm test`、完整 `pnpm format` 以及本模块八份文档的 Prettier check。单独新回归与联合清单、baseline tar/mock 对照、wheel 构建/自检、source/evidence/commit manifest 和精确资源记录保存在忽略的本轮 CI 证据目录；失败的旧实现 ImportError、首次导入排序 lint 和审批未执行历史保留，不随 Git 提交私有证据。

## 排除与回退 / Exclusions and rollback

无 API/依赖/迁移、执行启用、真实模型/目标调用、输入/金标导出或凭据交付、独立 CLI/manifest、外部结果采信、失联 Worker 配额回收、正式批准或部署。独立导出仍须完整数据授权、预算/deadline/确认、依赖版本、结果隔离与验收；能 import 单次采集器不代表这些已完成。

回退同时恢复 App collector 与请求准备测试注入点、撤销共享模块/新回归及说明；无 DB 回退或历史 hash 重写。不为回归放宽断言、限额、失败分类或启用执行。

## English summary

The candidate shares the existing complete bounded single-attempt collector, not another DTO or a second runner. An explicit mandatory client factory leaves outbound policy, consent, durable dispatch and run-wide budgets with the App. Request preparation, cooperative deadline, bounded response handling, errors/cancellation, sensitive observations and client/response close semantics are preserved. Approval recovered through separate resource inspection and explicit start authorization. The 487-test joint regression, 399 actual old/new parity cases and isolated built-wheel mock sends passed; the complete local backend/domain/frontend, blocking, lint, lock and formatting gates also passed. Source/evidence hashes, resource cleanup and exact-SHA CI are verified separately, never inferred from syntax or the previous commit. No execution enablement, deployment, new dependency/migration or real target/model call is introduced.
