# DevPilot RAG知识库与数据架构设计文档 v1.0

## 1. 文档概述

### 1.1 文档目的

本文档用于设计DevPilot智能研发协同平台中的RAG（Retrieval-Augmented Generation）知识增强体系。

目标是让Agent具备企业级知识理解能力，通过知识检索降低大模型幻觉，提高任务完成质量。

### 1.2 RAG定位

DevPilot中的RAG不是简单文档问答，而是Agent能力增强模块。

主要作用：

- 为Planner Agent提供任务背景知识
- 为Architect Agent提供技术方案参考
- 为Coding Agent提供代码规范和最佳实践
- 为Evaluation Agent提供评价标准

## 2. RAG总体架构

数据流：

```text
原始知识文档
    |
    ↓
文档解析
    |
    ↓
文本切分 Chunk
    |
    ↓
Embedding向量化
    |
    ↓
Milvus向量数据库
    |
    ↓
Retriever检索
    |
    ↓
Reranker排序
    |
    ↓
Agent上下文增强
    |
    ↓
LLM生成结果
```

## 3. 知识库分类设计

### 3.1 技术规范库

存储：

- 编程规范
- 架构规范
- API设计规范
- 数据库规范

### 3.2 项目代码知识库

存储：

- 历史项目代码
- 公共组件
- 最佳实践代码

### 3.3 Agent经验库

存储：

- 历史任务
- Agent执行轨迹
- 成功方案

### 3.4 评测知识库

存储：

- 评价规则
- Benchmark数据
- 常见问题

## 4. 文档处理流程

### 4.1 文档解析

支持：

- Markdown
- PDF
- Word
- HTML
- Git代码仓库

### 4.2 Chunk切分策略

采用：

- 固定长度切分
- 语义切分
- 代码结构切分

代码文件建议按照：

Class

Function

Module

进行切分。

## 5. Embedding设计

Embedding模型：

推荐：

- BGE系列
- text-embedding模型

流程：

```text
Document Chunk

↓

Embedding Model

↓

Vector
```

## 6. Milvus向量数据库设计

Collection设计：

### 6.1 knowledge_collection

保存企业知识。

字段：

id

content

embedding

source

metadata

### 6.2 code_collection

保存代码知识。

字段：

id

language

file_path

code

embedding

### 6.3 agent_memory_collection

保存Agent历史经验。

字段：

task_id

agent_name

result

score

## 7. Agent检索流程

用户任务：

```text
"设计用户认证模块"

↓

Planner Agent判断是否需要知识

↓

Retriever生成查询

↓

Milvus搜索

↓

返回Top-K结果

↓

Reranker优化

↓

拼接Context

↓

LLM生成方案
```

## 8. Agent Memory设计

### 8.1 短期记忆

Redis保存：

- 当前任务状态
- Agent上下文
- 中间结果

### 8.2 长期记忆

Milvus保存：

- 用户习惯
- 历史任务
- 优秀解决方案

## 9. 数据库设计

关系数据库：

PostgreSQL

核心表：

task

保存任务信息。

agent_execution

保存Agent执行记录。

knowledge_document

保存知识文件信息。

evaluation_result

保存评测结果。

## 10. RAG效果评估

指标：

### 10.1 Retrieval指标

- Recall@K
- Precision@K

### 10.2 Generation指标

- Faithfulness
- Answer Relevance
- Hallucination Rate

### 10.3 Agent指标

- Task Success Rate
- Tool Success Rate

## 11. 优化方向

### 1. Query Rewrite

根据用户意图优化搜索。

### 2. Hybrid Search

结合：

关键词搜索 + 向量搜索

### 3. Reranker

使用：

BGE-Reranker

### 4. Agentic RAG

让Agent自主决定：

是否检索

检索什么

检索几次

## 12. 总结

DevPilot RAG系统通过知识库、向量检索、Agent自主调用机制，为多智能体研发平台提供知识增强能力。

该设计支持企业级Agent应用中的：

- 知识管理
- 代码理解
- 经验复用
- 效果提升
