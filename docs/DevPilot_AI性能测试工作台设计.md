# DevPilot AI 性能测试工作台与负载工具集成

> 状态：目标规格，待实现。现有冻结计划可声明 `performance` 并配置并发/请求数；有界 QA 执行、派发和加密提取输出代码可复用，但性能阶段、请求级原生证据、指标聚合和独立 UI 尚未形成闭环。旧 `component-tests` / `evaluation-schedules` 是兼容路径，不作为新工作台基础。

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

性能方案必须有正整数请求预算和有界总字节预算；duration 只是较早的停止条件，不能取代请求上限或绝对 deadline。用户若选 duration 优先模式，仍填写可见 `max_request_count` 安全上限，并冻结停止原因为 duration 或 count。summary 显示 planned/actual request count、预热数、测量起止单调时钟、墙钟窗口、drain 时长和 `stop_reason`。

循环映射确定性规则：冻结 case IDs 按 `case_id` 字典序，warmup 和测量分别使用确定 seed/algorithm；第 `i` 个 dispatch 的 `case_id = ordered_case_ids[i mod N]`，`iteration_index = floor(i/N)`，并保存 `phase=warmup|measurement`、`profile_step_id`、`ordinal`、`dispatch_id`。启动前把实际有限 dispatch manifest/hash 固化，不能运行后重排或挑选成功项。

### 后续：开放到达率和负载矩阵

开放式 `constant_rate` / `poisson_rate` 用绝对计划时钟产生到达时间，按实际 `scheduled_at`、`sent_at` 记录迟到和发生器排队；不能因为慢响应自动降低目标到达率而不披露，否则会发生 coordinated omission。并发阶梯/速率阶梯每档独立测量窗口，warmup 不进入有效统计，档间按批准冷却并分别报告。Trace replay 只接收经授权并冻结 hash 的合成/脱敏 trace，不访问任意在线数据源。

同一 scenario 的多次 repeat 保存独立 run/measurement window，再按冻结聚合规则给出中位数/区间，不只保留最佳值。所有档位的 request/case/attempt 分母和失败都保留。多组件对比不简单汇总平均，不互相分摊计费或性能指标。

## 4. AI 性能指标契约

所有时间从负载 worker 单调时钟测量，明确包含网络/目标排队的端到端口径；平台队列时间与目标调用时间分开。percentile 使用版本化 quantile 算法，原始每次观测可复算；不足样本不生成虚假的 p99。

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

长尾样本少时显示“样本不足以稳定估计 p99”，仍保留有限样本 max 和 n；不以 null 代零。HTTP 2xx 但 JSON 协议错误不是成功输出；超时记录实际观察时间并标记 right-censored，不伪造响应完成时长。端到端测量不宣称目标纯推理时间。期望答案缺失不影响延迟/吞吐，expected 指标单独 `UNAVAILABLE`。

## 5. 请求级证据与数据模型

每次派发至少有唯一 `dispatch_id`、run/plan/snapshot hash、case ID/hash、循环 iteration、阶段/档位、预定/实际发送时间、客户端单调耗时、attempt 状态、HTTP status、错误分类、请求/响应 byte 数、request hash、raw response hash/media type、extractor/evaluator revision、token 数及其来源、stream timing、evidence refs。每个有效响应保存受控加密的应用层原始 response body artifact；任何响应 header 只保存 allowlist 元数据。

`dispatches` 是负载发送事实，`attempts` 若将来允许人工批准的额外发送必须独立建模；MVP 不重试，同一 ordinal 只对应一次平台发送，`delivery_unknown` 永远不自动重发。性能循环导致的同一 case 多次调用通过 dispatch ordinal/iteration 区分，不覆盖上一条 evidence。

建议 additive App migration：

