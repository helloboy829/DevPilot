# 共享 QA JSON 请求准备核心 / Shared QA JSON request preparation core

> 2026-11-10。候选源码；与响应核心共同推进统一执行适配器，但不是完整 runner/exporter，也不授予执行、数据导出或正式批准权限。

## 范围与分层 / Scope and layering

新增纯 `devpilot.qa_json_request.QAJSONRequest`，版本固定为 `qa-json-request.v1`。输入只能是**已经由独立准入调用方渲染**的 `FrozenRequest`；App `qa_attempts.collect_json_attempt` 直接共用本实现，不为将来的 exporter 另复制请求准备逻辑。

- 纯标准库及既有 request primitives；无 App/Harness、HTTP client、DB、环境/文件/网络、凭据解析、样本或金标访问。没有发送方法、裁判、授权/批准或配额释放字段。
- 原 `QAJSONBinding.render` 及 Worker 的 off-loop 输入渲染、随后耐久 `reserve_attempt` → 才调用采集器的顺序不变。版本不追溯写入旧计划、hash 或档案。
- App 仍持有独立授权、run-wide budgets、dispatch-before-I/O、总 deadline、DNS-pinned TLS transport、取消与资源排空、unknown-delivery/no-resend 规则。纯投影并不证明可安全发送。

## 固定合同 / Pinned contract

1. 在创建任何 client 之前，沿用 `FrozenRequest.to_request` 的完整校验；无效输入得到不含字段值的 `ValueError("Invalid QA JSON request")`。App 的原顶层 request/binding/limits 类型检查不变。
2. URL、method、body 完全保留；不 canonicalize URL/query、不解析或重序列化 JSON、不替换输入、读金标或解析 credential references。允许已验证请求中非 JSON body，因为这是已有采集器的准备合同，不是新 JSON 内容准入。
3. headers 深冻结为 tuple of tuples，保留原顺序、大小写、重复值、空值及空白。仅当不存在大小写不敏感的 `Accept-Encoding` 时追加 `("Accept-Encoding", "identity")`；显式 gzip/br/空值/重复编码头不偷偷覆盖，压缩响应仍由既有响应核心拒绝。
4. 原请求最多 **64** 个 headers；既有采集器的派生追加可使发送投影有 **65** 个。投影不重新当作待持久化 `RequestSpec`/`FrozenRequest` 进行 64 限制，否则会静默改变旧行为。输入 65 个仍在 client 前拒绝。
5. body 的 UTF-8 限额仍为 **262,144 bytes**，不是字符数。`content` 在 App 原 client 上下文/总 attempt timeout 内按需编码，保持传输内容精确，不声称 socket/wire/billing 计数。验证阶段不搬移网络或扩大时限。
6. frozen/slotted 投影不保留原对象或可变 header list；原始列表/对象后续变化不影响快照。`repr` 抑制 URL/headers/body；这些字段及 content **仍是敏感内部值**，不是公共 DTO、脱敏数据或导出许可，不能直接 asdict/日志/下载。

## 验证 / Verification

先在旧提交运行新测试，观察到缺模块收集失败并保留证据。新增参数化回归覆盖版本、严格输入、不可变快照、全部现有 methods、原样非 JSON/空 body、Unicode 精确上限、URL/query、重复/显式/空编码 header、64→65 历史边界、client 前拒绝与 App 实际委托。独立 `-I -S` 子进程拒绝 App/Harness/httpx/DB imports，验证纯子组件不依赖 site packages；不声称整个 devpilot 包零依赖。

首次核心/采集器/响应核心联合 **193 passed**；最终联合 binding/生命周期/执行及三条合成 API 主链 **349 passed，122.50s**。额外在 socket/DNS fail-closed 下对基线 `e32cb3d81b64ed8f79411f22a049a3f0669c37e2` 与当前实现执行 **119** 场景：HTTPX 实际 method/URL/raw headers/content 及 kind/status/body_bytes/output 逐项相等，每例一次发送，所有已打开响应关闭；elapsed_ms 非确定值不作相等断言。此脚本为本机额外证据，不与 pytest 数量相加。

离线构建 sdist/wheel，逐项比较公开核心成员与源码 hash；实际 wheel 在 `-I -S`、无业务 imports 下验证请求投影及共享响应解析。这不是完整独立 CLI/安全出站/真实目标等价验收。最终后端全量 **12,610 passed / 18 skipped / 11 deselected / 40 warnings，755.79s**；领域 **15 / 58 passed**，Blocking IO **72 passed**，Ruff check/format **1,254 files** 与纯核心单独检查、离线锁核对通过。前端 **152 files / 1,293 passed**，完整 Prettier 和本模块 Markdown 检查通过；前端无运行时改动，未重跑本地 build/浏览器/性能，不借用前模块成绩。源码/证据 hash、资源收尾及本提交精确 SHA 的实际 Actions 另存本机收据；push 成功本身不算 CI 成功。

## 不在本模块 / Exclusions and rollback

无新依赖/迁移、API/权限、运营配置、部署、执行启用或真实模型/目标调用。旧 debugger/toolkit/scheduler 未切换；旧 scheduler 不是冻结 QA 准入。未实现 runnable ZIP、输入/金标导出权限、凭据交付、独立出站/预算/时限、结果隔离导入或 formal approval。

撤回须一起还原 App 委托、新纯核心与测试/说明；无数据库回退。后续仍须完整执行适配/版本链、经授权导出、失联 Worker fencing/对账、冻结 QA 调度、正式批准及另行授权的保留数据升级/真实用户验收。

## English summary

The pinned immutable request projection is now shared by the admitted App collector. It preserves literal request values and the historical conditional identity header, including the derived 65-header case. UTF-8 content encoding remains inside the original attempt deadline/client context. It has no transport, data access, credential resolution, consent or execution authority. Sensitive values are repr-suppressed, not sanitized export DTOs. Pure-source and built-wheel checks demonstrate this subcomponent boundary only; no dependency, migration, deployment, enablement or real target/model call is introduced.
