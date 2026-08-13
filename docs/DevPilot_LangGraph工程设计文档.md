# DevPilot LangGraph工程设计文档 v2.0

## 1. 文档概述

本文档设计 DevPilot 多智能体系统的核心 Agent Runtime，基于 LangGraph 实现 Agent 状态管理、任务编排、工具调用、异常恢复以及 Human-in-the-loop 机制。

v2.0 变化：新增「双模式执行引擎」，将 Agentic Loop 自由循环模式细化到可编码程度。

目标：

- 构建可扩展 Multi-Agent 架构
- 支持复杂研发任务流程（流水线）
- 支持探索式任务（自由循环）
- 支持 Agent 执行追踪与结果评估

## 2. 双模式执行引擎总览

DevPilot 在 LangGraph 上实现两种执行模式，由 Manager 节点依据任务类型路由：

| 模式 | 适合任务 | 图结构 |
| --- | --- | --- |
| Pipeline 流水线 | 全栈从零生成 | 固定 9 节点 StateGraph |
| Agentic Loop 自由循环 | 修复/审查/脚本 | Agent ⇄ Tool ReAct 循环 |

两种模式**共享同一套基础 State 与 Tool 定义**，差异仅在图结构与循环控制。

## 3. 通用 AgentState 设计

LangGraph 通过共享 State 维护任务上下文。两种模式共用以下基础字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| task_id | str | 用户任务 ID |
| goal | str | 用户目标 |
| messages | list[Message] | 消息历史（human/ai/tool） |
| current_agent | str | 当前执行 Agent |
| plan | dict | 任务规划结果 |
| artifacts | dict | 生成文件及结果 |
| tool_results | list | 工具调用结果 |
| evaluation | dict | 评测结果 |
| status | str | 任务状态 |
| token_used | int | 累计 token 消耗 |

### 3.1 Pipeline 专用字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| stage | str | 当前流水线阶段 |

### 3.2 Agentic Loop 专用字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| iteration_count | int | 当前迭代次数 |
| max_iterations | int | 最大迭代次数（默认 20） |
| completion_flag | bool | LLM 判定任务完成 |
| pending_approval | dict | 待审批操作 |
| tools_available | list | 可用工具列表 |

## 4. Pipeline 流水线模式设计

### 4.1 图结构

```text
START → Manager → Planner → Research → Architect → Coding
      → Execution → Testing → Evaluation → Report → END
```

### 4.2 节点职责（简表）

| 节点 | 职责 |
| --- | --- |
| Manager | 接收请求、初始化 State、路由到执行模式 |
| Planner | 分析任务、拆解步骤、生成执行计划 |
| Research | 判断是否检索、调用 RAG、提供上下文 |
| Architect | 系统设计、技术选型、模块划分 |
| Coding | 创建/修改代码文件 |
| Execution | 沙箱内编译/运行 |
| Testing | 生成/执行测试、分析失败原因 |
| Evaluation | LLM-as-Judge 评分 |
| Report | 汇总结果、生成交付报告 |

### 4.3 条件分支（自修复循环）

```text
Testing ──失败──→ Coding → Execution → Testing
```

- 最大迭代次数默认 3（可配置）
- 超限则终止，保存 Checkpoint，产出失败报告

## 5. Agentic Loop 自由循环模式详细设计（核心）

### 5.1 设计目标

在沙箱中实现「think → act → observe → repeat」的自治循环，类 Claude Code 体验，适用于 Bug 修复、代码审查、脚本生成等探索式任务。

### 5.2 图结构

```text
START → agent_node ──有 tool_calls──→ tool_node ──→ agent_node（循环）
              │
              ├── 无 tool_calls 且 completion → END
              ├── 触发审批 → approval_node → 用户决策 → agent_node / END
              └── 迭代/ token 超限 → END（部分结果 + 警告）
```

### 5.3 节点设计

**agent_node（决策节点）**

- 职责：调用 LLM（绑定工具），决定调用哪个工具或判定任务完成
- 输入：当前 messages（含工具结果）
- 输出：AIMessage（可能含 tool_calls）
- 逻辑：每进入一次 `iteration_count += 1`