- `evaluation_response_artifacts`：`run_id/ordinal` 复合引用、artifact id、scope、sha256、bytes、media type、capture status、key version、created time；大正文在受控 artifact storage，不存大 blob 到查询行。
- `evaluation_request_artifacts`：可选加密映射请求 body artifact、body hash、RequestSpec/binding hash、redaction profile。没有显式保存预算时仅保存 hash 和可重建版本引用。
- `evaluation_run_metrics`：run、scenario/step/repeat、metric key、nullable value、unit、applicability、sample count、population hash、aggregation version 和 source hash；同一测量 revision 不原地覆盖。
- 现有 dispatch journal 增加 `phase`、`iteration_index`、`profile_step_id`、scheduled/start/first-content/finished monotonic observation 和 `capture_status` 所需索引/约束。实施前检查现有复合 FK 与 SQLite/PostgreSQL parity，按迁移版本新增，不直接更改已部署迁移。

artifact 总预算提前 reservation；单条响应 cap、run response-byte cap、总 artifact cap、保留期限与解密权限互相独立。大文件访问须显式授权和审计；敏感正文 no-store，不回显路径；写入未知时按同一 artifact/request ID 只读核对，绝不重新请求目标。DB/文件不能单事务时使用临时文件→内容/hash 校验→原子发布→DB manifest；留下的孤儿仅按精确 receipt 清理。

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

## 7. 开源工具评估（2026-11-19）

查验公开仓库 README/API、许可证文件与 PyPI 元数据。版本、仓库活跃度会变；正式集成时还须锁定 release/commit、检查依赖和供应链、构建 SBOM 并对选定目标/数据做独立校准。

