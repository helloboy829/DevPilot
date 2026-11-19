# DevPilot 效果测试工作台设计

> 状态：目标规格，待实现。当前已有冻结计划、显式执行授权、派发账本、加密提取文本和逐条人工复核；尚无完整原生响应保存，也没有独立的效果结果浏览器。实现状态以[交付状态](DevPilot_Delivery_Status.md)为准。

## 1. 目标与边界

效果测试工作台要让评测人员从某次冻结运行进入，快速判断整体运行是否完整、哪些样本失败或待审，并能逐条核对输入、实际请求、模型原始响应、解析结果、参考答案/评估依据、技术观测和人工复核历史。

工作台读取运行快照及不可变证据，不直接调用目标、不重跑、不修改输入/原始响应或自动生成审批。发送仍由单独授权的执行流程完成；查看敏感输入、expected/reference 和原始请求/响应都要经过独立的显式访问动作并记录审计。盲审阶段按冻结的盲审规则隐藏参考答案；获得对应任务权限且流程允许揭盲后才能访问。调用完成、结构有效、人工判定和最终批准分别显示。

无 expected 的输入用例仍可进行已授权调用并采集原生响应。详情显示“无参考答案”；金标对比指标标记 `UNAVAILABLE`。若已有冻结 schema/规则/rubric 或人工评估，则显示对应依据和结果；若方案将缺失的 reference 指标列为必需且无等价的独立方法，assessment 为 `BLOCKED`；没有任何适用依据时为 `NOT_EVALUATED`。这些评估状态不回头拦截授权采集，也绝不把请求成功显示成效果通过。

## 2. 用户流程与页面结构

工作台位于项目评测区，分为“运行列表 / 效果结果 / 性能结果”视图。效果视图只呈现 `mode=effectiveness` 的运行；不把人审汇总伪装成自动效果分数。

1. 用户显式加载项目的运行列表。筛选组件、计划版本、运行状态、时间、数据集版本、整体 verdict 和复核状态；列表分页游标稳定，服务端结果按创建时间倒序，不硬截断最近 200 条。
2. 打开运行后先显示固定运行快照：组件/请求版本、数据集版本与 hash、计划和评估依据版本、执行时间、执行状态、verdict、ALL 分母和完整性 blocker。
3. 样本表按冻结 `case_id` 顺序分页；列显示 case、输入摘要、参考答案状态、请求/技术状态、延迟、适用评估指标/结果、复核状态和证据可用性。搜索/过滤不改变已冻结分母。
4. 选择样本后打开详情侧栏或详情页。窄屏改为全页分段，不压缩成不可读的三列。
5. 详情按“输入与请求、返回与解析、效果判定、技术证据、人工复核”分区。原生请求/响应默认收起；用户明确点击并具备权限后才读取敏感正文。切换项目、运行或样本时立即清除上一个对象的明文内容。
6. 返回列表保留页内选择与筛选；刷新、账户变化、项目切换和失效 revision 清空明文并要求重新加载。下载证据需要单独的显式动作和权限，不从页面 mount 或后台轮询触发。

列表和详情建议布局：

```text
运行摘要 / 固定快照 / 评估结论与 blockers
筛选栏：样本 ID、请求状态、评估状态、reference 状态、复核状态、切片
样本表：case | 调用 | HTTP | 延迟 | 指标 | 复核 | 证据
详情：输入/映射请求 | 原生响应/解析结果 | 依据/判定 | 技术观测 | 决定历史
```

## 3. 逐条结果视图合同

### 样本列表 DTO

`GET /api/evaluation/projects/{project_id}/runs/{run_id}/cases` 返回权限过滤的固定分页。响应元数据包含 `scope=effectiveness_result_list.v1`、`run_id`、`snapshot_hash`、`assessment_revision`、viewer visibility scope/revision、`next_cursor`、固定 `total` 和只按当前 viewer 可见字段计算的计数快照。游标绑定可见性 scope/revision，任务/轮次/揭盲变化后旧游标失效。每行至少包含：

