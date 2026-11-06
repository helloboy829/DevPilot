# DevPilot 技术依据与决策记录

> 核对日期：2026-11-06。外部 main/stable 为动态资料，不代表本 fork 已同步最新版本；正式集成时应锁定 commit/包版本并存 hash。本次通过只读获取官方原文核对，未上传项目数据。

## 1. 一手资料与采用边界

| 资料 | 本次用途 | 不作出的推论 |
| --- | --- | --- |
| [DeerFlow 官方 README](https://github.com/bytedance/deer-flow/blob/main/README.md) | 核对 harness、skills、sub-agents、sandbox 的产品边界 | 不能据此声明本 fork 已完成评测闭环或与远端当前 main 完全一致 |
| [Ray LLMPerf 官方 README](https://github.com/ray-project/llmperf/blob/main/README.md) | 并发负载、逐请求与汇总记录、token 延迟/吞吐参考；注意其 tokenizer/测试文本约定 | 非直接移植脚本；不默认其 workload 代表本用户业务；尚未集成 |
| [NVIDIA GenAI-Perf 官方 README / Metrics](https://github.com/triton-inference-server/perf_analyzer/blob/main/genai-perf/README.md#metrics) | 区分 TTFT、ITL、request latency、每用户和整体 token throughput | 本项目“首非空内容”和成功请求统计是自定义口径；与其数值不可未经对齐直接排名 |
| [scikit-learn 模型评估文档](https://scikit-learn.org/stable/modules/model_evaluation.html) | 分类 accuracy、precision、recall、F1、宏/微平均等专项指标 | 用户业务通过率不等于所有任务只有 accuracy；不能省略关键类 |
| [COCO 官方评测说明](https://cocodataset.org/#detection-eval) | 检测需专用数据格式/标注/评估协议 | 自定义检测任务必须固定自己的 IoU、类别和匹配，不泛称已兼容 COCO |
| [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685) | 裁判的位置、篇幅、自偏好等风险与人工校准必要性 | 论文中的一致性结果不能当成本项目准确率保证 |
| [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html) | allowlist、DNS/连接地址、重定向、应用与网络双层控制 | 业务需要内网组件，因此采用管理员授权内网策略，不是一刀切拒绝私网 |

读取备注：NVIDIA 单独 docs/metrics.md 路径返回 404，采用官方 README 的 Metrics 章节；COCO 动态页面只用于核对官方评测入口，具体检测算法实现仍需在开发时锁定并校准。以上是方法与风险依据，不替代本地代码证据。

## 2. ADR（本轮设计基线；实现按阶段验收）

| ID | 决策 | 理由与后果 |
| --- | --- | --- |
| ADR-001 | 产品围绕评测，不再围绕编码/聊天 | 工作台主导航调整；旧评分保留 legacy |
| ADR-002 | Agent 辅助 + 确定性执行/判定 | 提高可复现性；审批/分母/限额不可由 Prompt 改 |
| ADR-003 | 数据质量/盲测/人工校准先于海量生成 | 产生审核成本，但避免虚假高分和污染 |
| ADR-004 | 复用 DeerFlow，领域模块化单体 | 降低重造 runtime 与过早微服务成本 |
| ADR-005 | 任务 DB 持久化，租约与证据分层 | 无法用 create_task 充当生产任务系统 |
| ADR-006 | 先隐藏/禁用，再按依赖裁剪 | 保留升级/回退和鉴权完整性 |
| ADR-007 | 缺证据不 PASS，执行/验收状态分离 | 新旧结果不能无条件等价；旧结果需标记 |
| ADR-008 | 结构化/全文起步，向量库可选 | 规模/召回经验证后再增加基础设施 |
| ADR-009 | 持续学习是审核知识推广，不自动训练 | 可回归/回滚；原始材料和验收答案分权限 |
| ADR-010 | 类 Postman 调试与 RequestSpec/确认绑定 | 降低接入门槛；调试证据不代替压测授权，不追求完整 Postman 兼容 |
| ADR-011 | 平台执行为主，独立脚本工程可选，共享版本核心 | 不依赖 LLM 临场编写；需独立环境、自检、权限与等价验收 |
| ADR-012 | 人工复核中心 + 数据/结果内嵌，同一任务服务 | 避免两套审查状态；支持单人到双盲/仲裁渐进扩展 |
| ADR-013 | 观测/自动裁判/人工决定/最终 assessment 分层 | 可追溯重算，不修改金标/原响应/性能测量，报告锁定修订 |
| ADR-014 | 项目文档仅维护中英文 | 清理日法俄 README 与引用，不删除运行时 i18n/许可，不限制材料语言 |

## 3. 待试点决定的问题

- 代表任务的业务分布、风险切片、最低样本与容差。
- 报告模板字段和最终签批职责；自审批是否允许、哪些需双人。
- 私网出站策略、企业 CA、保留期限与是否允许外部模型处理资料。
- 裁判模型选择、人工误放行门槛与校准集；费用和负载窗口。
- 团队授权、数据共享、隔离级别；何时引入 PostgreSQL/队列/向量索引。
- 首批可导出 adapter/OS、离线依赖分发、金标导出授权与外部结果采信标准。
- 复核角色是否允许自审、关键切片双审与抽检比例、任务时限；策略须审批后冻结。

不因尚待用户材料而停止文档工作，但正式评测在对应信息明确前必须阻断。

## 4. 本轮新增决策的证据边界

接口调试台“类似 Postman”是交互类比，独立工程导出与复核中心是本项目设计选择；不宣称已实现其兼容协议或已集成某官方 SDK。本轮没有取得新的可引用 Postman 文档内容，不能把类比写成经过验证的产品能力。TTFT 仍以本项目首内容观测定义为准，并明确代理缓冲、非流式与 Agent 状态流边界。
