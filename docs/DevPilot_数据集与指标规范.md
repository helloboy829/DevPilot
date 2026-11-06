# DevPilot 数据集与指标规范 v1.0

> 2026-11-06；**目标契约，待实现**。本文件为数据质量、计数、状态和通过判定的唯一规范；不得由 Prompt 或前端自行改写。

## 1. 从材料到可验收数据

1. 材料登记：保存来源、作者/提供方、授权范围、敏感级别、版本、内容 hash、用途与保留期限。
2. 任务建模：明确任务类型、业务分布、风险、允许输出、不可接受行为、正负例与边界。
3. 形成候选：历史真实记录优先，公开基准需授权和适用性审查；合成用于补覆盖。
4. 清洗：格式、文件可读性、重复/近重复、PII、标签冲突、时间与来源泄漏检查。
5. 标注：标签准则、可接受变体、数值容差、证据位置；高风险/争议双人独立复核。
6. 分层与隔离：开发/生成集、裁判校准集、冻结验收集按主体/来源/时间分组隔离，而非仅随机按行切分。
7. 质量评审：自动检查与人工抽检通过后批准；冻结 manifest、case ID、内容 hash 和审批记录。
8. 执行后：失败难例先进入候选池；经审核后发布下一数据版本，不能回写当前验收集。

提测方样例输出只是候选预期，不天然是金标；不能用被测模型自己的答案同时当 reference。关键标签应由独立授权来源/人工核验。固定公开 benchmark 也可能被目标训练见过，必须说明泄漏风险，不能将其得分直接当业务质量。

数据状态：draft → in_review → approved → frozen → retired。退回创建修订；frozen 内容不可修改，纠错创建新版本。外部大文件用受控 artifact 引用，不允许 cURL 指向任意本机路径。

## 2. 数据记录与质量卡

每条 case 至少：case_id、task_type、input、expected、source_refs、origin(real/synthetic/benchmark)、split、slices、label_status、rubric_ref、sensitivity、content_hash。
label_status 采用 unreviewed / pending_review / approved / rejected；冻结验收项必须 approved，其余只能保留在候选版本。
图像另记 asset ID/hash、尺寸、标注坐标约定、类别字典；多轮 Agent 另记初始环境、目标、轨迹约束与 reset 策略。

质量卡至少包含：
- 真实/合成比例、来源数、时间范围、样本数、类别与关键切片覆盖。
- 去重方法/阈值、train/calibration/acceptance 交叉泄漏结果。
- 标注版本、复核比例、独立一致性/冲突及裁决记录。
- 授权覆盖率、PII/敏感项处理、无法代表的业务范围。
- 各关键切片最小样本数、统计不确定性和审批人。

质量门槛由项目审批配置。格式/授权/关键标签缺失为硬阻断；不能以“生成了很多条”代替质量通过。样本量按业务风险、预期通过率和允许误差确定，报告区间及样本不足提示，不写死所有项目同一 N。

## 3. 场景构建要求

| 任务 | 必须覆盖 | 参考标注 / 指标 |
| --- | --- | --- |
| 图像分类 | 正负、各类别、难负例、模糊/遮挡、域外；来自真实业务的合法样本 | 类别、混淆矩阵、accuracy、precision/recall/F1；不均衡时报告宏平均与关键类 |
| 目标检测 | 空图、小/密集目标、遮挡、尺度变化 | 类别/框、坐标与 IoU 匹配规则；mAP、precision/recall；阈值约定固定 |
| OCR | 字体/语言、倾斜/噪声、版式和空白 | 转录与归一化版本、CER/WER；字段完整性另测 |
| QA / RAG | 可回答、不可回答、歧义、过时/冲突证据、多跳与拒答 | 答案要点、可接受变体、必需引用和证据段；事实/相关性/完整性/拒答 |
| 结构化模型 | 边界数值、缺字段、异常/无效输入 | schema、字段约束、绝对/相对容差和单位 |
| Agent | 多轮依赖、工具失败、无权限操作、状态复位 | 任务成功、步骤/成本、副作用与越权；终态之外验证环境变化 |

CV 图像增强不能凭空创造可信标签；生成图像须复核标签和域差异。不得把答案塞进目标组件请求；对 RAG 只传真实业务允许的检索上下文，reference answer 仅裁判可见。

