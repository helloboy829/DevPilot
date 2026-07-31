# DevPilot 系统架构设计文档 v1.0

## 1. 总体架构

系统采用：

Frontend + Backend + Agent Runtime + AI Infrastructure 架构。

整体：

```
                 User
                  |
              Next.js
                  |
              FastAPI
                  |
          LangGraph Runtime
                  |
 ------------------------------------------------
 |          |           |          |             |
Planner   Research    Coding   Testing   Evaluation
                  |
 ------------------------------------------------
          LLM / RAG / Tools / Memory
                  |
 ------------------------------------------------
 PostgreSQL    Redis    Milvus    Docker Sandbox
```

# 2. 技术选型

## 前端

技术：

- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui

负责：

- Chat界面
- Agent流程展示
- Trace查看
- 评测Dashboard

## 后端

技术：

- FastAPI
- Python

负责：

- 用户请求管理
- Agent任务管理
- API服务

## Agent框架

技术：

LangGraph

原因：

支持：

- 状态管理
- 节点编排
- 条件分支
- 循环执行
- Human-in-the-loop

# 3. Agent架构设计

## Manager Agent

系统入口。

职责：

- 接收用户目标
- 调度其他Agent

## Planner Agent

输入：

用户需求

输出：

任务图。

例如：

```
需求分析
↓
数据库设计
↓
代码生成
↓
测试
↓
评估
```

## Coding Agent

能力：

- 文件生成
- 代码修改
- 项目初始化

## Execution Agent

能力：

调用：

- Docker
- Python
- Shell

执行：

- 编译
- 测试
- 检查

## Evaluation Agent

负责：

LLM-as-Judge。

输出：

```
{
task_score:90,
code_quality:85,
confidence:88
}
```

# 4. RAG架构

流程：

```
Document
↓
Parser
↓
Chunk
↓
Embedding
↓
Milvus
↓
Retriever
↓
LLM
```

技术：

Embedding:

BGE系列

Vector Database:

Milvus

# 5. Memory设计

## Short Memory

Redis保存：

- 当前任务状态
- Agent上下文

## Long Memory

Milvus保存：

- 用户偏好
- 历史任务经验

# 6. Tool设计

Agent工具：

## Git Tool

功能：

- Clone代码
- 查看提交
- 分析代码

## Code Executor

功能：

- 执行代码
- 执行测试

## Browser Tool

功能：

- 查询技术资料

# 7. Agent Trace设计

记录：

```
User Input
↓
Planner
↓
Retriever
↓
LLM
↓
Tool Call
↓
Result
```

字段：

- Agent名称
- 输入
- 输出
- Token消耗
- 执行时间

# 8. 部署架构

Docker Compose：

```
services:
frontend:
 Next.js
backend:
 FastAPI
agent:
 LangGraph
database:
 PostgreSQL
vector:
 Milvus
cache:
 Redis
```

# 9. 后续扩展方向

- Multi Model Router

根据任务选择：

- GPT
- Claude
- Qwen
- Human Approval

高风险操作人工确认。

- Agent Benchmark

自动测试Agent能力。

- 企业权限体系

支持团队使用。
