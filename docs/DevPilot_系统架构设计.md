# DevPilot 系统架构设计文档 v2.0

## 1. 总体架构

系统采用「Frontend + Backend + Agent Runtime + AI Infrastructure」分层架构，并以**双模式执行引擎**为核心。

```
                        User (个人开发者 / 小团队)
                              |
                         Next.js (Web SaaS)
                              |
                        FastAPI (API Gateway / 多租户)
                              |
                   ┌──────────┴──────────┐
              Manager Agent (路由分发)
                   ┌──────────┴──────────┐
           Pipeline 流水线          Agentic Loop 自由循环
         (从零生成项目)            (修复/审查/脚本)
              │                        │
              └──────────┬─────────────┘
                         │
              LangGraph Runtime (状态机 + 编排)
                         │
   ┌─────────────┬───────┴───────┬─────────────┐
   LLM Router   RAG           Tools        Sandbox
   (国产为主)  (Milvus)   (文件/Git/Shell)  (Docker)
                         │
   ┌─────────────┬───────┴───────┬─────────────┐
  PostgreSQL     Redis         Milvus      对象存储
```

## 2. 技术选型

### 2.1 前端

- Next.js + React + TypeScript + Tailwind CSS + shadcn/ui
- 负责：Chat 界面、Agent 流程展示、Trace 查看、评测 Dashboard、文件浏览

### 2.2 后端

- FastAPI + Python
- 负责：用户认证、多租户隔离、任务管理、API 网关、SSE 推送

### 2.3 Agent 框架

- LangGraph
- 原因：状态管理、节点编排、条件分支、循环执行、Human-in-the-loop、Checkpoint 恢复

### 2.4 LLM 策略

- **国产模型为主**（DeepSeek / Qwen 等），满足数据合规与低成本
- **多模型路由（LLM Router）**：按节点/任务复杂度路由
  - 简单节点（Planner / Research / Report）→ 低价国产模型
  - 复杂节点（Architect / Coding / Evaluation）→ 更强模型
- **LLM 接口层抽象**：统一适配，可无痛切换/接入新模型（含 Claude / GPT 作为可选增强）

### 2.5 基础设施

| 组件 | 技术 | 用途 |
| --- | --- | --- |
| 关系数据库 | PostgreSQL | 用户、任务、评测、Trace |
| 缓存/短期记忆 | Redis | 会话、任务状态、限流 |
| 向量数据库 | Milvus | RAG 知识库、长期记忆 |
| 对象存储 | S3 兼容（MinIO/OSS） | 工作空间文件、知识文档 |
| 沙箱 | Docker + gVisor/Firecracker | 隔离执行用户/Agent 代码 |

## 3. 执行引擎设计（双模式）

### 3.1 路由分发

Manager Agent 接收用户任务，依据任务类型路由：

| 任务类型 | 模式 | 说明 |
| --- | --- | --- |
| Web 全栈生成 | Pipeline | 9 节点固定工序 |
| 脚本/工具生成 | Agentic Loop | 短链自由循环（可叠加轻量 Planner） |
| 代码审查/重构 | Agentic Loop | 读代码 + 分析 + 建议 |
| Bug 修复 | Agentic Loop | 定位 → 修改 → 验证 |

### 3.2 Pipeline 流水线模式

```
Manager → Planner → Research → Architect → Coding
        → Execution → Testing → Evaluation → Report
```

- 优点：结构化、可预期、可追踪
- 适用：从零生成项目、需求明确的多步骤任务

### 3.3 Agentic Loop 自由循环模式

```
┌─────────────────────────────────────┐
│  Agent (单强模型 + 长上下文)        │
│    think → act → observe → repeat   │
└──────────────┬──────────────────────┘
               │ 调用
   ┌───────────┴───────────┐
   │ 工具集               │ 沙箱
   │ 读/写/编辑文件        │ Docker 隔离容器
   │ Shell 执行           │ 含项目 + 工具环境
   │ Git                  │
   │ 代码搜索 / RAG        │
   └───────────────────────┘
```

- 优点：灵活、类 Claude Code 体验，适合探索式任务
- 约束：设最大迭代次数上限 + token 上限，防止失控

### 3.4 自修复循环

两种模式均支持测试失败后的自修复：

```
Testing 失败 → Coding → Execution → 重新 Testing
```

