# 共享完整有界 QA JSON run / Shared bounded run orchestration

> 2026-11-10，候选代码，不是部署或执行启用。新机器的历史运行收据不代表本机运行。基线为 `5d070b3f4d000c09366bf0ac628c76a2fa6973ae`。

## 范围 / Scope

原 `QAExecutionWorker.run_once` 的整个 consumer/monitor/group 控制流迁到 `devpilot.qa_json_run`，固定 `qa-json-run.v1`；平台 Worker 实际委托，不保留第二套循环。已共享的请求/响应/pinned transport/单次采集继续由真实路径调用。本模块不是另一个孤立 DTO，也没有打开下载按钮或独立实发 CLI。

`JSONRunLimits` 是无敏感快照的 frozen/slots 值：严格整数 request_count 1–10,000、concurrency 1–64、timeout 100–300,000ms、正整数 absolute deadline、单次 response 1–1,048,576 bytes；拒绝 bool/float。输入只接受 1–500 个字符串的不可变 tuple，次数不得少于所有冻结输入数；无金标参数。未知版本、无效请求/binding/limits/输入或不可调用能力在任务/回调前拒绝。

The finite orchestrator requires explicit capabilities and returns no verdict. It neither certifies callbacks nor grants execution/export authority.

## 调用能力与边界 / Capability boundary

五个 keyword-only 必传参数：`now_ms()`、异步 `reserve_attempt(ordinal, body_bytes)`、`collect_attempt(request, binding, AttemptLimits)`、`record_attempt(ticket, observation)`、`check_active()`。ticket 对核心是不透明泛型值；没有 DB/文件/环境变量/模型/网络客户端发现或默认时钟。

App 继续负责同 owner/project 的来源核验、显式人类双确认、operator default-disabled policy、全局运行/并发/字节占用、整 run body/response 配额、最大 1 小时的原冻结 wall-time、claim/lease/取消及证据加密。核心有限次数及 deadline **不替代**这些约束。App 保留原 `execution.collect_json_attempt` 测试/动态配置接缝；所有 DB 操作（含 monitor read）仍由原 `_drained_database` 排空。`check_active` 重新读取状态及原 DB deadline；不是只读内存标志。

## 保留的顺序与关闭 / Preserved ordering and shutdown

1. 单一 ordinal iterator 按原输入循环；render 在工作线程完成后，等待对应 reserve 的**耐久派发确认**，再计算原 deadline 剩余时间，最后才允许调用 collector。reserve 未知/异常不发送；remaining 小于 100ms 不发送。不增加超时或重试。
2. 单次 collector 保留现有原样请求、HTTP/JSON 分类、响应 max+1 留存与关闭。`delivery_unknown` 在 await evidence write **之前**设置共享 stopped，阻止其他消费者派发下一次；已发送工作取消并排空，从不重发。
3. 原 200ms monitor、绝对 wall deadline、FIRST_COMPLETED/gather 和 cooperative cancellation 保留。核心 finally 取消并 await consumer/monitor/group，App 才调用 drained finish。Gateway 重复关闭仍由已有 lifecycle shield 原 Worker；不把进程失联当作已排空。
4. render 线程取消不能硬终止线程；取消的 await 不再获得结果/dispatch。回调若自行忽略取消或执行外部 I/O，核心不能认证其安全性。App 的 DB-drain 合同必须保留，不能用超时/自动重试掩盖。
5. 正常返回只表示循环完成，不是 PASS、accuracy、完整人审或正式批准；完整评估仍使用 ALL frozen samples。技术错误可以结束采集但不成为通过。

## 回归与证据 / Verification

本模块本地最终门禁：新增 **62 passed**；最终联合 **549 passed**；完整后端 **12,753 passed / 18 skipped / 11 deselected / 40 warnings**，领域 **15 / 58 passed**，Blocking IO **72 passed**；后端 Ruff **1,257 files**、共享 run/attempt lint/format 与离线锁通过。前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。28 组旧/新真实 Worker 数据库/HTTP 行为逐字段对照及实际 wheel 完整 mock run 通过；静态 AST 另证原 DB-drain/serve、consumer/timeout/cleanup 保留。最终源码/提交归档、证据 hash、专用资源收尾及新 SHA Actions 分别核验。未重跑本地 frontend build/browser/performance，无部署、执行启用或真实模型/目标调用。

