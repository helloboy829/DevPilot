# DevPilot AI 性能测试工作台与负载工具集成

> 状态：目标规格与已实现边界。现有源码支持冻结性能场景、持久准入与 dispatch 账本、合成 Worker、metrics API v1 和只读结果页；可运行工作台和真实目标传输未交付。原始 request body 不作为性能证据持久化。旧 `component-tests` / `evaluation-schedules` 是兼容路径，不作为新工作台基础。

> **PERF-04 historical implementation boundary (2026-11-23):** The candidate implements PostgreSQL-first durable lease/fence primitives: `claim -> ACK ticket -> send_started`. `eval_0028` adds worker, epoch, and lease-deadline metadata. ACK does not start the measurement window or mark a request as sent; only the current worker/epoch with the stable ticket may transition to `dispatched`. This slice does not include Worker, real transport, admission authorization, cancel/drain, the complete metrics API, or the workbench UI.

## Metrics API v1 implementation boundary (2026-11-24)

`GET /api/evaluation/projects/{project_id}/performance-runs/{run_id}/metrics` is a read-only, owner/project-scoped projection. Its envelope contains `schema_version: performance-metrics.v1`, `applicability` (`available`, `not_measured`, or `synthetic_only`), nullable deterministic `revision`, and nullable `metrics`. The revision binds the schema version, run ID, frozen scenario hash, measurement window, and metrics population hash. Responses are `private, no-store`. The response body does not claim that a synthetic run measured a target. This is a versioned projection, not yet a persisted immutable assessment revision; matrix/stage/repeat projections and execution controls remain future work. The results browser now consumes this envelope on explicit run selection, shows applicability and projection revision, and renders metric cards only when `metrics` is present; it remains a ledger/results view and does not create load runs or dispatch requests.

## 1. 目标与产品边界

性能工作台用冻结的数据集和 RequestSpec 产生可重放的工作负载，按明确负载模型发送请求，给出总体和逐请求指标，并保存足以审计/复算的请求、响应、调度和发生器证据。它与效果测试共用项目、组件、数据版本、凭据引用、RequestSpec、运行身份、授权、派发 fence 和原始证据存储；负载模型、测量窗、指标聚合和性能验收单独版本化。

性能计划允许 expected 缺省。它不把性能结果混入效果分母或 rubric，不用性能通过推导效果通过。短数据集循环时，同一 `case_id` 可以出现多次；性能分母是冻结负载窗口内的 request/dispatch，不是唯一数据 case 数。执行每个请求都留痕，包括预热、测量、超时、失败和未实际派发项目。

真实目标调用默认关闭。只有执行计划、受控目标、执行时间窗、数据使用、预算和出站授权全部显式确认后才可启动。性能 worker 不通过 Agent 循环发请求，也不在 Gateway 同步完成压测。

## 2. 前端工作台流程