- 最大迭代次数：默认 3（可配置）
- 超限则终止，保存 Checkpoint，产出失败报告

## 4. Agent 架构设计（9 节点）

### Manager Agent
系统入口。职责：接收用户目标、初始化任务状态、路由到执行模式、调度后续 Agent。

### Planner Agent
输入：用户需求。输出：任务图（需求分析 → 数据库设计 → 代码生成 → 测试 → 评估）。

### Research Agent
职责：判断是否需要知识检索、调用 RAG 获取背景资料、为下游提供上下文。

### Architect Agent
职责：系统设计、技术选型、模块划分。

### Coding Agent
能力：文件生成、代码修改、项目初始化。

### Execution Agent
能力：调用 Docker/Python/Shell，执行编译、测试、检查。

### Testing Agent
职责：生成测试用例、执行测试、分析失败原因、触发 Coding 自修复循环。

### Evaluation Agent
职责：LLM-as-Judge。输出 7 字段评测标准（camelCase）：

```
{
  taskScore: 90,        // 任务完成度
  codeScore: 85,        // 代码质量
  testScore: 80,        // 测试覆盖/通过率
  hallucinationRate: 0.03, // 幻觉率
  confidence: 88,       // 置信度
  overall: 86,          // 综合评分
  report: "评测报告摘要"
}
```

### Report Agent
职责：汇总各 Agent 执行结果，生成最终交付报告。

## 5. RAG 架构

```
Document → Parser → Chunk → Embedding → Milvus → Retriever → Reranker → LLM
```

- Embedding：BGE 系列（中文友好）
- Vector DB：Milvus
- 定位：Agent 能力增强模块（为 Planner/Architect/Coding 注入知识），非文档问答
- 首版为 P1，MVP 后迭代

## 6. Memory 设计

### 短期记忆（Short Memory）
Redis 保存：当前任务状态、Agent 上下文、中间结果。

### 长期记忆（Long Memory）
Milvus 保存：用户偏好、历史任务经验、优秀方案。

## 7. Tool 设计

Agent 工具（统一接口：name / description / input_schema / execute）：

| 工具 | 功能 |
| --- | --- |
| File Manager | 读写、编辑、浏览文件 |
| Git Tool | Clone、查看提交、分析代码 |
| Code Executor | 沙箱内执行代码、运行测试 |
| Shell Tool | 沙箱内执行 Shell 命令 |
| Browser/Search | 查询技术资料 |
| RAG Retriever | 知识库检索（P1） |

## 8. Agent Trace 设计

记录完整执行链路：User Input → Planner → Retriever → LLM → Tool Call → Result。

字段：Agent 名称、输入、输出、Token 消耗、执行时间、状态。

## 9. 多租户与安全架构

### 9.1 多租户隔离

- SaaS 单实例多租户，**首版仅个人空间**（无共享项目）
- 隔离维度：PostgreSQL 按 user_id 隔离、对象存储按 user 前缀、沙箱按任务独立容器
- 预留：共享项目/团队空间作为后续扩展（tenant_id 字段预留）

### 9.2 安全纵深防御

- **沙箱隔离**（最高风险）：网络隔离、资源限额（CPU/内存）、执行超时、只读文件系统、gVisor/Firecracker 微 VM 隔离
- 认证：JWT + bcrypt
- 接口：Rate Limit + 输入校验
- 数据：TLS 传输 + 敏感数据加密

## 10. 部署架构（SaaS）

```
                    CDN / WAF
                        |
                   Next.js (前端)
                        |
                   FastAPI (API 网关，多副本)
                        |
          ┌─────────────┼─────────────┐
          │             │             │
    Agent Runtime   PostgreSQL    Redis
    (LangGraph)     (主从)        (集群)
          │             │             │
     Docker 沙箱池   Milvus      对象存储
     (动态创建)      (托管)      (MinIO/OSS)
```

- 前端/后端/Agent 无状态，可水平扩展
- 沙箱动态创建销毁，任务级隔离
- 监控：Prometheus + Grafana；日志：ELK/Loki
- 本地开发用 Docker Compose 一键起全套

## 11. 后续扩展方向

- Multi Model Router 增强（接入 Claude/GPT 作为复杂任务增强）
- 共享项目 + 成员权限（兑现小团队定位）
- RAG 知识库全量上线
- Agent Benchmark（自动测试 Agent 能力）
- 企业权限体系 + 私有化部署