- `case_id`、冻结 ordinal、输入摘要/hash、`reference_status`、来源引用摘要和切片。
- `dispatch_state`、技术 kind、HTTP status、send/start/end 时间、`latency_ms`、响应字节、错误类别、请求/响应 evidence 是否存在及其 capture status。
- 每个 metric 的 `value`、unit、`applicability`、分子/分母或 null reason；自动判断 revision 和判定依据 hash。
- 经当前用户任务/轮次/揭盲状态过滤后的人工决定摘要、决定 revision、待办状态；人工结果与自动判断分字段返回。盲审期间只返回本人可见的任务状态/本人决定，不返回其他审核者的决定、理由、身份或裁判参考答案；揭盲须由合同授权的独立状态转换产生并审计。

游标绑定 run、snapshot hash、查询条件 hash、viewer visibility scope/revision 和最后一条稳定排序键；不支持客户端传入 owner。游标/排序/计数不能触发解密 reference 或响应，且只能统计该 viewer 当前有权看到的字段，不能泄漏盲审决定数量。

### 单条详情 DTO

`GET /api/evaluation/projects/{project_id}/runs/{run_id}/cases/{case_id}` 只返回普通元数据：case/dispatch 身份、输入摘要/hash（不含正文）、来源定位、reference 是否提供及状态、RequestSpec/binding revision、映射后请求 hash、response hash 或 prefix hash/大小/媒体类型/capture status、已解析输出摘要、评估指标、错误类别、技术时间和按当前用户任务/轮次/揭盲状态过滤的复核历史摘要。决定、理由、审核者身份、rubric 与 reference 按字段单独授权；盲审期间不得从 summary、列表、详情或游标计数侧信道泄露他人决定。输入全文、expected/reference 内容与原始请求/响应不由列表或普通详情自动展开。

每次 dispatch 都必须记录实际交给 HTTP transport 的应用请求正文 SHA-256、字节数，以及 RequestSpec、binding、adapter/serializer revision；这证明确定性重建与实际发送内容一致。原始请求正文是否保存为加密 artifact，必须由冻结的 `capture_profile` 和预算预先决定。未保存时，详情只能从冻结输入与确切版本重建，并校验重建 hash；缺版本或 hash 不符时标记不可重建，不得伪造原始请求。URL 只留 allowlist 投影的 scheme/host/port 和经审查的路径模板，不保存原始敏感 path/query、API key、Authorization/Cookie 或代理头。不得把 expected、rubric 私有答案或裁判上下文放入目标请求。

### 敏感证据打开

正文通过独立动作取得：`POST /api/evaluation/projects/{project_id}/runs/{run_id}/cases/{case_id}/evidence-access`，body 为严格 DTO：证据类型（input/reference/request/response/stream）、`confirmed=true` 和当前 evidence hash。服务端重新验证项目归属与成员权限、精确任务指派和盲审阶段、运行/计划/hash、证据状态与大小，追加含访问者、对象、类型和授权依据的审计后返回短时 opaque `access_id`。随后 `GET .../evidence/{access_id}` 返回 `Cache-Control: no-store` 的受控内容或有界 Range 流。input/reference 读取与原始请求/响应读取分别授权、分别审计；reference 的明文访问不得绕过盲审。项目成员资格本身不授予盲审任务中的他人决定、理由或裁判答案访问权。失败不返回路径、凭据或解密异常。

打开动作不修改 run/assessment。下载作为独立确认操作；不能以图片/HTML/SVG inline 渲染，不能通过未转义 Markdown 展示，二进制与超限正文走附件下载。expected/reference、rubric 私有答案和裁判上下文始终与目标请求隔离。原生 response artifact 的规范字节是 HTTP transfer framing 移除后、`Content-Encoding` 解码前由 transport 暴露的 response body bytes；SHA-256、字节数和上限均针对这组字节。`Content-Encoding`/charset 仅来自安全 header allowlist；解压或字符集解码形成独立、有版本的解析投影，不覆盖原始 artifact/hash，并受单独解压后大小上限约束。超过捕获上限时最多消费并计数到 `max_bytes + 1`，只保存不超过 `max_bytes` 的前缀并记录 `truncated`，不得将前缀伪称完整响应。HTTP headers 仅保存安全 allowlist 元数据，不保存凭据、Set-Cookie、任意回显头。