## 4. 效果：计数与通过率

冻结数据中的有效验收项总数为 **N_total**，冻结前批准排除项必须留理由；执行后不能静默排除失败、超时或难例。
每项主 outcome 恰为以下之一：PASS、FAIL、ERROR、PENDING、NOT_RUN。

- PASS/FAIL：有效返回且完成判定。
- ERROR：超时、鉴权/网络/协议/目标异常等，错误类型单独记录。
- PENDING：已返回但待裁判/人工复核。
- NOT_RUN：尚未调用或取消前未执行。

恒等式：N_total = N_pass + N_fail + N_error + N_pending + N_not_run。

**业务通过率 pass_rate = N_pass / N_total**。N_total=0 时为 null，判 BLOCKED，不能当 0% 或 100%。
验收主通过率建议报告二项比例区间（如 Wilson 95% 区间，方法/置信水平随方案冻结）；存在同源/同主体相关样本时声明独立性假设不成立，必要时按组 bootstrap，不能用大规模近重复制造虚假窄区间。区间是额外证据，是否用区间下界作门槛由方案事先批准。

辅助：coverage=(N_total−N_not_run)/N_total；已判定质量率=N_pass/(N_pass+N_fail)，仅辅助，不能替代业务通过率；错误率=N_error/N_total。
所有结果同时展示分子分母、关键切片、ERROR/PENDING/NOT_RUN 和统计区间；比例存 0–1，UI 展示百分比。

规则判定优先；语义相近按审批 rubric，不要求逐字一致。数值容差如 abs(actual−expected) <= max(abs_tol, rel_tol×abs(expected))，单位与归一化版本必须固定。
LLM 裁判返回结构化维度、理由、证据与不确定性；对人工校准集测一致性与误放行，定期抽检 PASS/FAIL。裁判 API 失败不是目标答错，也不能由自报 confidence 自动通过。

## 5. 性能：测量口径

时间用客户端单调时钟；从 Worker 实际发起请求到完整解析业务终态，含网络和目标排队，不含平台待执行队列。另记平台排队耗时。跨服务无时钟对齐时不声称服务端纯推理时间。

| 指标 | 定义与边界 |
| --- | --- |
| latency_ms | 请求发起到有效业务终态，报告 mean/p50/p95/p99；失败单列耗时/超时，不静默隐藏 |
| ttft_ms | 仅文本流式已启用且内容增量可观测：请求发起到首个非空可展示生成内容 delta；measurement_kind=first_content_delta，chunk 不等于单 token；忽略心跳/角色/元数据 |
| inter_token_latency_ms | 有 token 时间戳时测间隔；chunk≠token，无 token 时间不得假装精确 ITL |
| tpot_ms | 可选：(末 token 时间−首 token 时间)/(输出 token 数−1)，需 >1 token；口径与 ITL 区分 |
| success_qps | 测量窗内成功完成的请求数 / 测量窗秒数；attempt_qps 另报 |
| output_throughput_tok_s | 测量窗内成功请求的输出 token 总数 / 测量窗秒数；是整体吞吐，不能均值化每请求 TPS 替代 |
| per_request_output_tok_s | 单请求输出 token / 明确约定时长；不同于整体 TPS |

Token 来源标为 provider_usage / tokenizer / estimated，并记录 tokenizer 名与版本、输入/输出分开；不可用时 null，不能以字符数冒充精确 token。不同计数源不直接排名。
TTFT 不可观测记 NOT_APPLICABLE 或 UNAVAILABLE，不能记 0；前者为普通非流式/CV、未启用文本流式或仅进度/状态事件等不适用调用，后者为应可测却被缓冲、无内容或解析失败。不得以首 HTTP 字节/完整响应延迟替代。Agent 最终答案流另记 first_answer_delta_ms，不能与底层模型纯 TTFT 混比。旧接入检查通过不能替代当次测量。整流被缓冲后一次交付时可另存 client_first_content_ms（含缓冲）与 stream_valid 标记，但不反推服务端首 token 时间，默认不作为已验证的流式 TTFT 采信；例外口径须计划事前明确。服务端自报指标单独存 reported/server，不混入客户端分位数。

## 6. 负载设计

