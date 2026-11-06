# DevPilot 接口调试与脚本导出设计

> 2026-11-06；目标设计，**当前尚无该调试台、RequestSpec 契约或独立脚本导出器**。本轮只更新设计，不提供伪装成已验证的 runner。

## 1. 产品决策：一份规范，多个执行入口

用户或 Agent 都可以协助验证 cURL，但必须走同一套受控后端；正式评测以平台内直接执行为主，脚本导出是可选交付方式，不要求评测者先写代码。

~~~text
提测 cURL / 手工编辑
  → 安全解析 → RequestSpec 草稿 → 保存不可变 EndpointRevision
  → 调试检查 Check → 人工确认 Confirmation
  → 绑定数据输入与提取器 → 数据/方案审批冻结
      ├─ 平台：持久化 Job → 共享执行核心 → 观测/裁判/指标
      └─ 导出：固定版本核心 + 配置 + 获准数据 → 独立测试工程
                                              → 外部结果隔离导入/复核
~~~

**不采用“每次让 LLM 从零写效果/性能脚本，再信任脚本自报结论”的主路径。** 配置、adapter、统计和阈值来自同一领域核心；导出器以受控模板组装。LLM 只可起草非标准 adapter，须隔离测试、审核和版本发布后才能成为能力。
这不是完整 Postman 克隆：不做任意脚本钩子、插件市场、通用协作云和全部协议兼容；重点是接入评测、证据与复现。

## 2. 调试台的人机操作

### 2.1 布局

- 顶部：项目、组件/版本、环境及执行位置（例如“内网 Worker A”，不是浏览器），接入确认状态。
- 左侧：已保存请求修订、最近脱敏检查记录；复制为新修订而非修改旧证据。
- 请求区：粘贴 cURL / 表单切换，method、URL、query、headers、鉴权引用、JSON/body、受控附件、超时与响应上限；敏感值只显示掩码。
- 输入绑定：明确 case 的哪些字段写入 body/query/multipart，显示用一条样例渲染后的请求；expected、rubric、金标禁止映射给被测端。
- 响应区：HTTP 状态/耗时、raw/pretty、提取结果、业务断言、响应体积、错误分类、流式事件时间线；raw 也经过权限与脱敏控制。
- 操作区：“解析预览”不联网；“发送一次”需批准目的地和调用权限；“确认此修订”只由有权的人执行；“创建评测方案 / 导出测试工程”显示各自前置门禁。

错误保留在对应字段/检查详情，不只显示 toast。检查有请求 ID、取消、明确截止时间和费用；Agent 不能通过自然语言授权给自己加并发。

### 2.2 什么叫验证通过

分别记录：目的地/证书、连接与鉴权、HTTP/协议、业务终态/错误码、输出提取、必要断言、流式可观测能力。HTTP 200、收到一段文字、声明支持 stream 均不足以单独证明接口可用于评测。
一次成功只证明当时、该环境、该修订的样例成功；**不证明组件稳定，不自动批准压测，也不代替效果测试**。如需小样本稳定性探测，另设有预算的检查方案。

Confirmation 绑定 component_version、endpoint/request hash、environment_revision、adapter/extractor 版本、credential_version 标识、destination_policy revision、check 证据与确认人/时间/有效期。秘密值不进入 hash 明文或响应。相关绑定改变、确认过期或撤销后，旧确认不可复用；签名短时效等动态字段由已审核 adapter 在发送时生成，不能靠冻结过期签名冒充可复现。

## 3. RequestSpec v1 的最低契约

| 区域 | 字段与限制 |
| --- | --- |
| 版本/协议 | schema_version、transport、adapter_version；仅 capabilities 宣布已实现的组合 |
| 请求 | method、url_template、query、headers、body_template；不含明文凭据或可执行代码 |
| 环境/鉴权 | environment_revision_id、credential_ref、credential_version；公共变量与 secret 分离 |
| 输入绑定 | case.input 的白名单路径 → 声明式请求路径；类型、必需性和大小检查 |
| 输出提取 | extractor_version、文本/结构化路径、业务成功规则；原响应与提取结果同时保留 |
| 流协议 | none / openai_sse 等已实现协议、内容事件规则、终态/错误规则；不是“有 SSE 就有 token” |
| 资源 | timeout、最大响应/文件体积、重试（默认 0）、副作用声明 |
| 网络安全 | 服务端目的地策略、TLS/企业 CA；用户不可设置 verify=false |

cURL 仅作为导入格式，不作为执行载体。首版只承诺已测试的 POSIX 风格标准 cURL 子集；PowerShell/cmd 的续行/转义须显式转换预览，Invoke-WebRequest 等别名不等于 cURL。拒绝真实管道、重定向、命令替换、可执行插值、不支持 flags 和任意本地文件读取。JSON 字符串里的分号不是 shell 控制符，不能简单字符串黑名单误拒。文件导入为受控 artifact，禁止把 @C:/... 当成服务器可随意读取的路径。
环境变量只做受限占位替换，无 eval/模板表达式执行；替换后再次做 URL/请求校验。浏览器统一调用 Gateway，Gateway/Worker 负责目标请求，不因 CORS 问题让浏览器携带凭据直连目标。

## 4. 流式与 TTFT 门禁

对文本生成，本平台的客户端 TTFT 定义为：请求实际发起到**首个非空、可展示的生成内容增量**被解析的时间，忽略连接建立、HTTP 头、角色、心跳和 usage 事件；这只是首内容观测，chunk 不保证是一个 token，报告写明 measurement_kind=first_content_delta。