**tool_node（执行节点）**

- 职责：执行 agent 请求的 tool_calls，返回 ToolMessage
- 输入：上一条 AIMessage 的 tool_calls
- 输出：ToolMessage 列表（执行结果/错误）

**approval_node（审批节点）**

- 职责：拦截高风险工具调用，暂停并等待用户决策
- 实现：LangGraph `interrupt()` 实现中断，用户 approve/reject 后继续

### 5.4 终止条件设计

| 条件 | 判定 | 结果 |
| --- | --- | --- |
| 正常完成 | LLM 输出最终回答（无 tool_calls） | SUCCESS |
| 迭代超限 | iteration_count ≥ max_iterations | 终止，产出部分结果 + 警告 |
| token 超限 | token_used ≥ 任务 token 上限 | 强制终止 |
| 审批拒绝 | 用户 reject 关键操作 | 跳过该操作或终止（视操作而定） |
| 连续工具失败 | 工具连续失败 N 次（默认 3） | 终止，报告失败原因 |

### 5.5 工具调用协议

工具统一接口：

```
Tool:
  name: str            # 工具名
  description: str      # 描述（供 LLM 决策）
  args_schema: JSON     # 参数 schema（function calling）
  execute(**args): dict # 执行实现
```

LLM 通过 function calling 返回 tool_calls，tool_node 按 schema 校验参数后执行，结果以 ToolMessage 回传。

### 5.6 上下文管理（长上下文挑战）

自由循环最大的难点是**上下文膨胀**。多轮工具调用会把 messages 撑爆。策略：

1. **滑动窗口**：保留最近 N 轮（默认 20 条消息），更早的丢弃
2. **摘要压缩**：超出窗口的旧消息用 LLM 压缩成摘要，注入系统提示
3. **文件按需读取**：不把整个仓库塞进上下文，Agent 通过 `read_file` 工具按需读
4. **工具结果截断**：大输出（如大文件、长日志）截断 + 摘要，保留关键部分
5. **代码搜索工具**：`grep`/`search_code` 精确定位，避免全量读取

### 5.7 与沙箱交互

- Agent 通过 Shell/CodeExecutor 工具在沙箱内执行
- 沙箱文件系统跨迭代**持久保留**（同一任务同一沙箱）
- 每次工具调用都有超时（默认 30s）与资源限额

### 5.8 与审批集成

高风险工具触发审批（结合 §12）：

| 工具 | 审批策略 |
| --- | --- |
| git_commit / git_push | 每次审批 |
| exec_command（危险命令） | 白名单外审批 |
| file_delete | 每次审批 |
| db_write | 每次审批 |
| 普通 read/write/grep/run_test | 不审批 |

实现：工具执行前检查 `requires_approval` 标记，若为真则进入 approval_node。

### 5.9 伪代码骨架

```python
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

class AgenticLoopState(TypedDict):
    messages: list
    iteration_count: int
    max_iterations: int
    token_used: int
    pending_approval: dict

def agent_node(state):
    """LLM 决策节点"""
    response = llm_with_tools.invoke(state["messages"])
    return {
        "messages": [response],
        "iteration_count": state["iteration_count"] + 1,
    }

def tool_node(state):
    """工具执行节点（含审批拦截）"""
    last = state["messages"][-1]
    results = []
    for call in last.tool_calls:
        tool = TOOLS[call["name"]]
        if tool.requires_approval:
            # Human-in-the-loop 中断
            decision = interrupt({"tool": call["name"], "args": call["args"]})
            if decision != "approve":
                results.append(ToolMessage("rejected", tool_call_id=call["id"]))
                continue
        results.append(tool.execute(**call["args"]))
    return {"messages": results}

def route(state):
    """条件边：有 tool_calls 继续循环，否则结束"""
    last = state["messages"][-1]
    if state["iteration_count"] >= state["max_iterations"]:
        return END
    if getattr(last, "tool_calls", None):
        return "tool"
    return END

graph = StateGraph(AgenticLoopState)
graph.add_node("agent", agent_node)
graph.add_node("tool", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", route, {"tool": "tool", END: END})
graph.add_edge("tool", "agent")
app = graph.compile(checkpointer=MemorySaver())
```