- 固定 workload 版本：输入长度/图像大小、输出上限、流式参数、缓存/会话、随机种子和业务比例。
- 首版封闭并发阶梯；到达率模式后续单独实现。并发 C 不等于每秒请求数。
- 每档配置 warmup、请求数或时长停止策略、drain 上限、超时、重复次数、冷却和授权窗口。
- 测量窗：warmup 后正式请求开始，到该档测量请求完成或按超时/drain 截断；记录实际边界，禁止跨档混算。
- 每档至少满足最小有效样本/时长要求；p99 小样本须警告；每次重复单列，并按事前批准规则汇总，不事后挑最好的一次。
- 默认重试 0；若允许，原请求与每次 attempt 都保存，成功/失败口径和耗时不因重试被美化。
- 阈值逐个必测档检查，不仅最高档；最大可承受并发是全部条件满足的已测档，不外推。
- 监控 Worker CPU/网络/事件循环，排除发生器瓶颈；性能任务中断不能拼接为一次有效连续压测。

## 7. 状态与判定契约

**执行 status**：queued、running、cancelling、completed、failed、cancelled、interrupted。
completed 仅表示执行流程完成，绝不等于验收通过；failed 是执行器错误，目标个别请求错误通常作为观测保留，执行可 completed。

**验收 verdict**：NOT_EVALUATED、PASS、FAIL、NEEDS_REVIEW、BLOCKED。
**metric applicability**：APPLICABLE、NOT_APPLICABLE、UNAVAILABLE。

确定性决策顺序：
1. 已确认的硬安全违规/硬失败可判 FAIL，保留缺证据说明。
2. 缺授权/必需指标/必要运行/最小样本、未执行项或中断 → BLOCKED。
3. 仅剩标签/语义争议或必需人工抽检未完成 → NEEDS_REVIEW。
4. 证据齐全后按冻结阈值判 PASS/FAIL。

明确的目标错误率/成功率失败即 FAIL；若全部调用失败，还缺延迟，绝不 PASS，可按成功率硬门槛 FAIL 并附缺指标。阈值不得静默默认成 0；方案必须显式定义成功率/错误预算及最小成功数。不适用指标不能成为必需阈值，方案审批时拒绝。
项目总 PASS 需要全部必需效果/性能运行通过、数据质量获批、无待审阻断、报告获批；两个分数加权平均不能掩盖一侧失败。

## 8. 复现与复测

运行快照保存：组件/endpoint 版本与指纹、dataset manifest hash、计划/阈值、adapter/extractor、rubric/裁判模型与参数、代码版本、环境、seed、每次观测与 artifact hash。
复测更换组件版本，但默认沿用冻结数据与方案；阈值/数据变更创建新基准并解释不可比原因。失败子集复测只能关闭对应缺陷，不能替代全量验收。指标与报告可离线重算，重判产生新版本，不覆盖旧证据。报告绑定 assessment_revision，不能随当前 run 摘要静默变化。

## 9. 人工复核与导出的一致性约束

ReviewTask.status 为 queued/in_review/escalated/resolved/cancelled；不等于 case outcome。自动 PASS 的必需抽检未完成时，保留 provisional outcome，但 run 不能正式 PASS；抽检只覆盖实际审核的样本。资料不足的决定不能解决为 PASS，目标 ERROR/NOT_RUN 不能用语义复核改通过；裁判服务故障且目标已有有效输出则为 PENDING。
原始观察、自动 Judgment、人工 Decision、策略 Resolution 和 RunAssessmentRevision 分层。解析后的 outcome/计数仍以冻结 N_total 为分母，形成不可变 assessment；金标错误须新数据版本/基准，不修改旧 expected 刷分。性能复核不编辑测量值，无效测量补证或重跑。

调试、平台执行和导出遵循同版本 RequestSpec、adapter/extractor、结果 schema、聚合器和阈值；外部环境差异须披露。execute_only 导出可只采集结果，verdict=NOT_EVALUATED，不是完成效果评测；外部结果即使自报 PASS 仍需隔离验证/采信和完整门禁。详见[接口调试与脚本导出](DevPilot_接口调试与脚本导出设计.md)、[人工复核工作台](DevPilot_人工复核工作台设计.md)。