| 情况 | 口径 |
| --- | --- |
| 支持且启用文本流式，增量确实可观测 | 可测客户端 TTFT；记录每次测量位置和协议 |
| 普通非流式/CV 返回，只有最终完整结果 | TTFT NOT_APPLICABLE；测端到端 latency |
| 应有流但被代理缓冲、缺有效内容或解析失败 | TTFT UNAVAILABLE，不能填 0 或把最终响应耗时冒充 TTFT |
| 只有进度、心跳、Agent 工具状态 | 不是文本生成 TTFT；另定义进度/状态延迟 |
| Agent 的最终答案以增量流返回 | 可另报端到端 first_answer_delta_ms；不与底层模型纯 TTFT 混比 |

如果整条 SSE 被缓冲后一次送达，仍可保留实际观测到的 client_first_content_ms（含缓冲）和 buffer_suspected/stream_valid 标记，但不能恢复服务端生成首 token 的时刻；本方案默认不把未验证的增量时序作为合格流式 TTFT。只有方案事前明确接受该客户端交付口径才可单独统计，不能事后换口径绕阈值。服务端自报的首 token 指标另存 reported/server 指标，不冒充客户端测量。

使用官方首响应指标作参考，不声称与其他工具定义天然一致。检查成功后，正式运行仍需逐请求验证流，不以旧检查记录补造缺失 TTFT。

## 5. 平台运行与脚本导出的共享边界

平台和导出包共享已发布的 devpilot 执行核心（请求构造、提取/流解析、采样、统计、阈值），通过锁定 wheel 或经审查的受控分发交付；不得 import 开发者仓库的绝对路径，也不复制出两套长期独立维护的实现。Gateway 的认证/DB/调度不打进纯核心。

导出工程建议结构（目标，不是当前仓库已有文件）：

~~~text
evaluation-export/
  README.zh.md / README.en.md
  manifest.json                 # 格式、版本、输入/hash、依赖/权限/测量口径
  run_effect.py / run_perf.py    # 薄 CLI，调用同版本核心
  request.json / plan.json       # 声明式配置、批准的负载上限
  requirements.lock / wheels/    # 精确依赖；可选离线 wheelhouse
  .env.example                  # 只有变量名，无 token
  inputs/                       # 仅获准被测输入
  judge/                        # 可选受限 expected/rubric；不发送给目标
  tests/                        # 假服务与无需访问目标的自检
  results/                      # 本地生成，默认不包含历史运行证据
~~~

初版只支持 Python 3.12+ 与已验证 OS/transport。README 必须说明安装依赖、联网/企业 CA、凭据、输入准备、dry-run、自检、显式实发和结果位置；不能宣称零依赖，也不能把仅远程调平台 Gateway 的 SDK 包叫“独立脚本”。目标网络或外部 judge 本身可以是必需远程服务。

导出权限分级：配置/空输入骨架、获准 input、带参考答案/裁判资料。验收集和金标导出需要额外授权/审计，不因能在复核页面看一条答案就可整库下载。若只获准骨架，平台明确显示“需自行补数据，尚不能完成评测”。敏感来源、历史响应、凭据、机器绝对路径和隐藏金标不能自动打包。

效果模式：
- 本地确定性规则：满足所需授权与输入后可独立判定。
- 外部语义裁判：显式配置独立 judge 凭据/模型/版本和数据出境许可。
- 无可用裁判：可选择 execute_only，保存结果等待导回/人工复核，verdict=NOT_EVALUATED；**不能声称已完成效果验收**。

## 6. 可运行性、等价性与外部结果

导出按钮只有在该 exporter/adapter 组合通过干净环境验证后才能由 capabilities 开启。生成完成前检查依赖齐备、引用可解、脱敏、manifest hash、数据授权和入口自检；少一个文件或依赖就失败，不返回空壳 ZIP。
测试使用同一假服务/固定观测，比较渲染请求、流解析、错误分类、N_total、分档聚合、阈值、缺失值和结果 schema。计时使用可注入时钟/明确容差；真实远端环境不同，不承诺两次运行数值完全相等。

保留并发/费用/时长限制、TLS、显式实发确认和授权说明；但离线工程可被修改，**平台无法持续强制其外部网络、权限或负载行为**。导出前需审查可接受的出域范围；不支持离线执行的受限目标应拒绝导出可实发包。
manifest 记录文件 SHA-256、核心/adapter/规则/计划/数据版本及 hash、export_id、生成器版本、允许范围和结果格式。hash 仅证明内容一致性，不证明结果真实或可信；签名若未实现不可写“已认证”。用户修改配置/代码标 custom/unverified，新导出形成新版本。
外部结果上传后先隔离、体积/schema/hash/provenance 校验、来源/环境核查，再显式关联为 external/unverified 记录；不能覆盖平台原运行，也不能只凭用户上传一个 PASS 自动授予正式验收。需批准采信或平台重跑，且仍满足全部证据门禁。

## 7. 分期与验收

- I1a：HTTP JSON / OpenAI SSE 调试、请求绑定、单次证据与确认、平台效果/性能直接跑；不等待脚本导出才可用。
- I1b：已验证 adapter 的 Python 工程导出，先固定规则，语义裁判缺省 execute_only；以干净环境自检 + 假服务等价 + 一次受控真实运行验收。I1 可在平台闭环验收后单独发布 I1b，未完成时隐藏导出按钮。
- I2：队列复核与裁判包权限增强、导出结果受控导入、更多数据/裁判方式。
- I3：CV multipart/文件与对应导出适配；未支持的协议明确阻断。

API、持久化、测试分别同步到[API](DevPilot_API接口设计文档.md)、[数据库](DevPilot_数据库详细设计.md)、[测试方案](DevPilot_测试方案.md)。