`capture_status` 使用闭合枚举：`pending`、`complete`、`partial`、`truncated`、`policy_skipped`、`not_received`、`write_failed`、`write_unknown`、`unavailable_legacy`。`complete` 的 hash 覆盖完整规范 response body；`partial`/`truncated` 只可保存 `captured_prefix_hash` 和已捕获字节数，不能伪装成完整 response hash。`truncated` 表示超过冻结捕获上限；`partial` 表示传输/worker 中断导致 body 不完整。新 manifest 从 `pending` 进入一个终态；只允许 `write_unknown` 经同一 artifact ID 对账后确认为 `complete`、`partial`、`truncated`、`policy_skipped`、`not_received` 或 `write_failed`。`unavailable_legacy` 仅用于历史数据且为终态。dispatch 前预建稳定 artifact ID 和 `pending` manifest；响应到达后以同一 ID 写临时加密对象、校验 hash/size、原子发布对象，再写入 durable receipt/manifest。数据库结果未知时只按原 artifact ID 只读对账，不重发目标请求、不创建替代 ID；已发布但未被 manifest 引用的对象进入隔离治理，只有确定无引用且超过保留期后才可按精确 ID 清理。`write_failed`/`write_unknown` 不抹去已发生的 dispatch/响应观察，也不从冻结分母剔除；依赖完整 raw evidence 的评估为 `BLOCKED`。显式 `policy_skipped` 只有在冻结方案允许且其他判定证据足够时才可评估。旧 run 为 `unavailable_legacy`，不补造正文。

### 解析与评估视图

原始 body、RequestSpec extractor 提取值、JSON 结构视图和 evaluator 输出是独立对象：

- 原始 body 用固定文本/JSON viewer 展示；JSON pretty-print 是视图层转换，不覆盖原文/hash。
- extractor 结果显示 `extractor_id/version`、路径、提取值和验证错误，来源可追到原始 body hash。
- effect evaluator 显示规则/rubric/参考答案 revision、逐维度结果、证据/理由与 `APPLICABLE/UNAVAILABLE/NOT_APPLICABLE`；裁判建议和人工决定分栏。
- 运行状态为 `completed` 不自动带 `PASS`。`NOT_EVALUATED` 表示没有适用依据；`BLOCKED` 表示缺少方案必需证据；`PENDING` 仅表示已建立的人工/裁判任务未完成。

## 4. API 与权限实现次序

沿用 `/api/evaluation` 的同项目 owner/permission guard、no-store 和严格 DTO。把现有 `/review-runs`、`cases` API 保留为人审兼容入口；结果浏览器加新的 result schema，避免将 review DTO 扩展成无边界的通用大对象。

1. `GET /projects/{id}/runs`：筛选、稳定游标、模式过滤、非敏感运行摘要。
2. `GET /projects/{id}/runs/{run_id}`：快照、metric summary、固定分母、完整性状态和 blocker。
3. `GET /projects/{id}/runs/{run_id}/cases`：稳定分页/筛选，不解密内容。
4. `GET /projects/{id}/runs/{run_id}/cases/{case_id}`：单条非敏感证据元数据、解析视图、评估与审查 revision。
5. `POST .../evidence-access` + `GET .../evidence/{access_id}`：双步骤明文访问、审计、短时绑定、大小/媒体类型限制。
6. 可选 `GET /projects/{id}/runs/{run_id}/events`：仅在服务端已有确定事件源时支持显式订阅；否则用用户触发的刷新，不加入 mount-fetch、静默长轮询或自动重试。