新增回归先在旧提交因缺少模块失败。初次 lint 的 Python 3.12 泛型规范错误修正而未加 ignore；首次小组合 99 通过/1 失败是隔离 mock 输入遗漏必需 headers，显式补空 tuple 后 100 通过；后续收据仍期望上一模块 stdout 版本，实际 wheel 子进程已成功，修正期望版本后重新核验。原失败与工具 transcript/脚本修正记录均区分保留，不宣称被覆盖的原小组日志仍存在。覆盖严格参数/必传能力、并发 1/2/4、输入循环、off-loop render、reserve ACK barrier、各阶段异常/取消不重试、dispatch 后计算剩余预算、七类技术结果、monitor 状态/时钟/异常、wall/external cancel 等待清理、unknown evidence drain 前阻止第三次发送、取消 render 无晚派发，以及隔离源码完整 real MockTransport run。既有真实 DB Worker/关闭/HTTP workflow 回归断言保留；真实 collector 场景另加委托 spy，继续运行实际核心/数据库回调与采集器，不以假核心通过。

旧提交 tar 中的实际 Worker 与候选在临时迁移 SQLite 上分别运行，比较 durable ACK/实际 mock wire、ALL dispatches、journal 预算/结束状态、解密输出/金标隔离、人审零 revision/全量分母与 audit action/ordinal。并发未知响应的首次 27 通过/1 失败是对照调度未固定：不同 ordinal 先落库。保留原日志后，对两套真实 DB callback 加相同完成 barrier，仍逐字段比较，不删除断言或更改运行核心。精确 elapsed、随机 ID/token/envelope、并发 audit sequence 不比较；独立取消 barrier 与原 Worker 回归覆盖排空。

真实 sdist→wheel 构建，成员 byte/hash 对照；`-I` 实际从该 wheel 导入并运行完整 mock run，拒绝 App/Harness/DB/Web 依赖及真实 DNS/socket。使用现有锁定 HTTPX，**不宣称零依赖/no-site**。基线、失败记录、清单、日志、source/evidence/commit hash 与资源收尾在忽略的本机 CI 目录，不提交配置、数据库或私人证据。完整 frontend unit/Prettier 独立执行，未重跑本地 build/browser/performance，不借用旧结果。

复现：backend `make test`（含 15/58 领域 unittest）、`make test-blocking-io`、`make lint`、共用核心 Ruff check/format、`uv lock --check --offline`；frontend `pnpm test`、`pnpm format`、八份模块 Markdown Prettier。测试全是显式合成数据；没有真实模型/目标调用。推送后仍须实际精确 SHA Actions，push 成功不等于 CI 成功。

## 排除与回退 / Exclusions and rollback

无迁移/新依赖/API/权限、执行启用、业务配置/保留数据升级、真实网络/模型调用、凭据/输入/金标交付、授权 exporter/manifest/CLI、外部结果采信、失联 Worker 配额释放、冻结 QA 独立调度或正式批准。后续 exporter 必须另行定义数据授权、依赖版本、出站/预算/实发确认与 external/unverified 结果隔离；本模块不能冒充整个平台完成。

回退同时恢复 Worker 原循环和测试委托断言，删除共用模块/新回归；不改 DB/head/历史 hash，不为回退启用执行。

## English summary

The App now genuinely delegates the complete bounded run loop to a version-pinned core, while retaining admission, durable/cancellation-drained database callbacks, global and run-wide quotas, encrypted evidence and finalization. Dispatch acknowledgement precedes every send; unknown delivery fences other consumers before recording; shutdown drains local tasks before App finish. Tests use synthetic databases and actual mock HTTP sends. The built wheel is independently exercised without business imports or real network. This is shared orchestration, not an authorized exporter, deployment, formal approval or a completed platform.
