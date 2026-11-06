# DevPilot LangGraph 工程设计 v3.0

> 2026-11-06；评测领域目标编排，**不是当前已经运行的九 Agent 图**。当前组件测试直接经业务服务调用 toolkit。

## 1. 复用与新增边界

复用 DeerFlow Lead Agent、模型工厂、工具权限、checkpoint 和追踪，不另建通用 ReAct runtime。新增评测业务服务及最小权限工具；LangGraph 用于有界规划和助手工作流，DB 中的版本、审批、Job、Run 才是业务真相。
首版一个领域助手即可。只有独立上下文/权限/并行收益经验证后再引入数据或报告子 Agent，不以固定九个 Agent 为目标。

## 2. 目标业务节点

~~~text
读取项目事实 → 提测完整性检查 → 接入候选方案 → 等待接入确认
          → 数据方案/候选构建 → 等待数据审批 → 方案/负载审批
          → 冻结并提交 Job → 等待 Worker → 解释结果/创建报告草稿
          → 人工复核/整改 → 同基准复测或报告审批 → 候选知识
~~~

这些是领域阶段，不要求全部成为独立 LLM 节点；字段校验、计数、网络调用、聚合、门禁使用程序。等待采用持久引用/checkpoint 或事件唤醒，不能让模型轮询到超预算。

## 3. 最小状态

只保存 project_id、submission_revision、plan_id/revision、dataset_version_id、run_ids、pending_review_ids、phase、budget_refs、last_event_cursor、artifact_refs、summary。
不把整批图像、密钥、完整参考答案、百万条观测或指标中间数组放进 AgentState。checkpoint 不能替代 dataset manifest 或 RunSnapshot。
恢复先查业务 DB 版本；state 引用过期时提示重新计划，不能盲目继续旧审批。

## 4. 工具契约

| 工具（目标名） | 能做 | 禁止 |
| --- | --- | --- |
| inspect_submission | 缺项/能力建议 | 网络试探未知目标 |
| propose_dataset / generate_candidates | 指定授权源、预算内产候选 | 直接标 approved/frozen |
| validate_dataset | 确定性检查并产质量卡 | 自动把所有标签变可信 |
| propose_plan / request_review | 草拟规则、负载、预算并请求审批 | approve 自己的计划 |
| submit_approved_run | 引用冻结方案，服务端再校验 | 接收任意 URL/阈值绕审批 |
| get_run_evidence | 已授权摘要和 case 片段 | 返回凭据/全部敏感盲测答案 |
| draft_report / propose_knowledge | 根据事实 ID 产草稿/候选 | 发布 PASS 报告/直接推广知识 |

Agent 工具只是业务 API 的薄适配，服务端权限与幂等不可因内部工具而跳过。工具输出带 schema_version、resource_ref、revision、warnings、blocked_reasons。

## 5. 有界性、错误与恢复

- 每任务最大 LLM 步数/token/时间/生成条数/工具次数，由部署与项目预算交集决定。
- 不支持能力、授权不足、裁判不可用时解释阻断；不靠自由循环反复尝试外网或提并发。
- 工具可重试错误采用有限退避；副作用工具带幂等键；目标 Agent 有副作用时不得自动重放。
- 超时/取消捕获并落业务状态，不仅发聊天消息；取消 LangGraph 不能冒充已停止外部压测。
- 危险材料/输出为不可信文本，引用内容不成为工具指令；工具权限保持最小集合。
- 长时间 Job 由 Worker 心跳和租约管理，不把 LangGraph checkpoint 当作队列。

## 6. 人机审批

审批对象绑定 revision/hash、actor、scope 和有效期；数据、负载、报告和知识推广独立审批。内容改变必须重审。
调度器的 non_interactive 只表示不等待聊天澄清，不表示绕过审批；没有预授权时任务 BLOCKED。不得信任客户端伪造内部非交互标识。

## 7. 工程与验证

领域服务位于 backend/app，纯 schema/逻辑位于 devpilot/src/devpilot；工具桥接和模型调用适配不得反向污染 harness。插件加载使用 operator-controlled plugins.use。
测试：状态过期恢复、重复工具提交、超预算、攻击性来源、未审标签、审批失效、Worker 中断与报告幻觉。追踪记录 prompt/model/tool 版本及业务 ID，但日志脱敏，真实答案仅限授权观察者。

## 8. 调试、导出、人工复核的 Agent 边界

增加工具入口的目标能力：解析 RequestSpec/读取脱敏检查、提交受控 check、起草数据/方案、申请导出、查询复核进度/整理证据。工具只能调用与 UI 相同的应用服务，执行 ID 与预算由后端确定；非标准 adapter 草稿只能进入审核/测试流程，不能直接运行任意生成代码。

人工 Confirmation、ReviewDecision/Adjudication、计划/负载批准和报告发布由登录 actor 经 REST 提交，Agent 无相应自批权限。Human-in-the-loop 中断只作提示，不以聊天“同意”替代持久化授权；non_interactive 模式缺授权仍阻断。
调试目标 SSE 的首内容、LangGraph token、项目业务 SSE 是三个不同来源；不能用助手首字时间计算目标 TTFT。export/ref 与 task/ref 只传摘要，验收金标/raw 大文件不注入普通 thread memory。