## 6. ReAct 执行内核

自由循环的执行内核为 ReAct：

```text
Reason → Action → Observation → Repeat
```

例如 Bug 修复：分析错误 → 读文件定位 → 修改代码 → 运行测试 → 观察结果 → 再修改…

## 7. Tool Calling 设计

工具清单（两种模式共享）：

| 工具 | 功能 | 是否需审批 |
| --- | --- | --- |
| read_file | 读取文件 | 否 |
| write_file | 写入文件 | 否 |
| edit_file | 编辑文件 | 否 |
| delete_file | 删除文件 | 是 |
| list_files | 浏览目录 | 否 |
| search_code | 代码搜索 | 否 |
| exec_command | 沙箱执行命令 | 白名单外审批 |
| run_test | 运行测试 | 否 |
| git_commit | 提交代码 | 是 |
| git_diff | 查看变更 | 否 |
| browser_search | 查询资料 | 否 |
| rag_retrieve | 知识检索（P1） | 否 |

## 8. Prompt 工程设计

目录：

```
prompts/
  manager/
  planner/
  coding/
  testing/
  evaluation/
  agentic_loop/     # 自由循环 System Prompt
```

每个 Agent 独立 System Prompt。自由循环模式额外要求：

- 明确「可用工具清单 + 何时调用」
- 明确「任务完成的判定标准」
- 明确「高风险操作需审批」
- 输出结构化结果（完成标志 + 变更说明）

示例（Coding Agent）：

```
你是一名高级软件工程师。
要求：
- 生成高质量代码
- 遵循工程规范
- 编写测试
- 输出结构化结果
```

## 9. Agent Memory 设计

### 短期记忆
Redis 保存：当前任务上下文、中间结果、checkpoint。

### 长期记忆
Milvus 保存：历史任务、优秀方案、Agent 经验。

## 10. Streaming 设计

Agent 执行过程中通过 SSE 推送：

```json
{
  "agent": "Coding",
  "event": "generate_code",
  "message": "正在生成User模块"
}
```

自由循环模式额外推送：每次迭代的 think/act/observe 事件，前端实时展示 Agent 的「思考-行动」过程。

## 11. 异常处理机制

| 异常类型 | 处理策略 |
| --- | --- |
| LLM 异常 | 重试（默认 3 次）→ 降级模型 |
| Tool 异常 | 捕获错误 → 返回 ToolMessage（错误信息）→ Agent 自主应对 |
| 任务异常 | 保存 Checkpoint → 支持恢复 |
| 沙箱异常 | 重建沙箱 → 从 Checkpoint 继续 |
| 审批超时 | 默认 reject → 终止任务 |

## 12. Human-in-the-loop 设计

高风险操作（删除文件、修改数据库、提交代码、执行危险命令）暂停流程：

```text
Agent → Approval Node → 用户确认 → 继续执行
```

- 实现：LangGraph `interrupt()` + checkpointer
- 审批超时（默认 30 分钟）自动 reject
- 详见 §5.8

## 13. Agent 版本管理

记录：Agent 名称、Prompt 版本、Model 版本、Tool 版本。

用于：效果分析、问题定位、A/B 对比。

## 14. 工程目录设计

```text
agent/
├── graph/
│   ├── workflow.py          # 流水线图定义
│   ├── agentic_loop.py      # 自由循环图定义
│   └── state.py             # 通用 State
├── nodes/
│   ├── manager.py           # 路由分发
│   ├── planner.py
│   ├── coding.py
│   └── evaluation.py
├── tools/
│   ├── file_tools.py
│   ├── shell_tool.py
│   └── git_tool.py
├── prompts/
├── memory/
└── router.py                # 模型路由
```

## 15. 总结

LangGraph 作为 DevPilot 核心 Agent 编排引擎，实现：

- 双模式引擎（流水线 + 自由循环）
- 多 Agent 协作
- 状态管理
- 工具调用
- 自修复循环
- 人机协同
- 执行追踪

为后续工程开发提供核心架构基础。
