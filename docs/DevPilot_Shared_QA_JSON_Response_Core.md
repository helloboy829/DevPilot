# 共享 QA JSON 响应核心 / Shared QA JSON response core

> 2026-11-10。候选代码；这是统一执行适配器的一个可复用子组件，不是完整的可运行独立工程导出，也不新增执行或正式批准权限。

## 范围与分层 / Scope and layering

新增纯 `devpilot.qa_json_response`：固定 `qa-json-response.v1` 的单次 HTTP JSON 响应缓冲、头部技术分类及严格输出提取。App 的 `qa_attempts._read` 现在调用它，不保留另一套解析实现。原 `QAJSONBinding`、请求/计划 schema、definition hash、journal/evidence DTO 和历史报告均不改。

- 纯核心仅使用标准库和既有纯 binding/request primitives；没有 App、Harness、HTTP client、数据库、环境、文件、网络、金标或模型访问。
- App 仍负责独立准入、耐久 dispatch-before-I/O、DNS-pinned transport、总 timeout、HTTP response/client 关闭、取消传播和不确定交付分类。缓冲器不能发送，也不能证明交付或输出真实。
- 版本只固定本子组件的语义；**没有**把它追溯写入旧计划/存档，也不宣称已建立完整 exporter/adapter/core 版本链。将来改变语义必须新版本及显式兼容策略，不能随 latest 静默升级。

## 固定合同 / Pinned contract

1. 按原优先级：非 2xx → `http_error`；非 JSON/vendor +json 或非 identity 编码 → `unsupported_response`；声明长度超过上限 → `response_limit`。预拒绝不读取 body，计数为零。
2. 显式 ASCII 十进制 Content-Length 仅作提前拒绝；缺失、无效或谎报长度不绕过实际限制。沿用旧规则，超过 20 字符的十进制声明直接拒绝，包括前导零。边界不悄悄变更。
3. 每个 raw chunk 先切到 remaining 再复制，最多接收 `max_response_bytes + 1`；范围为 1 byte–1 MiB。此计数不是完整 wire 流量、HTTP headers、transport read-ahead 或计费流量。
4. **仅正常 end-of-body 后**允许 finish 提取。严格 UTF-8、唯一 JSON keys、有限数值、bounded pointer/depth/nodes 与非空 string 沿用 binding；保留有效输出的原空白，不修复/截断文档。畸形、空白输出或缺 pointer 是 `invalid_output`，不是 PASS。
5. App 将 UTF-8 解码及提取一起 off-loop。即使已接收完整 JSON，随后 transport error/cancellation 也不 finalize、不收集输出、不重发。
6. 状态单 owner、同步 feed；finish 结果 immutable，可重复读取同一结果；终态拒绝 late feed，不允许重新打开/再利用部分响应。最终清空 raw buffer 不代表安全内存擦除。
7. 结果 output 是敏感内部值，仅 repr 抑制；**不是脱敏公共 DTO**，不能直接 asdict/日志/导出到客户端。无 verdict、acceptance、TTFT、token、证据可信度、释放/重试或批准字段。

## 验证 / Verification

先在未实现新模块的当前提交上运行新增测试，确认缺模块收集失败；保留日志。新增测试覆盖版本/类型/上限、HTTP/编码/长度优先级、UTF-8 任意分块、精确边界、严格 JSON/pointer、终态/幂等 finish、敏感 repr、合成 App/core 等价、off-loop 及完整 JSON 后失败/取消不提取。新测试初次调试的模块导入/必填 FrozenRequest 字段错误亦保留，不放宽断言。

新增 **90 项**参数化回归；与既有 binding/attempt/生命周期及三条合成 API 主链联合 **291 passed，120.66s**。额外在 socket/DNS fail-closed 下对旧提交与当前实现逐例执行 **49** 个合成场景，kind/http_status/body_bytes/output 全部一致，每例一次发送且 response 关闭；elapsed_ms 的非确定值不作相等断言。该额外脚本是保留的本机证据，不与 pytest 数量相加。

扩展旧版对比发现首个候选把 HTTP 状态限制为 100–599，导致旧版对 600 的 `http_error` 被错误改成 `delivery_unknown`。核对实际三位状态解析范围后修正为 100–999，并添加 600/999 回归；保留首次失败，修复后按原命令重跑全部门禁，不能把修复前的全量通过当作最终源码验证。

最终源码后端 `make test`：**12,552 passed / 18 skipped / 11 deselected / 40 warnings，718.70s**；其中分层门禁另含 **15 / 58 passed**。Blocking IO **72 passed，5.78s**；Ruff 后端 **1,253 files** 与新纯核心单独 lint/format、离线锁文件检查均通过。前端无运行时代码变化，但全量单测 **152 files / 1,293 passed**；最终完整前端及本模块 Markdown 格式检查亦须通过。

通过 `-I -S` 子进程直接运行纯核心，并拦截 App/Harness/HTTP/DB imports；证明本子组件不依赖 site packages，不声称整个既有 devpilot 包零依赖。离线构建 source distribution/wheel，再从 wheel 在隔离解释器中进行相同纯解析及版本检查；这仍不是完整 CLI/执行导出验收。

最终本地定向/完整门禁、源码与证据 hash、资源收尾和精确 SHA Actions 分别记录于交付矩阵和本机 ignored `.deer-flow/ci/20261110-json-response-core/`。未运行的前端 build/浏览器/性能 gate 不借用前次成绩。

## 不在本模块 / Exclusions

无依赖/迁移、API/权限、运营配置、部署或执行启用，无真实模型/目标调用。旧 debugger/toolkit/scheduler 未切换；特别是旧 scheduler 不能代替冻结 QA 准入。未实现 runnable ZIP、凭据引用交付、输入导出授权、独立 CLI 出站/预算、结果 quarantine/import、真实目标等价验收或 formal approval。

本模块撤回须同时还原 App 调用及新核心/测试/说明；没有数据库回退步骤。失联 Worker fencing/安全对账、冻结 QA 调度、完整共享执行适配器与可运行导出、正式批准及另行授权的保留数据升级仍待完成。

## English summary

The pinned pure response buffer is now the single JSON response-framing/output-decoding implementation used by the admitted App collector. Transport, durable dispatch, total deadlines, cancellation and uncertain-delivery/no-resend rules remain App-owned. Only normal end-of-body permits extraction. Outputs are sensitive internal values, not verdicts or public DTOs. A standard-library-only subprocess and a built-wheel smoke check verify this component's packaging boundary, not a complete independent runner. No migration, new dependency, deployment, execution enablement or real model/target call is introduced.
