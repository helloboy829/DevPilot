# DevPilot LangGraph工程设计文档 v1.0

## 1. 文档概述

本文档用于设计DevPilot多智能体系统的核心Agent Runtime。

基于LangGraph实现Agent状态管理、任务编排、工具调用、异常恢复以及Human-in-the-loop机制。

目标：

- 构建可扩展Multi-Agent架构
- 支持复杂研发任务流程
- 支持Agent执行追踪
- 支持Agent结果评估

## 2. LangGraph总体架构

系统采用State Graph模式：

```text
User Request

↓

Manager Agent

↓

Planner Agent

↓

Research Agent

↓

Architect Agent

↓

Coding Agent

↓

Execution Agent

↓

Testing Agent

↓

Evaluation Agent

↓

Report Agent
```

## 3. Agent State设计

LangGraph通过共享State维护任务上下文。

AgentState:

字段：

task_id

用户任务ID

goal

用户目标

messages

消息历史

current_agent

当前执行Agent

plan

任务规划结果

artifacts

生成文件及结果

tool_results

工具调用结果

evaluation

评测结果

status

任务状态

## 4. Node节点设计

### 4.1 Manager Node

职责：

- 接收用户请求
- 创建任务
- 初始化State
- 调度后续流程

### 4.2 Planner Node

职责：

- 分析任务
- 拆解步骤
- 生成执行计划

输出：

```json
{
tasks:[
"需求分析",
"代码生成",
"测试"
]
}
```

### 4.3 Research Node

职责：

- 判断是否需要知识检索
- 调用RAG
- 提供上下文

### 4.4 Architect Node

职责：

- 系统设计
- 技术选型
- 模块划分

### 4.5 Coding Node

职责：

- 创建代码文件
- 修改代码
- 输出代码结果

### 4.6 Execution Node

职责：

- 调用Docker Sandbox
- 执行代码
- 获取运行结果

### 4.7 Testing Node

职责：

- 生成测试
- 执行测试
- 分析失败原因

### 4.8 Evaluation Node

职责：

- 对Agent结果评分
- 判断任务完成质量

## 5. Edge流程设计

正常流程：

```text
START

↓

Manager

↓

Planner

↓

Research

↓

Architect

↓

Coding

↓

Execution

↓

Testing

↓

Evaluation

↓

END
```

条件分支：

如果测试失败：

```text
Testing

↓

Coding

↓

Execution
```

形成Agent自修复循环。

## 6. ReAct执行模式

Agent执行：

```text
Reason

↓

Action

↓

Observation

↓

Repeat
```

例如：

```text
Coding Agent:

分析错误

↓

修改代码

↓

重新运行测试

↓

确认结果
```

## 7. Tool Calling设计

工具统一接口：

Tool:

name

description

input_schema

execute()

支持：

Git Tool

Docker Tool

Python Executor

Browser Search

File Manager

## 8. Prompt工程设计

目录：

prompts/

manager/

planner/

coding/

testing/

evaluation/

每个Agent独立System Prompt。

示例：

Coding Agent：

你是一名高级软件工程师。

要求：

- 生成高质量代码
- 遵循工程规范
- 编写测试
- 输出结构化结果

## 9. Agent Memory设计

短期Memory：

保存：

- 当前任务上下文
- 中间结果

存储：

Redis

长期Memory：

保存：

- 历史任务
- 优秀方案
- Agent经验

存储：

Milvus

## 10. Streaming设计

Agent执行过程中：

通过SSE推送：

```json
{
agent:"Coding",
event:"generate_code",
message:"正在生成User模块"
}
```

前端实时展示。

## 11. 异常处理机制

LLM异常：

- 重试
- 降级模型

Tool异常：

- 捕获错误
- 返回Agent

任务异常：

- 保存Checkpoint
- 支持恢复

## 12. Human-in-the-loop设计

高风险操作：

- 删除文件
- 修改数据库
- 提交代码

暂停流程：

```text
Agent

↓

Approval Node

↓

用户确认

↓

继续执行
```

## 13. Agent版本管理

记录：

Agent名称

Prompt版本

Model版本

Tool版本

用于：

效果分析

问题定位

## 14. 工程目录设计

```text
agent/

├── graph/

│   ├── workflow.py

│   └── state.py

│

├── nodes/

│   ├── planner.py

│   ├── coding.py

│   └── evaluation.py

│

├── tools/

│

├── prompts/

│

└── memory/
```

## 15. 总结

LangGraph作为DevPilot核心Agent编排引擎，实现：

- 多Agent协作
- 状态管理
- 工具调用
- 自修复循环
- 人机协同
- 执行追踪

为后续工程开发提供核心架构基础。
