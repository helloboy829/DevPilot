# DevPilot RAG知识库与数据架构设计文档 v2.0

## 1. 文档概述

### 1.1 文档目的

本文档设计 DevPilot 的 RAG（Retrieval-Augmented Generation）知识增强体系，目标是让 Agent 具备企业级知识理解能力，通过知识检索降低大模型幻觉，提高任务完成质量。

> **版本状态**：RAG 在需求分析中定为 P1（MVP 后第一迭代），但技术设计在此提前细化，便于后续直接实施。

### 1.2 RAG 定位

DevPilot 中的 RAG 不是简单文档问答，而是 **Agent 能力增强模块**：

- 为 Planner Agent 提供任务背景知识
- 为 Architect Agent 提供技术方案参考
- 为 Coding Agent 提供代码规范和最佳实践
- 为 Evaluation Agent 提供评价标准

## 2. RAG 总体架构

```text
原始知识文档 → 文档解析 → 文本切分 Chunk → Embedding 向量化 → Milvus
                                                          ↓
用户/Agent 查询 → Query Rewrite → Hybrid Search → Reranker → Top-K
                                                          ↓
                                              Agent 上下文增强 → LLM 生成
```

## 3. 知识库分类设计

### 3.1 技术规范库
编程规范、架构规范、API 设计规范、数据库规范。

### 3.2 项目代码知识库
历史项目代码、公共组件、最佳实践代码。

### 3.3 Agent 经验库
历史任务、Agent 执行轨迹、成功方案。

### 3.4 评测知识库
评价规则、Benchmark 数据、常见问题。

## 4. 文档处理流程

### 4.1 文档解析

支持格式：Markdown、PDF、Word、HTML、Git 代码仓库。

解析器：Markdown/代码用原生解析，PDF 用 PyMuPDF，Word 用 python-docx，HTML 用 BeautifulSoup + 正文抽取。

### 4.2 Chunk 切分策略

| 文档类型 | 切分方式 | chunk_size | overlap |
| --- | --- | --- | --- |
| 文本文档 | 固定长度 + 语义边界 | 512 tokens | 50 tokens（~10%） |
| 代码文件 | 按结构（Class/Function/Module） | ≤ 512 tokens | 0（结构切分不需 overlap） |
| Markdown | 按标题层级 + 段落 | 512 tokens | 50 tokens |

补充规则：

- 切分时保留元数据（源文件路径、标题层级、语言）
- 代码切分以 AST 语法树为准，避免切到函数中间
- 语义切分（可选增强）用 embedding 相似度检测段落边界

### 4.3 切分后处理

- 每个 chunk 附带 metadata（source、title、language、position）
- 过滤低质量 chunk（空白、纯符号、过短 < 10 tokens）

## 5. Embedding 设计

### 5.1 模型选型

| 模型 | 维度 | 特点 | 用途 |
| --- | --- | --- | --- |
| **bge-m3**（主选） | 1024 | 多语言、支持稠密+稀疏双检索 | 通用文档 + 代码 + Hybrid Search |
| bge-large-zh-v1.5 | 1024 | 中文效果好 | 中文文档备选 |

推荐 **bge-m3**：单模型同时产出稠密向量（dense）和稀疏向量（sparse），天然支持 Hybrid Search，避免维护两套模型。

### 5.2 向量化流程

```text
Document Chunk → Embedding Model → Dense Vector (1024d) + Sparse Vector
```

- 稠密向量用于语义检索
- 稀疏向量（BM25 风格词权重）用于关键词检索
- 两者入 Milvus 同一 collection，支持混合检索

## 6. Milvus 向量数据库设计

### 6.1 索引与距离度量

| 配置项 | 取值 | 说明 |
| --- | --- | --- |
| 索引类型 | HNSW | 高召回、中规模最优 |
| 索引参数 | M=16, efConstruction=200 | 建索引质量 |
| 距离度量 | COSINE | 语义相似度（向量归一化后等价 IP） |
| 检索参数 | ef=64 | 检索时的搜索宽度 |
| 稀疏索引 | BM25（SPARSE_INVERTED_INDEX） | 关键词检索 |

### 6.2 Collection 设计

**knowledge_collection（企业知识）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | VARCHAR | 主键 |
| content | VARCHAR | chunk 文本 |
| dense_vector | FLOAT_VECTOR(1024) | 稠密向量 |
| sparse_vector | SPARSE_FLOAT_VECTOR | 稀疏向量 |
| source | VARCHAR | 来源文档 |
| metadata | JSON | 标题/语言/位置等 |

