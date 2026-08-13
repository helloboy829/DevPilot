# DevPilot 实时通信协议设计 v1.0

## 0. 文档说明

本文档定义 DevPilot 前后端实时通信协议，包括 SSE 事件类型与字段级结构、Human-in-the-loop 审批数据流。本文档是《API接口设计文档》第 6、7 章的协议级细化。

## 1. 通信方式选择

| 场景 | 方式 | 说明 |
| --- | --- | --- |
| 服务端 → 客户端单向推送 | **SSE**（首选） | 任务执行过程、审批请求、状态变更 |
| 双向交互（暂停/恢复/审批） | REST + SSE | 客户端操作走 REST，服务端推送走 SSE |
| 复杂双向（可选扩展） | WebSocket | 多 Agent 面板实时状态 |

首版统一用 **SSE + REST**，WebSocket 作为扩展。

## 2. SSE 协议规范

### 2.1 连接建立

```
GET /api/agent/stream/{taskId}
Authorization: Bearer {jwt}
Accept: text/event-stream
```

- 连接建立后，服务端持续推送该任务的事件流
- 客户端可用 `Last-Event-ID` 实现断线重连续传

### 2.2 事件格式

```text
event: {event_type}
id: {event_id}
data: {json_payload}

```

- `event`：事件类型（见 §2.3）
- `id`：单调递增事件 ID，用于重连续传
- `data`：JSON 载荷（camelCase）

### 2.3 事件类型清单

#### task_status — 任务状态变更

```json
{
  "taskId": "task_001",
  "status": "RUNNING",
  "message": "任务开始执行",
  "timestamp": "2026-08-13T10:00:00Z"
}
```

status 取值：CREATED / RUNNING / PAUSED / SUCCESS / FAILED / CANCELLED

#### agent — Agent 节点状态

```json
{
  "taskId": "task_001",
  "agent": "Planner",
  "execMode": "pipeline",
  "status": "start | running | end",
  "message": "正在拆分任务",
  "timestamp": "2026-08-13T10:00:01Z"
}
```

#### tool — 工具调用状态

```json
{
  "taskId": "task_001",
  "tool": "exec_command",
  "status": "start | success | error",
  "input": {"command": "pytest"},
  "output": "3 passed",
  "durationMs": 120,
  "timestamp": "2026-08-13T10:00:05Z"
}
```

#### approval — 审批请求（核心）

```json
{
  "taskId": "task_001",
  "approvalId": "apv_001",
  "actionType": "git_commit",
  "payload": {
    "command": "git commit -m 'feat: order module'",
    "files": ["src/order.py"]
  },
  "createdAt": "2026-08-13T10:00:10Z",
  "expiresAt": "2026-08-13T10:30:10Z"
}
```

#### trace — 链路信息

```json
{
  "taskId": "task_001",
  "executionId": "exec_001",
  "spanType": "llm | tool | retriever",
  "name": "Coding LLM Call",
  "status": "success",
  "durationMs": 1500,
  "tokenUsed": 8000
}
```

#### error — 错误

```json
{
  "taskId": "task_001",
  "code": "602",
  "message": "工具调用失败",
  "agent": "Coding",
  "timestamp": "2026-08-13T10:00:20Z"
}
```

#### complete — 任务完成（含评测摘要）

```json
{
  "taskId": "task_001",
  "status": "SUCCESS",
  "evaluation": {
    "taskScore": 90,
    "codeScore": 85,
    "testScore": 80,
    "hallucinationRate": 0.03,
    "confidence": 88,
    "overall": 86,
    "report": "评测报告摘要"
  },
  "timestamp": "2026-08-13T10:05:00Z"
}
```

### 2.4 心跳与重连

- 心跳：服务端每 30s 发送 `event: ping`（data 为空）
- 重连：客户端断开后携带 `Last-Event-ID` 重连，服务端从该 ID 续推未消费事件
- 事件保留：服务端缓存该任务最近事件（Redis，TTL 1 小时）

## 3. Human-in-the-loop 审批数据流（字段级）

### 3.1 审批触发

Agent 调用 `requires_approval=True` 的工具时：

1. 后端创建 approval 记录（status=pending）
2. 任务状态置为 PAUSED
3. LangGraph 在 approval_node 处 `interrupt()` 挂起

### 3.2 审批事件推送

服务端通过 SSE 推送 `approval` 事件（见 §2.3），前端弹出审批卡片。

### 3.3 审批决策

客户端调用 REST 接口：

```text
POST /api/approval/{approvalId}/decision
```

Request：

```json
{
  "decision": "approve | reject",
  "comment": "可选备注"
}
```

Response：

```json
{
  "approvalId": "apv_001",
  "status": "approved",
  "taskId": "task_001"
}
```

### 3.4 决策后续

| 决策 | 后端行为 | 后续事件 |
| --- | --- | --- |
| approve | `interrupt()` 返回 "approve"，Agent 继续执行 | `task_status`（RUNNING） |
| reject | `interrupt()` 返回 "reject"，跳过该操作 | `task_status`（RUNNING）或 FAILED |
| timeout（30min） | 默认按 reject 处理，终止任务 | `task_status`（FAILED）+ `error`（604） |

### 3.5 审批状态机

```text
pending → approved →（Agent 继续）
        → rejected →（跳过操作 / 终止）
        → timeout →（默认 rejected）
```

## 4. WebSocket 扩展协议（可选）

复杂交互场景（多 Agent 面板、代码生成进度条）可启用 WebSocket：

```text
ws://host/api/ws/{taskId}

客户端 → 服务端：
  {"type": "pause", "taskId": "..."}
  {"type": "resume", "taskId": "..."}
  {"type": "approval_decision", "approvalId": "...", "decision": "approve"}

服务端 → 客户端：
  （复用 SSE 事件类型，作为 message.type 推送）
```

首版不实现，接口预留。

## 5. 事件与 API 的衔接

| 客户端动作 | API | 触发的事件 |
| --- | --- | --- |
| 创建任务 | POST /api/task/create | task_status(CREATED) |
| 启动任务 | POST /api/agent/run | task_status(RUNNING) + agent(start) |
| 订阅实时流 | GET /api/agent/stream/{id} | 持续推送上述所有事件 |
| 审批决策 | POST /api/approval/{id}/decision | task_status(RUNNING/FAILED) |
| 查询 Trace | GET /api/trace/{taskId} | （同步返回，非事件） |
| 查询评测 | GET /api/evaluation/report/{id} | （同步返回，非事件） |

## 6. 前端消费规范

- SSE 用 `EventSource` 或 fetch 流式读取（需自定义 header 时用 fetch）
- 事件按类型分发到对应 UI 组件（Agent 面板、工具日志、审批弹窗、Trace 图）
- 审批事件必须置顶 + 强提醒，防止阻塞被忽略
- 断线自动重连（携带 Last-Event-ID），重连期间展示「重连中」
- 事件乱序容忍：以 `id` 排序去重
