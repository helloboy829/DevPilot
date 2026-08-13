# DevPilot 数据库详细设计 v1.0

## 0. 文档说明

本文档定义 DevPilot 关系数据库（PostgreSQL）的详细表结构。向量数据（RAG/长期记忆）由 Milvus 承载，见《RAG知识库与数据架构设计文档》，本文档不重复。

**约定**：

- 数据库命名：表名/字段统一 snake_case
- 主键：UUID v4（对外暴露，避免信息泄露与分布式冲突）
- 时间戳：所有表含 `created_at` / `updated_at`（TIMESTAMPTZ）
- 多租户：首版仅个人空间，统一以 `user_id` 隔离；预留 `tenant_id` 字段用于后续共享项目/团队

## 1. ER 关系总览

```
users 1───N projects 1───N tasks 1───N agent_executions
                                       1───N trace_spans
                                       1───N approvals
                                       1───1 evaluation_results
                                       1───N workspace_files
users 1───N knowledge_documents (P1)
users 1───N usage_records (P1)
```

## 2. 表结构定义

### 2.1 users — 用户表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 用户 ID |
| email | VARCHAR(255) | UNIQUE, NOT NULL | 登录邮箱 |
| password_hash | VARCHAR(255) | NOT NULL | bcrypt 密码哈希 |
| nickname | VARCHAR(100) | | 昵称 |
| status | VARCHAR(20) | DEFAULT 'active' | active / disabled |
| created_at / updated_at | TIMESTAMPTZ | | 时间戳 |

### 2.2 projects — 项目表（个人，预留团队）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 项目 ID |
| user_id | UUID | FK→users, NOT NULL | 归属用户（个人空间） |
| tenant_id | UUID | NULL | 预留：团队/租户 ID |
| name | VARCHAR(200) | NOT NULL | 项目名称 |
| description | TEXT | | 项目描述 |
| status | VARCHAR(20) | DEFAULT 'active' | active / archived / deleted |
| created_at / updated_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_projects_user` (user_id)

### 2.3 tasks — 任务表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 任务 ID |
| user_id | UUID | FK→users, NOT NULL | 归属用户 |
| project_id | UUID | FK→projects, NOT NULL | 归属项目 |
| title | VARCHAR(200) | NOT NULL | 任务标题 |
| goal | TEXT | NOT NULL | 任务目标（自然语言） |
| task_type | VARCHAR(30) | NOT NULL | fullstack_gen / script_gen / code_review / bug_fix |
| exec_mode | VARCHAR(20) | NOT NULL | pipeline / agentic_loop |
| status | VARCHAR(20) | NOT NULL | CREATED / RUNNING / PAUSED / SUCCESS / FAILED / CANCELLED |
| checkpoint | JSONB | | 恢复点（LangGraph checkpoint 引用） |
| workspace_id | UUID | FK→workspaces | 关联工作空间 |
| token_used | BIGINT | DEFAULT 0 | 累计 token 消耗 |
| credit_used | NUMERIC(10,2) | DEFAULT 0 | 累计信用点消耗 |
| error_message | TEXT | | 失败原因 |
| started_at / finished_at | TIMESTAMPTZ | | 起止时间 |
| created_at / updated_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_tasks_user` (user_id)、`idx_tasks_project` (project_id)、`idx_tasks_status` (status)

### 2.4 agent_executions — Agent 执行记录（节点级）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 执行记录 ID |
| task_id | UUID | FK→tasks, NOT NULL | 归属任务 |
| agent_name | VARCHAR(50) | NOT NULL | Manager/Planner/Coding... |
| exec_mode | VARCHAR(20) | NOT NULL | pipeline / agentic_loop |
| status | VARCHAR(20) | NOT NULL | running / success / failed / skipped |
| input | JSONB | | 输入 |
| output | JSONB | | 输出 |
| token_input / token_output | BIGINT | | token 消耗 |
| duration_ms | BIGINT | | 执行耗时 |
| model_name | VARCHAR(100) | | 使用的模型 |
| prompt_version | VARCHAR(50) | | Prompt 版本 |
| error_message | TEXT | | 失败原因 |
| started_at / finished_at | TIMESTAMPTZ | | 起止时间 |
| created_at | TIMESTAMPTZ | | 创建时间 |

索引：`idx_agent_exec_task` (task_id)、`idx_agent_exec_agent` (agent_name)