**code_collection（代码知识）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | VARCHAR | 主键 |
| language | VARCHAR | 编程语言 |
| file_path | VARCHAR | 文件路径 |
| code | VARCHAR | 代码内容 |
| dense_vector | FLOAT_VECTOR(1024) | 稠密向量 |
| sparse_vector | SPARSE_FLOAT_VECTOR | 稀疏向量 |

**agent_memory_collection（Agent 经验）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | VARCHAR | 主键 |
| task_id | VARCHAR | 任务 ID |
| agent_name | VARCHAR | Agent 名称 |
| result | VARCHAR | 结果摘要 |
| score | FLOAT | 任务评分 |
| dense_vector | FLOAT_VECTOR(1024) | 稠密向量 |

## 7. 检索策略设计

### 7.1 Query Rewrite（查询改写）

用户/Agent 原始查询往往不适合直接检索，先经 LLM 改写：

```text
原始："订单系统怎么做"
改写：["订单系统 架构设计 最佳实践", "订单系统 数据库表设计", "订单 CRUD 接口 规范"]
```

- 一次改写为多个检索友好的子查询
- 多查询并行检索，结果合并去重

### 7.2 Hybrid Search（混合检索）

结合关键词 + 向量，弥补纯向量检索对精确术语（函数名、错误码、类名）的不足：

```text
Dense 检索（语义） + Sparse 检索（关键词） → 加权融合
```

融合算法：**RRF（Reciprocal Rank Fusion）**，公式：

```text
RRF(doc) = Σ 1 / (k + rank_i(doc))    # k 默认 60
```

### 7.3 Reranker（精排）

初检返回 Top 50，用 Reranker 精排到 Top 5-10：

- 模型：**bge-reranker-v2-m3**
- 输入：(query, candidate chunk) 对，输出相关性分数
- 效果：显著提升 top-K 精度（Precision@K）

### 7.4 检索参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| 初检 top_k | 50 | 混合检索召回数 |
| Rerank 后 top_k | 5-10 | 注入上下文的最终数量 |
| 最小相似度阈值 | 0.5 | 低于阈值不注入（防噪声） |

## 8. Agent 检索流程

```text
用户任务："设计用户认证模块"
    ↓
Planner Agent 判断是否需要知识
    ↓
Query Rewrite 生成多个子查询
    ↓
Hybrid Search（Dense + Sparse）
    ↓
返回 Top 50 → Reranker → Top 5-10
    ↓
拼接 Context（标注来源）
    ↓
LLM 生成方案
```

## 9. Agentic RAG

让 Agent 自主决定检索策略（区别于固定检索流程）：

| 决策点 | Agent 自主能力 |
| --- | --- |
| 是否检索 | 信息充足则不检索，避免噪声 |
| 检索什么 | 自主构造 query，而非用原始输入 |
| 检索几次 | 检索结果不足时迭代补检 |
| 何时停止 | 结果相关性达标即停 |

实现：检索工具 `rag_retrieve(query, top_k)` 作为自由循环模式的工具之一，Agent 按需调用。

## 10. Agent Memory 设计

### 10.1 短期记忆
Redis 保存：当前任务状态、Agent 上下文、中间结果。

### 10.2 长期记忆
Milvus（agent_memory_collection）保存：用户习惯、历史任务、优秀解决方案。

- 长期记忆写入时机：任务完成后，高质量任务（评分高）自动沉淀
- 检索时机：新任务启动时，检索相似历史任务经验注入上下文

## 11. 关系数据库设计

关系数据库（PostgreSQL）保存知识库元信息（非向量）：

| 表 | 用途 |
| --- | --- |
| knowledge_document | 知识文件信息（见数据库详细设计 §2.9） |
| knowledge_chunk | chunk 元数据（doc_id、position、milvus_id 映射） |

## 12. RAG 效果评估

### 12.1 Retrieval 指标
- Recall@K
- Precision@K
- MRR（Mean Reciprocal Rank）

### 12.2 Generation 指标
- Faithfulness（忠实度）
- Answer Relevance（相关性）
- Hallucination Rate（幻觉率）

### 12.3 Agent 指标
- Task Success Rate
- Tool Success Rate

### 12.4 评估方法
- 离线评测集（query + 标准答案 + 相关文档标注）
- 对比实验：不同 chunk/检索/rerank 配置的 A/B

## 13. 总结

DevPilot RAG 系统通过「知识库 + Hybrid Search + Reranker + Agentic RAG」为多智能体研发平台提供知识增强能力，支持：

- 知识管理
- 代码理解
- 经验复用
- 效果提升