1. 选择项目、组件、已确认的 endpoint revision、适用且审核冻结的数据版本。组件/数据错配在计划冻结前阻断。
2. 选择数据范围：全部 case 或事前固定的 case ID 集合。计划保存排序算法、case 集合 hash 和数据版本 hash。
3. 配置请求构造：复用冻结 RequestSpec/adapter、输入映射、协议/流式模式、max output tokens 等允许参数；参考答案永不送入目标。
4. 选择基础负载模型与停止条件。MVP 为固定闭环并发、测量 request count、可选测量 duration 上限、预热请求数、单请求 timeout、in-flight 上限、绝对 run deadline 和 drain 上限。`request_count` 始终为有限预算；若 duration 先到，停止新派发并排空已发送请求，实际完成数和 stop reason 明示。duration 不能让请求数无上限。
5. 后续档位负载可创建一个不可变 scenario matrix：并发阶梯或 request rate 阶梯、每档预热/测量/排空、冷却间隔、重复次数。首次发布不强迫多档/自动扫参；用户能逐档检查预算和总请求数后再冻结。
6. 查看请求/响应字节预算、模型计费估计、并发资源额度、数据外发范围、目的地址和 stop policy。保留预检、授权、单次确认和运行号；条件变化立即撤销确认。
7. 运行列表显示当前阶段、已派发/完成/成功/失败/未知/未派发数、当前吞吐、剩余预算及生成器健康。只允许显式刷新/受控状态事件，不创建后台重发。
8. 完成后先看 summary 与档位对比，再进入逐请求表和请求详情。可以按样本、轮次、并发档位、时间窗、响应类别和技术状态过滤；不删除失败行、不从图表点掉样本。输入正文遵循[效果工作台的敏感数据访问合同](DevPilot_效果测试工作台设计.md#敏感证据打开)，参考答案不参与性能请求，性能详情不自动解密参考答案。

## 3. 负载模型与停止语义

### MVP：闭环固定并发

一条 request 完成或终止后，同一个 worker slot 才领取下一条；配置 `concurrency`、`measured_request_count`、`warmup_request_count`、可选 `duration_limit_seconds`、`request_timeout_ms`、`max_in_flight` 和硬性 `wall_time_limit_seconds`。停止条件按 `first_limit_reached` 执行：测量请求数已派发或持续时间截止其中任一成立即停止新测量派发；warmup 在测量窗口前独立完成。未完成请求进入 drain，超过 drain deadline 的请求标记为未知/截尾，不重发。

调度状态机必须区分 `claim`、`send_started`、终态和发送前取消。`claim` 只为冻结 manifest 中的 ordinal 预留 worker slot，不代表目标请求已发送，也不启动测量窗口。Worker 在即将调用 transport、且之后不再有本地拒绝分支时记录 `send_started` 单调时钟；首个 measurement `send_started` 才设置 `window_start` 并启动可选 duration。测量预算按冻结 dispatch 行消耗：已开始发送或显式 `cancel_before_send` 的行均保留在固定分母，未发送取消不得伪装为 attempt/timeout/unknown。请求数上限耗尽后停止新 claim；count-only 的 `window_end` 等所有已开始请求完成或 drain deadline 将它们标为 unknown 时确定。duration 或 wall-time 先到时，`window_end` 取该停止边界；边界后禁止尚未开始的 dispatch 再发送，必须显式终结为 `not_started`。drain 只将已经 `send_started` 且未终态的请求归为 unknown。

性能方案必须有正整数请求预算和有界总字节预算；duration 只是较早的停止条件，不能取代请求上限或绝对 deadline。用户若选 duration 优先模式，仍填写可见 `max_request_count` 安全上限，并冻结停止原因为 duration 或 count。summary 显示 planned/actual request count、预热数、测量起止单调时钟、墙钟窗口、drain 时长和 `stop_reason`。

循环映射确定性规则：冻结 case IDs 按 `case_id` 字典序，warmup 和测量分别使用确定 seed/algorithm；第 `i` 个 dispatch 的 `case_id = ordered_case_ids[i mod N]`，`iteration_index = floor(i/N)`，并保存 `phase=warmup|measurement`、`profile_step_id`、`ordinal`、`dispatch_id`。启动前把实际有限 dispatch manifest/hash 固化，不能运行后重排或挑选成功项。
Case selection and ordinal mapping are deterministic for the frozen ordered case IDs. `dispatch_id` is a random per-schedule UUID, so independent schedule constructions do not produce byte-identical manifests; the future durable admission layer must persist the generated manifest and its hash before dispatch, and retries/reconciliation must use those persisted IDs rather than regenerate them.

### 后续：开放到达率和负载矩阵

开放式 `constant_rate` / `poisson_rate` 用绝对计划时钟产生到达时间，按实际 `scheduled_at`、`sent_at` 记录迟到和发生器排队；不能因为慢响应自动降低目标到达率而不披露，否则会发生 coordinated omission。并发阶梯/速率阶梯每档独立测量窗口，warmup 不进入有效统计，档间按批准冷却并分别报告。Trace replay 只接收经授权并冻结 hash 的合成/脱敏 trace，不访问任意在线数据源。

同一 scenario 的多次 repeat 保存独立 run/measurement window，再按冻结聚合规则给出中位数/区间，不只保留最佳值。所有档位的 request/case/attempt 分母和失败都保留。多组件对比不简单汇总平均，不互相分摊计费或性能指标。

## 4. AI 性能指标契约

本工作台文档拥有性能 scenario、run、dispatch、指标投影的领域字段和语义，以及负载、停止、预算与适用性合同。API 方法/路径和通用 wire 协议由[API 接口设计](DevPilot_API接口设计文档.md)维护；API 中的性能路由表是映射摘要，不重复定义 profile 或 metrics DTO。除本节明确标注已实现的 PERF-01 定义资源外，本文列出的目标能力不代表已实现。

PERF-01 已实现范围：owner-scoped immutable scenario 定义 API，引用冻结 performance plan，固化有界 profile、dataset/request/plan hash、case-cycle manifest 与 audit；读取时校验 definition hash。它不创建运行、不发送请求，不含执行 admission、Worker、指标、逐请求证据或工作台 UI。

所有时间从负载 worker 单调时钟测量，明确包含网络/目标排队的端到端口径；平台队列时间与目标调用时间分开。MVP `quantile_method=nearest_rank.v1`：对 n 个有限有效观测升序排列，p 分位取索引 `ceil(p*n)-1`（0-based），不插值；n=0 返回 null。原始未舍入观测保留用于复算，只在展示层舍入到 2 位；不足 100 个有效样本时 p99 显示样本不足提示而非数值，仍提供 n/max。后续改算法必须升版本，不重写旧 run。

测量总体由实际 `measurement` phase 且 Worker `send_started` 落在测量窗口 `[window_start, window_end)` 的 dispatch 组成；warmup 永不进入。count-only 模式下，窗口从首个 measurement send 开始，至所有已冻结测量 dispatch 达到成功/失败/timeout/unknown 终态为止，drain 中未终态项目依 deadline 标 unknown 后结束窗口。duration 生效时，`window_end` 是到达 duration 或 measured count 上限的 first-limit 停止派发时刻；随后 drain 的终态仍归入各自 dispatch 指标，但不延长测量窗口，未知及失败保留在 cohort 中。attempt QPS 是窗口内实际 send 数/窗口秒数；success QPS 是该 cohort 最终成功数/同一窗口秒数，output token throughput 是 cohort 成功成员的合格 output token 总和/同一窗口秒数。窗口秒数为 `window_end-window_start` 的单调时钟差；零窗口时速率为 null 且原因 `zero_measurement_window`，不能除零、记零或代入配置 duration。每项汇总都同时报告 cohort population、成功/失败/timeout/unknown 计数与 hash。

| 指标                                      | 计算/适用范围                                                    | 必须并列的证据                                              |
| ----------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| completed/attempted/error/timeout/unknown | dispatch 全量计数；未知、取消、未派发不移出 denominator          | 冻结 request manifest 与 stop reason                        |
| request rate / attempt QPS                | 测量窗内 dispatch 数 ÷ 实际测量秒数                              | scheduled/sent/completed 时间与发生器排队                   |
| successful QPS                            | 有效业务终态请求数 ÷ 实际测量秒数                                | HTTP、协议解析和目标错误分类分开                            |
| end-to-end latency                        | send 到完整业务响应终态                                          | 成功和失败分别报告 mean/p50/p90/p95/p99/max、样本数、截尾数 |
| time to first byte / first content        | 明确单位和观测事件；first content 仅适用于实际流式可见内容       | stream mode、chunk/timestamp parser 版本、是否发生缓冲      |
| TTFT / ITL / TPOT                         | 仅传输确实暴露文本 token 增量/时间戳时可计算；chunk 不等于 token | tokenization/usage 来源、可观测性；否则 UNAVAILABLE/N/A     |
| output token throughput                   | 成功测量请求输出 token 总和 ÷ 测量窗秒数                         | usage 来源 provider/tokenizer/estimated 和版本              |
| per-request generation rate               | 输出 token ÷ 冻结计时区间                                        | 与 aggregate token/sec 分栏，不能互代                       |
| schema/协议有效率                         | 按冻结 extractor/response schema 解析成功数 ÷ 预定 population    | extractor revision、失败响应证据                            |
| goodput/SLO                               | 满足冻结的延迟/成功率/token 或质量约束的请求数 ÷ 冻结 population | 每个条件、分子分母和适用性                                  |
| worker saturation                         | CPU、RSS、事件循环 lag、socket/FD、发送队列、网络吞吐            | 采集器版本、采集间隔和缺失状态                              |

成功和失败 latency population 相互独立，以各自的完整有效终态耗时计算 nearest-rank 分位数；到 hard deadline 仍未完成者只记 observed duration + right-censored，不当作完整 latency 样本，也不从 dispatch cohort 分母消失。HTTP 2xx 但 JSON 协议错误不是成功输出。端到端测量不宣称目标纯推理时间。期望答案缺失不影响延迟/吞吐，expected 指标单独 `UNAVAILABLE`。worker saturation 等资源序列以原采样时间点/缺失状态保留，不能将稀疏样本插值伪装为目标服务端指标。

## 5. 请求级证据与数据模型

每次派发至少有唯一 `dispatch_id`、run/plan/snapshot hash、case ID/hash、循环 iteration、阶段/档位、预定/实际发送时间、客户端单调耗时、attempt 状态、HTTP status、错误分类、请求/响应 byte 数、实际交给 HTTP transport 的应用请求正文 hash、原生 response hash 或 captured-prefix hash/media type/capture status、extractor/evaluator revision、token 数及其来源、stream timing、evidence refs。请求 artifact 是否保存正文由冻结的 `capture_profile` 和预算决定；hash、字节数、RequestSpec/binding/adapter/serializer revision 始终必存。未留正文时，仅当 run 冻结输入与全部渲染版本可用、确定性重建结果的 hash 与 dispatch 记录完全一致，才可展示标明“重建”的应用层正文；否则标为 unavailable，不得用当前数据或当前 serializer 补造。该 hash/正文对应交给 HTTP 客户端的应用层内容，不宣称包含 HTTP framing、TLS 或网络线上字节。每个收到的 response（包括 HTTP error body）均按共享 evidence policy 有界捕获；只有因未收到响应而没有 body。响应 artifact 字节定义、闭合 `capture_status`、预算、加密存储、稳定 ID 和写入恢复统一遵守[效果工作台 EVID-02 合同](DevPilot_效果测试工作台设计.md)，不另造性能专用状态或事务语义。任何响应 header 只保存 allowlist 元数据。

性能结果页的请求详情分开展示“请求预览”“已捕获应用层正文”“确定性重建”或“不可用”，并同时呈现来源、serializer/contract revision、hash 和 capture status。预览不证明曾经发送；重建必须展示 hash 校验状态；已捕获正文才可引用 request artifact receipt。三者均属于敏感数据，遵循共享 evidence access 授权、审计、no-store 与大小限制。

`dispatches` 是负载发送事实，`attempts` 若将来允许人工批准的额外发送必须独立建模；MVP 不重试，同一 ordinal 只对应一次平台发送，`delivery_unknown` 永远不自动重发。性能循环导致的同一 case 多次调用通过 dispatch ordinal/iteration 区分，不覆盖上一条 evidence。

建议 additive App migration：

- `evaluation_response_artifacts`：`run_id/ordinal` 复合引用、dispatch/artifact id、scope、完整 body hash 或 captured-prefix hash（含 hash scope）、bytes、媒体类型、共享 `capture_status`、key version、receipt 与 created time；大正文在受控 artifact storage，不存大 blob 到查询行。完整 body hash 针对 transfer framing 移除后、`Content-Encoding` 解码前的 transport body；解压/字符集解码是独立有版本的解析投影并有单独展开上限。
- `evaluation_request_artifacts`：按冻结 capture profile 可选保存加密应用层请求正文 artifact；实际交给 HTTP 客户端的正文 hash/bytes、RequestSpec/binding/adapter/serializer hash 必存。未保存原文时仅在完整冻结输入/版本可用且重建 hash 完全一致时允许标记为确定性重建，否则标记不可用；不得称为 wire capture。
- `evaluation_run_metrics`：run、scenario/step/repeat、metric key、nullable value、unit、applicability、sample count、population hash、aggregation version 和 source hash；同一测量 revision 不原地覆盖。
- 现有 dispatch journal 增加 `phase`、`iteration_index`、`profile_step_id`、scheduled/start/first-content/finished monotonic observation 和 `capture_status` 所需索引/约束。实施前检查现有复合 FK 与 SQLite/PostgreSQL parity，按迁移版本新增，不直接更改已部署迁移。

artifact 总预算提前 reservation；单条响应 cap、run response-byte cap、总 artifact cap、保留期限与解密权限互相独立。大文件访问须显式授权和审计；敏感正文 no-store，不回显路径。请求和响应 artifact 都由共享 EVID-02 协议处理：dispatch 前分配稳定 ID 并写 `pending` manifest，response body 以同 ID 临时加密写入、校验 hash/size、原子发布，再写 durable receipt/manifest；DB 结果未知时只对同一 ID 只读对账，绝不重新请求目标或创建替代 ID。发布对象但 manifest 未确认的内容进入隔离治理；只有证实无引用并越过保留期后，才按精确 ID 清理。`pending/complete/partial/truncated/policy_skipped/not_received/write_failed/write_unknown/unavailable_legacy` 等状态对分母和 assessment blocker 的含义以共享合同为准；任何失败、未知或不完整响应都不能从冻结人口中删除。

## 6. Worker/模块架构

```text
Performance Workspace
  -> frozen PerformanceScenario + Dataset/RequestSpec snapshot
  -> admission / target window / quota / byte reservation
  -> durable PerformanceRun + outbox
  -> isolated PerformanceWorker (load scheduler + finite workers)
       -> durable dispatch ACK -> pinned transport -> raw response capture
       -> one request observation + artifact receipt per dispatch
  -> deterministic performance metrics core -> immutable metrics revision
  -> run dashboard / request table / case evidence detail
```

App 保留权限、确认、目标白名单、凭据、租约/fence、耐久记录和 artifact ACL。`devpilot` 纯核心负责 scenario validation、case-cycle mapping、调度计划、指标公式和报告 projection；不能 import App/Harness。QA effect/performance 两种任务共用 request/dispatch/evidence/run 身份及采集合同；指标和 `AssessmentRevision` 按 mode 分开。LangGraph/LLM 不在负载循环内。高并发 Worker 初期作为独立进程/容器，可和 Gateway 分开限额，不能由 API event loop 当发生器。

## 7. 开源工具评估（2026-11-20）

查验公开仓库 README/API、许可证文件与 PyPI 元数据。版本、仓库活跃度会变；正式集成时还须锁定 release/commit、检查依赖和供应链、构建 SBOM 并对选定目标/数据做独立校准。

| 工具                                                                                                                                   | 查验结果                                                                                                                                                                 | 可借鉴能力                                                                                                                                                                                                                                                 | 是否直接成为平台执行核心                                                                                                                                                                                                                     |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [AIPerf](https://github.com/ai-dynamo/aiperf)                                                                                          | 2026-11-20 查验：Apache-2.0；最新稳定 PyPI 版为 `0.13.0`（2026-09-24），Python `>=3.11,<3.14`；`0.14.0.dev20261119` 是预发布版，不作稳定基线；官方 `v0.13.0` 文档已提供 `--export-level raw`，导出完整请求/响应记录 | concurrency、request-rate、trace replay、duration、ramping、OpenAI chat/completions/embeddings/audio/images/Responses 示例；`v0.13.0` 有逐请求 metric/error/ID records、raw parsed request/response records 和可选 HTTP trace（headers、时间戳、chunk/byte 计数）。版本化资料未确认 raw 记录中 binary body 的具体编码或与实际发送字节的一致性。官方迁移文档指出 reasoning 模型的 TTFT/TTFO 定义与 GenAI-Perf 不同，跨工具比较须对齐口径 | **首选外部适配候选，稳定版即可进入隔离 adapter spike，不是核心依赖**。raw export 是工具自己的文件落盘，未证明请求在发送前已经由 DevPilot durable ACK，也未天然绑定平台 dispatch/case/iteration、加密 artifact manifest、budget/capture status 和 unknown/no-resend；还需验证 body 字节表示及其与实际发送字节的一致性、异常/流式响应覆盖、敏感头处理、明文临时文件清理及崩溃边界。raw parsed records 不等同于完整 wire capture。 |
| [GuideLLM](https://github.com/vllm-project/guidellm)                                                                                   | 2026-11-20 查验：Apache-2.0；最新 PyPI release `0.8.1`（2026-10-08），Python `>=3.10`；release 页面未展示构建来源证明，集成前需核对 wheel 与固定源码 tag                 | OpenAI-compatible/vLLM、同步/并发/throughput/constant/Poisson/sweep profiles、按 request/duration 约束、合成/本地/多模态数据。JSON/YAML 默认保留每条请求的完整内容级数据；`sample_size` 可按状态组抽样；CSV 不含逐请求细节 | **第二外部适配候选**，适合到达率实验及多模态能力对照；不得只导入聚合 CSV，若要求完整逐请求留痕须保持默认全量数据而不设置 `sample_size`。JSON/YAML 内容留存不等于原始 HTTP wire/body/header 证据，也不自动满足平台加密 artifact、发送前 ACK、稳定 case/iteration 和 unknown/no-resend。 |
| [vLLM `bench serve`](https://docs.vllm.ai/en/latest/benchmarking/cli/)                                                               | 2026-11-20 查验：vLLM 官方随项目维护的 serving benchmark CLI；依赖 vLLM 及其 benchmark extra，目标服务针对 vLLM OpenAI-compatible serving                 | 固定/随机 workload、request-rate/concurrency、请求级延迟与 token 指标、详细结果、timeline；可启用 server-side per-request metrics 作诊断，但会增加服务端 CPU 开销。当前 vLLM benchmark 文档建议生产 serving 基准优先使用 GuideLLM，`bench serve` 更偏向 vLLM 特性评估与回归 | **不作通用平台 adapter**。仅作为 vLLM 后端专项校准/指标交叉核对参考；后端绑定、诊断指标开销以及缺少平台 dispatch/evidence durability 合同，使它不适合作为 DevPilot 的跨供应商负载执行核心。 |
| [Ray LLMPerf](https://github.com/ray-project/llmperf)                                                                                  | GitHub `archived=true`；Apache-2.0；最后推送 2024-12-09，已归档                                                                                                          | Ray 并发 token benchmark、单请求/总体吞吐与延迟思想                                                                                                                                                                                                        | **不采用**：归档项目不适合作为新基线；可作历史公式参考，不 fork/vendoring。                                                                                                                                                                  |
| [NVIDIA GenAI-Perf](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_analyzer/genai-perf/README.html) | NVIDIA 官方文档明确标注 phased out、停止新功能，并指向 AIPerf                                                                                                            | 旧版 Triton/NVIDIA serving 口径参考                                                                                                                                                                                                                        | **不新接入**：新需求评估 AIPerf，保留 GenAI-Perf 兼容/历史报告只读说明。                                                                                                                                                                     |

截至 2026-11-20 的 release 复核未改变推荐顺序：AIPerf 最新稳定 release 为 `v0.13.0`，GuideLLM 最新 release 为 `v0.8.1`，Ray LLMPerf 仓库已于 2025-12-17 归档。AIPerf `v0.13.0` 的高精度 rate-loop pacing 和 `--per-chunk-usage` 表明 PERF-02 必须区分调度速率与实际发送速率，并明确首个合并 stream chunk 对 token throughput 的计数口径；GuideLLM `v0.8.1` 的 knee detection、request-generation delay / dispatch-lateness 告警可作为 PERF-03 发生器饱和与调度偏差视图的参考。两者都不能代替 DevPilot 自己的逐 dispatch 耐久回执、冻结分母或证据留存合同。

决策：平台官方统计仍由 DevPilot `devpilot` 的版本化纯指标核心计算，初版用自有有限负载调度器通过 App durable dispatch/evidence worker 执行。AIPerf 的逐请求/raw 导出使它成为第一个 adapter spike 候选，但不预设它已有符合 DevPilot 语义的持久化发送前回执；GuideLLM 是可选第二候选。必须通过运行时 hook/transport bridge 将每次外发与 DevPilot dispatch ACK、case/iteration、原生响应 artifact/hash、错误和 token timing 一一对应，并在崩溃边界验证。未通过前，工具输出只能标为 `external_unverified / NOT_EVALUATED`，不能混入平台评估、通过率或正式报告。

这里的 `external_unverified / NOT_EVALUATED` 是性能结果的概念性信任/评估边界，并非已实现的 wire enum。它不等同于本地 QA 元数据的 `scope=external_unverified_technical_only`，也不等同于服务端声明隔离档案的 `scope=external_technical_metadata_quarantine_only`；两者的 `verdict=NOT_EVALUATED` 只表示未形成质量结论。PERF-04 adapter 开发前必须在其版本化 DTO 中分别定义结果来源/可信状态和评估结论字段，并保持这些既有 schema 不变。

第三方工具接入 gate：

1. 固定具体 release/tag、平台 wheel SHA256 与 license；PyPI release 页面未显示构建来源证明时，额外核对 wheel hash 与源码 tag、生成 SBOM 并扫描传递依赖。仅在隔离容器运行，固定输入/输出目录和网络目标 allowlist，不接受用户任意 CLI、插件、模板代码或任意 URL。第三方 `inputs.json`、raw export 和 HTTP trace 可能含 prompt、completion、request headers（包括认证信息）与 endpoint 元数据；未证明敏感头过滤、明文临时文件清理和受控加密落盘前，只能连接合成 Mock，禁止真实敏感数据/目标。
2. 对外部 backend 使用替换 target 的合成 Mock 服务；验证请求映射、循环分母、流式行为、cancel、timeout、body budget、原生响应 hash 和 failure classifications。
3. 必须做到每个 send 前耐久 ACK，每个结果以原 run/dispatch ID 入账，无未知请求自动重发；若工具 SDK 不能提供钩子，则不作为平台 runner，只用于离线对照。
4. 对照 DevPilot 与工具各自 raw data、TTFT/ITL/TPOT、吞吐定义和分位数，差异需解释。不同 tokenizer、warmup、窗口、quantile 或 coordinator 行为不合并。
5. 工具版本/配置/后端/数据 hash 进入运行快照。工具崩溃或写收据未知时，通过同 ID 只读核账；不重跑新 run 掩盖未知结果。

## 8. Legacy 路径和代码重构方案

- `backend/app/evaluation/plans.py` 目前只冻结通用 limits `mode/concurrency/request_count/timeout/wall_time/bytes`，performance 没有 warmup、duration stop、rate model、profile step 或 token metrics revision。使用新 schema revision/additive migration 扩展，不在现有冻结计划上补默认参数。
- `QAExecutionWorker` / `devpilot.qa_json_run` 当前是一条 effect/performance 共用循环：有限请求、样本按序循环、固定并发、超时/硬 deadline、default no-retry、派发 ACK 后请求、加密提取输出。复用其安全协议与 dispatch identity；把 scheduler policy、mode-specific capture 和 metrics adapter 接到可替换接口，不 fork 第二套无限请求 runner。
- `evaluation_output_evidence` 现在仅存 extracted text；保留历史表语义。新 raw response/artifact 用新增 artifact manifest 或 additive migration，不把 HTTP body 放进旧文本栏，不将历史提取输出冒充 raw response。
- `evaluation_review_panel` 是人审任务入口，不是性能仪表板。新 `PerformanceWorkspace` 和 `PerformanceRunDetail` 仅读 summary/metric/run evidence API；既有人审面板仍为人审工作流。
- 旧 `component-tests` ORM/service、旧 `evaluation-schedules` 的参数 payload 和效果/性能 runner 继续只读兼容历史数据；新导航创建 performance scenario 只走 `/api/evaluation`，不双写、不开旧 scheduler，也不把旧 validation_type 的过宽声明带入新 DTO。
- 需特别隔离 `devpilot.toolkit.perf`：`percentile()`、`_aggregate_level()` 是可评估的纯计算候选；`_run_level()` / `perf_run()` 则通过 `call_transport()` 直接发送并发请求，且返回的是按档聚合，不含可供 durable ledger 对账的每请求 dispatch/evidence。`backend/app/component_tests/service.py` 当前直接调用 `perf_run()`，将各档 `to_dict()` 写入 legacy `raw.json`，并用 `perf_eval()` 生成旧报告。新 Worker 不得直接调用 `perf_run()`，不得把它包一层后当作 dispatch scheduler；否则发送越过 App durable ACK、冻结 ordinal 和 EVID-02 receipt。
- `devpilot.qa_stream_metrics`、`devpilot.qa_cv_metrics` 等纯指标工具可被纳入版本化 metric adapter；CLI 投影不能当作线上 evidence store 或执行引擎。

指标复用 gate：对 `percentile()` 和 `_aggregate_level()` 建立固定样本 fixture，明确小样本分位算法、舍入、失败/取消样本人口、measurement wall window、usage/token source 和缺测语义；只有逐项对齐新版本化 metric contract 后才可复用。`perf_eval()` 的 `PASS/FAIL` 是旧 acceptance report，不是新领域的 assessment verdict；旧 `FAIL` 可能混合请求数、测量窗口、阈值和证据充分性，不能映射成新 `BLOCKED` 或 `NOT_EVALUATED`。旧结果仅按 `legacy` schema 展示，新的评估从新 immutable observation/metrics revision 重算；旧 PASS 永不晋升为新口径 PASS，旧 FAIL 也不伪造为某个新 blocker。

旧 run 永久保留其 `legacy`/schema revision。新旧结果以明确迁移/对照报告比较，不批量重新计算、不将旧 PASS 升级为新口径 PASS。先 additive API/UI 和新计划 revision，再按新 API/UI parity、逐请求 evidence 对账、空/部分/未知数据不会假 PASS 的验收门槛逐步停止旧写入、最后只读或退役；生产数据迁移需备份、owner/组件核对和回退演练。

## 9. 开发切片与验收

| 切片                              | 范围                                                                                                                                                         | 退出条件                                                                                                                                                                                    |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PERF-01 场景与准入（定义冻结已实现） | 有界 profile schema、case-cycle manifest、owner-scoped immutable scenario、hash 校验与 audit；`eval_0024` PostgreSQL-first schema；仅定义 API，不含 execution admission | 拒绝空/重复/非法 case scope、无界或越界 profile；请求超过 case 数时按冻结排序循环；要求已冻结 performance plan、精确 dataset/request 绑定和显式确认。duration stop、目标权限/预算变化撤销执行确认属于 PERF-02 admission，尚未实现 |
| PERF-02 worker、ledger 与指标核心 | dispatch phase/iteration、EVID-02 artifact、request/response hash、allowlist headers、预算/保留审计、延迟/错误/吞吐/分位数/token/stream/source/applicability | 逐 ordinal 完全可对账；重复 case 不覆盖；超过预算部分 run 明示 incomplete；取消和未知提交不重发；人工可算 fixture 对照；warmup/drain 不混入 measurement；失败/censored/p99 小样本等分支全测 |
| PERF-03 性能工作台与场景矩阵      | 配置步骤、预检、阶段运行、summary、档位比较、request table/detail、并发/速率阶梯和 worker 资源                                                               | the deterministic scheduler core is merged at `28ea31e`; run/dispatch ledger, synthetic worker and evidence browser exist. A versioned metrics v1 summary endpoint exists; persisted immutable metric revisions, complete matrix projections, user-facing execution controls, and the operator workbench remain incomplete. PERF-07 concurrency is synthetic-only and is not target load evidence |
| PERF-04 AIPerf adapter spike      | 隔离适配器、合成校准、协议和依赖扫描                                                                                                                         | 未通过第三方 adapter gate 前不进入生产执行选择；不加用户可任意选择工具开关                                                                                                                  |
| 后续扩展                          | 图像/音频/embedding/多轮 Agent workload 专用 schema                                                                                                          | 各 adapter 先定义 request/evidence/token/质量，不以单一 text JSON schema 假装通用；独立进入 backlog 后再实现                                                                                |

回归覆盖 request count 大于 N 的 exact cycle、duration 优先终止、warmup、steady window、drain 截尾、固定时间戳、延迟分位数、rate scheduling/迟到、token source、无流式 N/A、流被 buffer、cancel/lease/fence/unknown delivery、超限响应、artifact partial write 与重建。CI 只用确定性本地假服务；真实服务需有隔离手动授权的验收计划。

### PERF-02 已实现切片：持久账本、证据和浏览 UI（2026-11-23）

截至 2026-11-23，PR #5 已合入 `main`，合并提交为 `a672af3fd44f4e053b880a3ca5d53163eb525733`。当前实现包括 `eval_0025` ledger/metrics、`eval_0026` 加密响应 artifact、`eval_0027` actor-bound 一次性证据授权/审计，以及 `/workspace/performance-results` 浏览 UI。下方在开发期间形成的“候选”“未提交”描述是当时状态的历史记录，不表示当前代码仍未合并。候选 SHA `2f86a3e7daa29562d3c3d1dbf48bf6360035efa3` 的 CI 全部终态通过；合并 SHA 的主分支 Actions 单独跟踪于[交付状态](DevPilot_Delivery_Status.md)。

本切片只实现 durable run/dispatch/audit ledger 和确定性指标投影，不实现 worker 或发网请求。迁移 `eval_0025` 新增 `evaluation_performance_runs`、`evaluation_performance_dispatches`、`evaluation_performance_run_audit`；run 绑定 owner、project、冻结 scenario/hash 和 population count；创建事务一次性写入完整 manifest ordinal。每个 ordinal 只有一次 pending → dispatched ACK 与一次 observation；ACK 返回稳定 `dispatch_id` ticket，未来执行器必须先提交 ACK 再发请求。当前仓储没有任何 HTTP client、调度循环或出站授权。

状态/时间约束：`pending` 与 `not_dispatched` 不得有发送时间；`dispatched` 必须有 `send_started_ns` 且没有完成时间；完成的 `succeeded/failed/timeout` 需要单调 `finished_ns` 与非负 elapsed；`unknown` 同时允许有完整终态计时，或在 run 中断后保留 send start、无 finish/elapsed 的右截尾证据。中断将尚未发送项置为 `not_dispatched`、所有已 ACK 未观测项置为 `unknown`，绝不重发/续跑；数据库 CHECK 明确拒绝状态与时间不相容的组合。

`performance_metrics.py` 是纯函数核心，指标版本为 `performance_metrics.v1`，分位数算法为 `nearest_rank.v1`。summary 只使用 `[window_start_ns, window_end_ns)` 中 measurement 发送，排除 warmup/drain；计数和逐 dispatch 行可复算，未知/失败不伪装成成功 latency，token 缺测不补零，小样本 p99 按 applicability 明示。DB 只存有界 hash/reference 与计时/响应元数据，不存请求/响应正文；shared EVID-02 artifact/receipt 绑定尚未实现。

当前实现入口为 `performance_run_repository.py`：`create_run` 冻结 scenario population，`acknowledge_dispatch` 执行一次性发送前 ACK，`record_observation` 接受一次终态观察，`interrupt_run` 进行 unknown/not-dispatched 收尾，`get_run` 按已落库逐项状态投影 summary。Gateway `evaluation_performance.py` 已增加 ledger-only `POST /performance-runs`、owner-scoped `GET /performance-runs/{run_id}` 和 bounded `GET /performance-runs/{run_id}/dispatches`；创建需客户端预生成的 32 位小写十六进制 `run_id`、`confirmed=true` 和精确 scenario definition hash，但不授权、不排队、不触发网络请求。若创建响应未知，只能用原 `run_id` GET 对账，禁止重新 POST/换 ID/自动重试/续跑。读写均由 owner/project/run 组合限定；审计序号在事务内递增。

`feature/perf-evidence` 隔离候选以新迁移 `eval_0026` 建立性能响应 artifact metadata，并在 dispatch ACK 同一数据库事务中分配稳定 `response_artifact_id`、写入 `pending` manifest、将 ID 放入 ticket。manifest 以 `(project_id, run_id, ordinal, dispatch_id)` 外键绑定唯一 dispatch；`record_observation` 校验该绑定后调用共享 `ResponseArtifactStore`，仅加密落盘最多 1 MiB 的响应正文，并持久化 capture status、HTTP/hash/byte metadata、key version、sealed hash/size 与 receipt hash。超过正文留存上限时可保留单独的响应摘要/hash 和观测字节数，不保存正文；`not_received` 不生成对象。响应文件成功但数据库回执未确认时记为 `write_unknown`，故障恢复只能读取原 artifact ID、校验 binding/metadata 后更新原记录；禁止重新发布、重新发送请求或生成替代 ID。落盘缺失可收敛到 `write_failed`，不伪造响应证据。

后续未提交候选新增 `eval_0027` 授权读取：owner/project/run/dispatch/artifact/hash 绑定的短期随机 token 仅以 hash 保存；显式确认后才创建，最多 5 分钟、actor-bound、一次消费，读取后 append-only 审计。只允许单段 byte Range；拒绝无效/多段 Range 和非 URL-safe ASCII token；artifact receipt 与 DB metadata 每次打开均校验；成功响应为 attachment、`private, no-store`。测试覆盖跨 actor/项目隔离、确认/摘要冲突、非法 Range 不消耗 grant、并发双读恰有一次成功及读取审计。不得将 `pending`、`write_unknown` 或 `write_failed` 显示为可读取/成功。

2026-11-23 本地定向验证：性能 router、repository、`eval_0026..0027` migration 及候选升级恢复 **30 passed**；使用 PostgreSQL 17 临时隔离容器实跑升降级、再升级与 metadata parity；回归发现并修复非 ASCII token 后缀被 ASCII-ignore 规范化的问题。随后当前 UI 候选的 Linux/Python 3.12 全后端 `make test` **13,846 passed / 79 skipped / 11 deselected / 40 warnings / 7 subtests passed**；Ruff check/format 通过（**1,348 files already formatted**），Blocking IO **72 passed**；最终 `git diff --check` 通过。此前较大 Windows 跨模块回归为 **305 passed / 20 failed / 7 skipped**，失败来自既有 QA EVID-02 路径在 Windows 不支持目录 `fsync`。这些均为本地候选 worktree 证据，不是精确 SHA Actions；候选尚未提交/push/merge。

2026-11-23 未提交 UI 候选：新增 `/workspace/performance-results`，显式加载项目/运行/dispatch ledger 与纯指标 summary，分批读取逐请求元数据；提供当前已加载页内的 phase/state/sample 筛选、未知/失败/未派发状态、metadata-only 详情，以及用户另行确认后通过一次性 grant 读取最多 1 MiB 响应正文。此页不轮询、不发送/重发、不改变 ledger，不读取原始请求正文；筛选范围明确限于已加载 dispatch，尚无服务端筛选。关闭详情会 fence 晚到证据响应并清除加载状态。前端 ESLint + TypeScript `check`、全量 Prettier 和全量测试 **171 files / 1,474 passed**；Linux/Python 3.12 全后端 `make test` **13,846 passed / 79 skipped / 11 deselected**、Ruff check/format、Blocking IO **72 passed**，性能 repository/router 定向 **21 passed**；artifact/access migration/recovery **30 passed**。仓储分页按 API 稳定 cursor，dispatch UI 使用 offset 分批加载。最终 diff 检查通过。上述为候选本地验证，精确 SHA Actions 待提交后运行。

当前 UI 是证据浏览候选，不是可启动压测的完整 PERF-03。尚无执行 admission/worker、负载调度、真实请求发送或服务端 dispatch 筛选；本候选的一次性证据读取不是完整性能工作台交付。PostgreSQL 是目标数据库；`eval_0026..0027` 候选迁移已有定向 PostgreSQL live parity，但尚无完整 PostgreSQL 后端套件验证。SQLite 仍用于快速隔离仓储测试，不能代替 PostgreSQL parity。

本候选退出门槛还包括当前源码 Linux/Python 3.12 完整离线后端套件、Blocking IO、Ruff、迁移测试及精确 SHA CI。即使这些门槛通过，也只可将本响应 evidence 子切片标记为已验证；Worker/admission、授权读取/审计 API、执行控制 API、前端逐请求工作台、发生器健康/速率阶梯及真实目标授权依然未完成。

## 10. 公开依据

- GuideLLM 主页/功能：[GitHub README](https://github.com/vllm-project/guidellm)；输出格式、请求内容保留和 `sample_size`：[Outputs guide](https://github.com/vllm-project/guidellm/blob/main/docs/en/guides/outputs.md)。
- AIPerf 主页/功能/示例：[GitHub README](https://github.com/ai-dynamo/aiperf)；[`v0.13.0` raw export CLI definition](https://docs.nvidia.com/aiperf/v0.13.0/reference/command-line-options)；[`v0.13.0` profile export models](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/docs/tutorials/working-with-profile-exports.md)；[`v0.13.0` HTTP trace](https://github.com/ai-dynamo/aiperf/blob/v0.13.0/docs/tutorials/http-trace-metrics.md)；[PyPI metadata](https://pypi.org/project/aiperf/)；[GenAI-Perf migration and metric differences](https://docs.nvidia.com/aiperf/getting-started/migrating-from-gen-ai-perf)。Stable and prerelease capabilities must not be conflated.
- GuideLLM release 与发生器指标告警：[v0.8.1 release notes](https://github.com/vllm-project/guidellm/releases/tag/v0.8.1)；[versioned outputs guide](https://vllm-project.github.io/guidellm/0.8.1/guides/outputs/)；[PyPI release/provenance metadata](https://pypi.org/project/guidellm/0.8.1/)。
- vLLM benchmark CLI 的定位、client/server 指标与诊断开销：[official benchmark guide](https://docs.vllm.ai/en/latest/benchmarking/cli/)。
- NVIDIA 的迁移说明：[GenAI-Perf 官方文档](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_analyzer/genai-perf/README.html)。
- Ray LLMPerf 的归档/许可证元数据：[GitHub repository](https://github.com/ray-project/llmperf)。


### PERF-06 Synthetic-only Worker (2026-11-23)

### PERF-07 Bounded Concurrent Synthetic Worker (2026-11-24; source SHA `0dd39cb302814fb0fe7aea62e5e873d3f0009760`; 9/9 exact-SHA Actions passed)

PERF-07 extends only the explicitly invoked, admitted-run synthetic worker. One coordinator owns the frozen manifest and admits no more than `min(profile.concurrency, profile.max_in_flight)` dispatch tasks. Each task preserves its own claim -> ACK -> `send_started` fence -> built-in in-process synthetic transport -> observation and encrypted evidence identity. Request plus maximum response bytes are reserved before a fence is crossed; observed unused response capacity is released, so concurrent work cannot exceed the aggregate byte cap.

The first terminal-policy failure stops new admission. Already fenced peers are drained and durably observed when possible; a failed/uncertain fenced ordinal remains unknown and is never resent. Cancellation interrupts the run, records every open fenced dispatch as unknown, and marks the rest not dispatched. Warmup stays outside the measurement window; synthetic durations remain non-metrics (`metrics: null`). This slice adds no public worker endpoint, startup poller, external transport, subprocess, destination authorization, or real target/model load test. It does not complete cancel/drain operations for real workers or the performance UI/API.

`backend/app/evaluation/performance_worker.py` is an explicitly invoked App-domain worker for already admitted, frozen runs. It renders each frozen case input into the protected request body using the plan's existing `QAJSONBinding`, then passes those exact UTF-8 body bytes only to the built-in synthetic transport. The ordinal is separate synthetic failure-injection metadata, not injected into the user's request. It never reads gold/reference answers, invokes a model/target, opens network connections, schedules itself, exposes a public run endpoint, retries, or resends.

Migration `eval_0030` adds durable `execution_mode` (`target` by default; irreversibly changed to `synthetic_only` before the first dispatch) and the corresponding audit action. `get_run` does not project synthetic latency/QPS as target performance metrics. Request/response/aggregate byte bounds, request timeout, wall deadline, and optional measurement duration are honored; uncertain outcomes after the send fence become `unknown` and stop the run. Evidence uses the existing encrypted artifact and access-audit path.

**Acceptance boundary:** PERF-07 adds bounded concurrency only to the built-in synthetic transport. Its timings are not target/model load-test results. Durable real-worker scheduling and destination authorization, real transport, operator cancel/drain control plane, persisted immutable metric revisions/matrix projections, and runnable performance workbench remain future slices; the read-only metrics v1 projection is implemented. PostgreSQL is production default; SQLite is isolated test-only.

### PERF-08 Dataset-backed synthetic workload preparation (2026-11-26; candidate source `ed0af1a42f143ef271f314431149b557b5369e36`; integration pending)

The execution snapshot owner-scopes and revalidates the frozen scenario, performance plan, request-version metadata, and frozen dataset revision/hash before dispatch. It opens the encrypted request version through the audited boundary and renders per-case `FrozenRequest` values with the frozen QA JSON binding using a query containing only sample IDs and `input` values. A separate integrity check includes persisted reference/expected values when recomputing the frozen dataset hash; expected answers are not used to render or dispatch requests. It rejects per-request or cycle-expanded request-body budgets before any dispatch fence. Request bodies and credentials remain private in memory; ACK persists only exact UTF-8 byte count and SHA-256. The built-in synthetic transport receives those exact bytes and an out-of-band ordinal. No target/model traffic, target timing, or target performance metrics are produced.

Dataset hash verification and request rendering run in `asyncio.to_thread`; a heartbeat regression covers event-loop responsiveness. The sample-input query used for rendering omits reference data; the independent dataset integrity check still validates the full frozen hash. Invalid preflight remains terminal and audited; it does not dispatch or retry. See the [delivery status](DevPilot_Delivery_Status.md) for scoped verification evidence and the integration gate.


**2026-11-26 candidate verification note:** On `feature/perf-08-workload-preparation` at `ed0af1a42f143ef271f314431149b557b5369e36`, the focused Worker/repository/request-version/scenario/metrics suite passed **99 tests** on Windows/Python 3.12 and Ruff check/format passed. Windows Blocking IO remains **68 passed / 4 environment/platform failures** (POSIX mode assertions and missing `lark-cli`). These checks do not substitute for the locked Linux full suite, PostgreSQL parity, or exact-SHA Actions; the candidate is not merged and synthetic timings remain non-metrics.