### 2.5 trace_spans — Trace 链路（工具/子步骤级）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | Span ID |
| task_id | UUID | FK→tasks, NOT NULL | 归属任务 |
| execution_id | UUID | FK→agent_executions | 归属节点 |
| parent_span_id | UUID | NULL | 父 Span（树形） |
| span_type | VARCHAR(30) | NOT NULL | llm / tool / retriever |
| name | VARCHAR(200) | NOT NULL | 步骤名称 |
| input / output | JSONB | | 输入输出 |
| token_used | BIGINT | | token |
| duration_ms | BIGINT | | 耗时 |
| status | VARCHAR(20) | NOT NULL | success / error |
| started_at / finished_at | TIMESTAMPTZ | | 起止时间 |

索引：`idx_span_task` (task_id)、`idx_span_exec` (execution_id)

### 2.6 workspace_files — 工作空间文件元数据

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 文件 ID |
| task_id | UUID | FK→tasks, NOT NULL | 归属任务 |
| path | TEXT | NOT NULL | 相对路径 |
| size | BIGINT | | 文件大小 |
| object_key | TEXT | | 对象存储 key（实际内容存对象存储） |
| content_hash | VARCHAR(64) | | 内容 SHA-256 |
| created_at / updated_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_files_task` (task_id)

### 2.7 evaluation_results — 评测结果

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 评测 ID |
| task_id | UUID | FK→tasks, UNIQUE | 归属任务（一对一） |
| task_score | NUMERIC(5,2) | | 任务完成度 0-100 |
| code_score | NUMERIC(5,2) | | 代码质量 0-100 |
| test_score | NUMERIC(5,2) | | 测试评分 0-100 |
| hallucination_rate | NUMERIC(5,4) | | 幻觉率 0-1 |
| confidence | NUMERIC(5,2) | | 置信度 0-100 |
| overall | NUMERIC(5,2) | | 综合评分 0-100 |
| report | TEXT | | 评测报告摘要 |
| detail | JSONB | | 评测明细（各维度打分理由） |
| model_name | VARCHAR(100) | | 评测模型 |
| created_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_eval_task` (task_id)

### 2.8 approvals — 审批记录

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 审批 ID |
| task_id | UUID | FK→tasks, NOT NULL | 归属任务 |
| execution_id | UUID | FK→agent_executions | 触发审批的节点 |
| action_type | VARCHAR(50) | NOT NULL | commit / exec_command / db_write / file_delete |
| payload | JSONB | NOT NULL | 待审批操作详情 |
| status | VARCHAR(20) | NOT NULL | pending / approved / rejected / timeout |
| decided_by | UUID | FK→users | 审批人 |
| decided_at | TIMESTAMPTZ | | 决策时间 |
| created_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_approval_task` (task_id)、`idx_approval_status` (status)

### 2.9 knowledge_documents — 知识文档（P1）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 文档 ID |
| user_id | UUID | FK→users, NOT NULL | 归属用户 |
| name | VARCHAR(255) | NOT NULL | 文件名 |
| source_type | VARCHAR(20) | NOT NULL | md / pdf / docx / html / git |
| object_key | TEXT | | 原始文件存储 key |
| chunk_count | INT | | 切分块数 |
| status | VARCHAR(20) | | processing / ready / failed |
| created_at / updated_at | TIMESTAMPTZ | | 时间戳 |

索引：`idx_knowledge_user` (user_id)

### 2.10 usage_records — 用量记录（P1）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | UUID | PK | 用量 ID |
| user_id | UUID | FK→users, NOT NULL | 归属用户 |
| task_id | UUID | FK→tasks | 关联任务 |
| metric | VARCHAR(20) | NOT NULL | token_input / token_output / credit |
| amount | NUMERIC(20,2) | NOT NULL | 数量 |
| model_name | VARCHAR(100) | | 模型 |
| recorded_at | TIMESTAMPTZ | NOT NULL | 记录时间 |

索引：`idx_usage_user_time` (user_id, recorded_at)

## 3. 索引与约束策略

- 高频查询路径均建索引（user_id、task_id、status）
- 外键统一加约束，保证引用完整性
- `tasks.status` 等枚举字段用 VARCHAR + CHECK 约束（易演进，避免 PG ENUM 迁移成本）
- 大 JSONB 字段（checkpoint、detail、input/output）按需查询，避免 SELECT *

## 4. 多租户隔离设计

首版仅个人空间，隔离策略：

1. **应用层**：所有查询强制带 `user_id` 过滤（ORM 层统一注入）
2. **数据库层**：表均含 `user_id` 外键，配合索引保证查询性能
3. **预留演进**：`projects` 表已含 `tenant_id` 字段，后续共享项目/团队空间无需改表结构

## 5. 数据生命周期

- 任务/文件：用户可删除（软删除 + 定时清理对象存储）
- Trace/execution：保留 N 天（默认 30）后归档/清理
- 评测结果：随任务保留
- 审计/用量记录：长期保留（合规与计费）
