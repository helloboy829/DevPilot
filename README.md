# DevPilot

智能研发协同平台 —— 面向个人开发者与小团队的 SaaS 多智能体研发协同平台，基于 Next.js + FastAPI + LangGraph + Milvus。

## 文档

本仓库包含 DevPilot 的完整项目生命周期设计文档（Markdown 格式），按阶段组织：

| 阶段 | 文档 | 说明 |
| --- | --- | --- |
| 可行性分析 | [docs/DevPilot_可行性分析.md](docs/DevPilot_可行性分析.md) | 产品定位、市场/技术/经济/合规可行性、风险与立项结论 |
| 需求分析 | [docs/DevPilot_需求分析.md](docs/DevPilot_需求分析.md) | 用户画像、用例、功能需求（P0/P1/P2）、非功能需求、MVP 范围 |
| 概要设计 | [docs/DevPilot_系统架构设计.md](docs/DevPilot_系统架构设计.md) | 总体架构、双模式执行引擎、技术选型、Agent/RAG/Memory/Tool/Trace、部署 |
| 详细设计 | [docs/DevPilot_LangGraph工程设计文档.md](docs/DevPilot_LangGraph工程设计文档.md) | Agent Runtime：双模式、State、Node、Edge、ReAct、Tool、异常恢复、HITL |
| 详细设计 | [docs/DevPilot_Prompt工程设计文档.md](docs/DevPilot_Prompt工程设计文档.md) | 各 Agent System Prompt、自由循环完成判定、评测 Prompt、版本管理 |
| 详细设计 | [docs/DevPilot_API接口设计文档.md](docs/DevPilot_API接口设计文档.md) | RESTful + SSE/WebSocket 接口、审批接口、错误码、安全设计 |
| 详细设计 | [docs/DevPilot_实时通信协议设计.md](docs/DevPilot_实时通信协议设计.md) | SSE 事件类型与字段级协议、审批数据流、心跳重连 |
| 详细设计 | [docs/DevPilot_数据库详细设计.md](docs/DevPilot_数据库详细设计.md) | PostgreSQL 表结构、索引、多租户隔离、数据生命周期 |
| 详细设计 | [docs/DevPilot_RAG知识库与数据架构设计文档.md](docs/DevPilot_RAG知识库与数据架构设计文档.md) | RAG 知识库、Hybrid Search、Reranker、Milvus 设计 |
| 测试方案 | [docs/DevPilot_测试方案.md](docs/DevPilot_测试方案.md) | 测试层次、Agent 评测、沙箱安全测试、性能/成本回归 |
| 部署运维 | [docs/DevPilot_部署与运维设计.md](docs/DevPilot_部署与运维设计.md) | 部署架构、沙箱池、CI/CD、监控告警、备份恢复 |

## 关键设计决策

- **双模式执行引擎**：Pipeline 流水线（从零生成项目）+ Agentic Loop 自由循环（修复/审查/脚本）
- **LLM 策略**：国产模型为主 + 多模型路由，接口层抽象可切换
- **部署形态**：SaaS 云服务，首版仅个人空间，预留团队协作
- **Human-in-the-loop**：关键/高危操作人工审批
