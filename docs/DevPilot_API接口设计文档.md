# DevPilot API接口设计文档 v2.0

基于 Next.js + FastAPI + LangGraph + Milvus 的 SaaS 多智能体研发协同平台接口设计文档。

## 1. 接口设计原则

系统 API 遵循 RESTful 设计原则，同时针对 Agent 实时执行场景提供流式通信能力。

设计目标：

- 前后端解耦
- 支持 Agent 任务异步执行
- 支持实时输出 Agent 过程
- 支持知识库检索
- 支持 Agent 评测
- 支持关键操作人工审批

命名约定：

- API JSON 字段统一采用 camelCase（与前端 JS 生态一致）
- Python 内部 State 与代码采用 snake_case

## 2. 系统接口架构

```text
Next.js Frontend
    ↓
FastAPI Gateway（多租户隔离）
    ↓
Agent Service (LangGraph，双模式引擎)
    ↓
LLM / RAG / Tools / Evaluation / Sandbox
```

## 3. 用户管理接口

POST /api/user/register — 用户注册

POST /api/user/login — 用户登录（返回 JWT）

GET /api/user/profile — 获取用户信息

## 4. Agent任务管理接口

### 4.1 创建任务

POST /api/task/create

Request:

```json
{
"title": "开发订单系统",
"goal": "实现用户、商品、订单模块",
"taskType": "fullstack_gen"
}
```

taskType 取值（决定执行模式）：

| taskType | execMode | 说明 |
| --- | --- | --- |
| fullstack_gen | pipeline | Web 全栈从零生成 |
| script_gen | agentic_loop | 脚本/工具生成 |
| code_review | agentic_loop | 代码审查/重构 |
| bug_fix | agentic_loop | Bug 修复 |

Response:

```json
{
"taskId": "task_001",
"status": "CREATED",
"execMode": "pipeline"
}
```

### 4.2 查询任务

GET /api/task/{taskId} — 查询任务状态

GET /api/task/list — 查询历史任务

### 4.3 任务状态机

```text
CREATED → RUNNING → SUCCESS / FAILED / CANCELLED
                ↘ PAUSED（审批中）→ RUNNING
```

## 5. Agent执行接口

POST /api/agent/run

启动 Agent 执行流程。

Request:

```json
{
"taskId": "task_001"
}
```

执行流程（依据 execMode 路由）：

```text
Pipeline 模式：
Manager → Planner → Research → Architect → Coding
        → Execution → Testing → Evaluation → Report

Agentic Loop 模式：
Agent Node ⇄ Tool Node（ReAct 循环）
```

## 6. Agent实时通信接口（SSE）

GET /api/agent/stream/{taskId}

采用 SSE 实现实时输出。

返回：

```json
event:agent
data:{
"agent":"Planner",
"message":"正在拆分任务"
}

event:tool
data:{
"tool":"docker",
"status":"running"
}

event:approval
data:{
"approvalId":"apv_001",
"actionType":"commit",
"payload":"提交代码到 main 分支"
}
```

## 7. Human-in-the-loop审批接口

### 7.1 查询待审批项

GET /api/task/{taskId}/approvals

返回任务当前待审批的操作列表。

### 7.2 审批决策

POST /api/approval/{approvalId}/decision

Request:

```json
{
"decision": "approve"
}
```

decision 取值：`approve`（同意）/ `reject`（拒绝）。

审批超时（默认 30 分钟）自动按 reject 处理并终止任务。

## 8. Agent Trace查询接口

GET /api/trace/{taskId}

返回 Agent 执行链路。

Response:

```json
{
"trace":[
{
"agent":"Planner",
"duration":1200,
"status":"success"
}
]
}
```

## 9. RAG知识库接口

POST /api/knowledge/upload — 上传知识文档

POST /api/knowledge/search — 知识检索

Request:

```json
{
"query":"React最佳实践",
"topK":5
}
```

Response:

```json
{
"documents":[
{
"content":"...",
"score":0.92
}
]
}
```

## 10. 文件与代码Workspace接口

POST /api/workspace/create — 创建 Agent 工作空间

GET /api/workspace/{id}/files — 查看生成文件

GET /api/workspace/file/content — 查看文件内容

GET /api/workspace/{id}/download — 打包下载项目

## 11. Tool调用接口

POST /api/tool/execute

Agent 调用外部工具（沙箱内执行）。

支持：

- Git
- Docker
- Python 执行环境
- Shell
- Browser Search

## 12. Evaluation接口

POST /api/evaluation/run — 启动 Agent 评测

GET /api/evaluation/report/{taskId} — 获取评测报告

返回（7 字段评测标准）：

```json
{
"taskScore": 90,
"codeScore": 85,
"testScore": 80,
"hallucinationRate": 0.03,
"confidence": 88,
"overall": 86,
"report": "评测报告摘要"
}
```

## 13. WebSocket扩展设计

对于复杂交互场景，可使用 WebSocket。

用途：

- 多 Agent 实时状态
- 代码生成进度
- 用户人工审批
- Agent 暂停恢复

## 14. 错误码设计

| 错误码 | 含义 |
| --- | --- |
| 200 | SUCCESS |
| 400 | PARAM_ERROR |
| 401 | UNAUTHORIZED |
| 404 | NOT_FOUND |
| 429 | RATE_LIMIT_EXCEEDED |
| 500 | SERVER_ERROR |
| 600 | AGENT_EXECUTION_ERROR |
| 601 | LLM_ERROR |
| 602 | TOOL_ERROR |
| 603 | SANDBOX_ERROR |
| 604 | APPROVAL_TIMEOUT |

## 15. API安全设计

采用：

- JWT 身份认证
- API Rate Limit
- 多租户隔离（user_id 强制过滤）
- 敏感操作人工确认
- 沙箱执行安全隔离

## 16. 后续扩展

支持：

- OpenAPI 自动生成
- Agent 版本管理
- 多模型路由接口
- 共享项目/团队接口
- 计费与用量接口