| 工具                                                                                                                                   | 查验结果                                                                                                                       | 可借鉴能力                                                                                                                                                                                                                        | 是否直接成为平台执行核心                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [AIPerf](https://github.com/ai-dynamo/aiperf)                                                                                          | Apache-2.0；GitHub main 可访问且 `archived=false`，2026-11-18 有更新；PyPI `aiperf 0.13.0`，Python `>=3.11,<3.14`              | concurrency、request-rate、trace replay、duration、ramping、OpenAI chat/completions/embeddings/audio/images/Responses 示例；README 展示 TTFT、第二 token、ITL、请求延迟、请求率、token throughput 与 JSON/CSV 导出                | **首选外部适配候选，不是核心依赖**。其进程直接调用 target 的模式若没有逐请求耐久 ACK/证据回调，不能覆盖 App 的 no-resend、固定请求映射和完整响应证据合同。先在合成 OpenAI-compatible 服务做接口/口径试验；失败保留原生 Worker。 |
| [GuideLLM](https://github.com/vllm-project/guidellm)                                                                                   | Apache-2.0；`archived=false`，核对 main SHA `a111aed14b86382269771a4c0e9646aeabab76d3`；PyPI `guidellm 0.8.1`，Python `>=3.10` | OpenAI-compatible/vLLM、同步/并发/throughput/constant/Poisson/sweep profiles、按 request/duration 约束、合成/本地/多模态数据。官方输出文档显示 JSON 默认保留所有请求数据，可用 sample_size reservoir 限制全文档样本；CSV 只有汇总 | **第二外部适配候选**，适合真实流量形态、并发/到达率实验及多模态能力对照；同样不能仅导入聚合 CSV。完整输入/输出文本不等于原生 HTTP body/headers，也不能取代逐次 durable dispatch。                                               |
| [Ray LLMPerf](https://github.com/ray-project/llmperf)                                                                                  | GitHub `archived=true`；Apache-2.0；最后推送 2024-12-09                                                                        | Ray 并发 token benchmark、单请求/总体吞吐与延迟思想                                                                                                                                                                               | **不采用**：归档项目不适合作为新基线；可作历史公式参考，不 fork/vendoring。                                                                                                                                                     |
| [NVIDIA GenAI-Perf](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_analyzer/genai-perf/README.html) | NVIDIA 官方文档明确标注 phased out、停止新功能，并指向 AIPerf                                                                  | 旧版 Triton/NVIDIA serving 口径参考                                                                                                                                                                                               | **不新接入**：新需求评估 AIPerf，保留 GenAI-Perf 兼容/历史报告只读说明。                                                                                                                                                        |

决策：平台官方统计仍由 DevPilot `devpilot` 的版本化纯指标核心计算，初版用自有有限负载调度器通过 App durable dispatch/evidence worker 执行。AIPerf 是第一个外部 adapter spike 候选，GuideLLM 是可选第二候选；在 adapter 能将每个开始发送的请求与 DevPilot dispatch ACK、case/iteration、原生响应 hash、错误和 token timing 一一对应之前，外部工具结果只能标为 `external_unverified / NOT_EVALUATED`，不能混入平台评估、通过率或正式报告。

第三方工具接入 gate：

1. 选定具体 release/commit 与 license/SBOM；仅在隔离容器运行，固定输入/输出目录和网络目标 allowlist，不接受用户任意 CLI、插件、模板代码或任意 URL。
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
- `devpilot.qa_stream_metrics`、`devpilot.qa_cv_metrics` 等纯指标工具可被纳入版本化 metric adapter；CLI 投影不能当作线上 evidence store 或执行引擎。

旧 run 永久保留其 `legacy`/schema revision。新旧结果以明确迁移/对照报告比较，不批量重新计算、不将旧 PASS 升级为新口径 PASS。先 additive API/UI 和新计划 revision，再按已归档历史逐步隐藏旧写入口；生产数据迁移需备份、owner/组件核对和回退演练。

## 9. 开发切片与验收

| 切片                      | 范围                                                                                                        | 退出条件                                                                                              |
| ------------------------- | ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| P1 场景契约               | profile schema、case-cycle manifest、count/duration stop、预算 preflight                                    | 无 expected 用例可选；请求数越过数据集大小按冻结序列循环；任何无上限/溢出/空数据/并发越界在调用前拒绝 |
| P2 请求级 ledger/evidence | dispatch phase/iteration、raw response artifact、request/response hash、allowlist headers、分预算和保留审计 | 逐 ordinal 完全可对账；重复 case 不覆盖；超过预算部分 run 明示 incomplete；取消和未知提交不重发       |
| P3 纯指标核心             | 延迟/错误/吞吐/分位数/token/stream/source/applicability                                                     | 人工可算小 fixture 对照；warmup/drain 不混入 measurement；失败/censored/p99 小样本等分支全测          |
| P4 性能计划/授权 API      | 冻结 scenario、执行 admission、预算和 run receipt                                                           | 确认绑定 exact plan/data/endpoint snapshot，权限/目标/预算变更撤销确认，重复写原 ID 对账              |
| P5 性能工作台             | 配置步骤、预检、阶段运行、summary、档位比较、request table/detail                                           | 计数与 DB/hash/summary 相符；可从 summary 下钻任一失败或未知请求；空/失败/取消/部分运行无假绿色       |
| P6 AIPerf adapter spike   | 隔离适配器、合成校准、协议和依赖扫描                                                                        | 未通过五项第三方 adapter gate 前不进入生产执行选择；不加用户可任意选择工具开关                        |
| P7 场景矩阵               | 并发/速率阶梯、重复/冷却、worker 资源监测与 benchmark compare                                               | 每档结果独立保存，可复算，不挑最好档，不把发生器瓶颈写成目标瓶颈                                      |
| P8 多模态/Agent workload  | 图像/音频/embedding/多轮轨迹专用 schema                                                                     | 各 adapter 有 request/evidence/token/质量定义；单一 text JSON schema 不假装通用                       |

回归覆盖 request count 大于 N 的 exact cycle、duration 优先终止、warmup、steady window、drain 截尾、固定时间戳、延迟分位数、rate scheduling/迟到、token source、无流式 N/A、流被 buffer、cancel/lease/fence/unknown delivery、超限响应、artifact partial write 与重建。CI 只用确定性本地假服务；真实服务需有隔离手动授权的验收计划。

## 10. 公开依据

- GuideLLM 主页/功能：[GitHub README](https://github.com/vllm-project/guidellm)；输出与逐请求保留：[Outputs guide](https://github.com/vllm-project/guidellm/blob/main/docs/en/guides/outputs.md)。
- AIPerf 主页/功能/示例：[GitHub README](https://github.com/ai-dynamo/aiperf)，[PyPI metadata](https://pypi.org/project/aiperf/)。
- NVIDIA 的迁移说明：[GenAI-Perf 官方文档](https://docs.nvidia.com/deeplearning/triton-inference-server/user-guide/docs/perf_analyzer/genai-perf/README.html)。
- Ray LLMPerf 的归档/许可证元数据：[GitHub repository](https://github.com/ray-project/llmperf)。