人审写接口维持既有 revision/hash CAS 和追加式决定语义。结果浏览 API 不改变复核任务权限、盲审、仲裁和签核合同；owner 复核兼容 API 不能直接充当盲审 reviewer 的证据授权。访问输入全文、参考答案或决定历史不因用户属于项目成员而自动放宽任务指派、盲审揭盲规则或运行内职责分离。

## 5. 前后端模块落点

- 前端复用 `EvaluationExecutionPanel` 的显式授权和 `EvaluationReviewPanel` 的页面内存、late-response fence、ref lock 及同对象重载习惯；新增 `EvaluationResultsWorkspace`、`EvaluationRunSummary`、`EvaluationCaseTable`、`EvaluationCaseDetail`、`EvidenceViewer`，复核仍由现有独立复核组件处理。
- 新结果页面把 query 参数限制为非敏感过滤器，不将输入、expected、response、token 或理由放 URL、local/session storage、全局持久缓存或遥测。
- 后端 `app.evaluation` 维护 result query、证据权限和 access audit；`devpilot` 纯核心维护版本化结果 DTO/metric projection；router 只组合服务，不自行解密或判分。
- 原始证据使用 App 自有 artifact abstraction，不复用线程 artifact 路径或 Harness workspace ACL。数据库保存 artifact ID、hash、大小、状态、密钥版本和保留规则；内容加密且由受控存储保存。

## 6. 兼容和迁移

当前 `evaluation_output_evidence` 是加密提取文本，不是原生响应；新字段/表必须 additive migration。历史记录标记 `raw_response_capture=unavailable_legacy`，不从提取文本伪造原始 body，也不补造旧请求正文。

实施分三步：先并行新增原生 evidence artifact 与 hash/allowlist metadata 写入，确认事务/未知写入恢复；再新增权限受控结果 API 和 UI；最后为已冻结旧计划提供只读兼容展示。只有新 plan schema 显式选择 `capture_profile` 并冻结 evidence budgets 后才承诺新证据完整性。

## 7. 开发切片与退出条件

| 权威功能 ID      | 工作内容                                                                                                 | 退出条件                                                                                                                                                           |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| EVID-02          | 共享 attempt 的有界原生请求/响应 evidence、稳定 artifact ID、capture ledger、加密存储/receipt 与失败恢复 | 字节层/hash fixture 一致；状态闭合；partial/truncated 仅有 prefix hash；超限/缺密钥/写失败不标完整；未知写入 exact-ID 对账且绝不重发目标；SQLite/PostgreSQL parity |
| EFF-01           | RunSummary / CasePage / CaseDetail DTO、cursor、过滤与权限                                               | owner 隔离、跨项目 ID、篡改 cursor/hash 均拒绝；查询不解密 expected/raw body；盲审列表无他人决定侧信道                                                             |
| EFF-02           | 分类型 evidence grant/access ID、访问审计、盲审/任务权限与有界读取                                       | 越权、错误轮次、reference 揭盲前、未知 artifact/hash 与失效 grant 均拒绝；no-store、Range/HTML/SVG/secret 回归                                                     |
| EFF-03           | 运行摘要、case table、分页/筛选、详情 tabs、无 evidence/无 expected/错误/部分 run 状态                   | 切项目迟到响应丢弃；普通详情无敏感正文；view/download 需显式授权，键盘和窄屏可用，大样本不自动加载正文                                                             |
| ASMT-01 / REV-01 | 自动依据、metric applicability、reference status、按任务可见的人工 revision 联动                         | fixture 可重算且 hash 固定；人审不覆盖 observation/automatic judgment；无依据不得 PASS；盲审历史按揭盲规则过滤                                                     |

实现顺序与唯一功能 ID 以[模块进度](DevPilot_实现进度与下一步.md)为准；本表不另造 E1/E2 编号。每个切片先添加失败后端/前端回归；合成 Mock 服务验证，无真实模型或目标默认访问。完成代码后还需准确 SHA CI 和业务端验收，不用旧 run/旧 CI 当证据。
