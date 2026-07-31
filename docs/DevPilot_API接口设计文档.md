# DevPilot API接口设计文档 v1.0

基于 Next.js + FastAPI + LangGraph + Milvus 的企业级多智能体研发协同平台接口设计文档。

# 1. 接口设计原则

系统API遵循RESTful设计原则，同时针对Agent实时执行场景提供流式通信能力。

设计目标：

- 前后端解耦
- 支持Agent任务异步执行
- 支持实时输出Agent过程
- 支持知识库检索
- 支持Agent评测

# 2. 系统接口架构

```text
Next.js Frontend

↓

FastAPI Gateway

↓

Agent Service (LangGraph)

↓

LLM / RAG / Tools / Evaluation
```

# 3. 用户管理接口

POST /api/user/register

用户注册

POST /api/user/login

用户登录

GET /api/user/profile

获取用户信息

# 4. Agent任务管理接口

POST /api/task/create

创建Agent任务。

Request:

```json
{
"title":"开发订单系统",
"goal":"实现用户、商品、订单模块"
}
```

Response:

```json
{
"taskId":"task_001",
"status":"CREATED"
}
```

GET /api/task/{taskId}

查询任务状态。

GET /api/task/list

查询历史任务。

# 5. Agent执行接口

POST /api/agent/run

启动Agent执行流程。

Request:

```json
{
"taskId":"task_001"
}
```

执行流程：

```text
Manager Agent
→ Planner Agent
→ Coding Agent
→ Testing Agent
→ Evaluation Agent
```

# 6. Agent实时通信接口

采用SSE(Server Sent Events)实现实时输出。

GET /api/agent/stream/{taskId}

返回：

```json
event:agent
data:{
agent:"Planner",
message:"正在拆分任务"
}
event:tool
data:{
tool:"docker",
status:"running"
}
```

# 7. Agent Trace查询接口

GET /api/trace/{taskId}

返回Agent执行链路。

Response:

```json
{
trace:[
{
agent:"Planner",
duration:1200,
status:"success"
}
]
}
```

# 8. RAG知识库接口

POST /api/knowledge/upload

上传知识文档。

POST /api/knowledge/search

知识检索。

Request:

```json
{
query:"React最佳实践",
topK:5
}
```

Response:

```json
{
documents:[
{
content:"...",
score:0.92
}
]
}
```

# 9. 文件与代码Workspace接口

POST /api/workspace/create

创建Agent工作空间。

GET /api/workspace/{id}/files

查看生成文件。

GET /api/workspace/file/content

查看文件内容。

# 10. Tool调用接口

POST /api/tool/execute

Agent调用外部工具。

支持：

- Git
- Docker
- Python执行环境
- Browser Search

# 11. Evaluation接口

POST /api/evaluation/run

启动Agent评测。

GET /api/evaluation/report/{taskId}

获取评测报告。

返回：

```json
{
taskScore:90,
codeScore:85,
hallucinationRate:0.03,
overall:88
}
```

# 12. WebSocket扩展设计

对于复杂交互场景，可使用WebSocket。

用途：

- 多Agent实时状态
- 代码生成进度
- 用户人工审批
- Agent暂停恢复

# 13. 错误码设计

200 SUCCESS

400 PARAM_ERROR

401 UNAUTHORIZED

404 NOT_FOUND

500 SERVER_ERROR

600 AGENT_EXECUTION_ERROR

601 LLM_ERROR

602 TOOL_ERROR

# 14. API安全设计

采用：

- JWT身份认证
- API Rate Limit
- 用户权限控制
- 敏感操作人工确认

# 15. 后续扩展

支持：

- OpenAPI自动生成
- Agent版本管理
- 多模型路由接口
- 多租户接口隔离
- 企业级权限体系
