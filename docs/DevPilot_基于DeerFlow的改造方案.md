# DevPilot 基于 DeerFlow 的改造方案

> 版本：v1.0 ｜ 日期：2026-08-13 ｜ 状态：落地中

## 1. 背景与决策

DevPilot 最初的自主设计（双模式执行引擎、Next.js + FastAPI + LangGraph + Milvus、9-Agent Pipeline、7 字段评测）经可行性分析后发现：**DeerFlow 2.0（bytedance/deer-flow，MIT）已实现其中约 80% 的底座能力**。重复造轮子成本高、收益低。

最终决策：**平铺 fork DeerFlow 2.0 作为底座，DevPilot 专注补齐 DeerFlow 的空白——研发场景垂直化**。

| 维度 | 决策 | 理由 |
| --- | --- | --- |
| 底座 | 复用 DeerFlow 2.0（MIT） | 多智能体编排、沙箱、记忆、工具、Skills、MCP、tracing 已齐备 |
| 迁移方式 | 平铺 fork（源码直接拷贝进本仓库，不带 .git 历史） | 便于后续自由修改；保留上游可追溯性（README_upstream + docs/upstream） |
| 多租户 / 计费 | **移除**（已确认） | DeerFlow 单租户，个人/小团队场景暂不需要 |
| 差异化 | 研发 Skills + 7 字段评测 + 操作级审批 | DeerFlow 的空白 |

## 2. DeerFlow 2.0 能力盘点（复用清单）

以下能力 DevPilot **直接复用，不改动**：

| 能力 | DeerFlow 实现 | DevPilot 用法 |
| --- | --- | --- |
| 主智能体（Lead Agent） | `packages/harness/deerflow/agents/lead_agent/` | 作为研发任务的总控 |
| 子智能体（Subagents） | `general-purpose` / `bash` / `custom_agents` | 代码生成、执行、验证的并行 worker |
| 沙箱执行 | Local / Docker / AIO / E2B / provisioner 多模式 | 本地跑代码、跑测试（当前 local 模式） |
| 工具集 | bash / read_file / write_file / view_image / 浏览器 / 搜索 / MCP | 研发任务的标准工具 |
| 技能系统 | `skills/public/`（23 个内置）+ `skills/custom/<name>/SKILL.md` | ★ 承载 DevPilot 研发 Skills |
| 中间件（Middlewares） | safety / summarization / loop_detection / tool_error_handling 等 | ★ 评测体系的挂载点 |
| 记忆 | 短期滑动窗口 + 长期 memory 抽取 | 项目上下文延续 |
| 模型路由 | `config.yaml` `models:` 多模型 + `PatchedChatDeepSeek` 等适配器 | 对接国产模型（DeepSeek V4 等） |
| 前端 / 网关 | Next.js 前端 + FastAPI Gateway（`/api/*`） | 交互界面 |
| Tracing / 事件 | run_events、agent_storage | 运行可视化、评测数据采集 |

## 3. DevPilot 差异化定制点

DevPilot 在 DeerFlow 底座上新增三类能力：

### 3.1 研发专用 Skills（核心差异化）

DeerFlow 内置技能只有 `code-documentation`、`frontend-design` 等通用技能，**缺研发场景技能**。DevPilot 新增 5 个（见 `skills/custom/`）：

| Skill | 职责 | 触发场景 |
| --- | --- | --- |
| `code-generation` | 从需求/设计生成可运行代码 | 「实现 X 功能」 |
| `bug-fix` | 定位并修复 Bug | 「修复 X 问题」 |
| `test-generation` | 生成单元/集成测试 | 「给 X 写测试」 |
| `code-review` | 代码审查，输出问题清单 | 「审查这段代码」 |
| `architecture-review` | 架构/技术选型评审 | 「评审这个架构」 |

> 实现方式：完全走 DeerFlow 原生 `skills/custom/` 约定（`SKILL.md` YAML frontmatter + Markdown 正文），**不改核心代码**。当前为骨架，待跑通后按真实运行效果填充 Prompt。

### 3.2 评测体系（7 字段 LLM-as-Judge）

DeerFlow **无评测能力**。DevPilot 实现 7 字段评分（源自系统架构设计文档）：

```json
{
  "taskScore": 90,          // 任务完成度
  "codeScore": 85,          // 代码质量
  "testScore": 80,          // 测试评分
  "hallucinationRate": 0.03, // 幻觉率
  "confidence": 88,          // 置信度
  "overall": 86,             // 综合
  "report": "评测报告摘要"
}
```

- 位置：`devpilot/evaluation/`（judge.py + metrics.py）
- 挂载点：DeerFlow 的 **post-run 中间件**（任务完成后触发评测），或独立 Gateway router（`/api/evaluation/*`）——待跑通后二选一

### 3.3 操作级审批（后续）

基于 DeerFlow guardrails / authorization 扩展，用于高风险操作（写文件、执行命令、对外请求）的人机审批。**不在 MVP 范围**。

## 4. 定制实现路径

| 定制点 | 采用机制 | 改动位置 | 是否改核心 |
| --- | --- | --- | --- |
| 研发 Skills | 原生 `skills/custom/` | `skills/custom/<name>/SKILL.md` | 否 |
| 评测体系 | 中间件 / 独立 router | `devpilot/evaluation/` + 中间件挂载 | 否（新增） |
| 模型对接 | `config.yaml` `models:` + 适配器 | `config.yaml`、`.env` | 否 |
| 审批 | guardrails / authorization | 待定 | 否（扩展） |

**原则**：优先使用 DeerFlow 扩展机制（skills/custom、middlewares、MCP、config），仅在确有必要时才改核心代码；改动核心需记录于 `docs/upstream/` 对照。

## 5. 目录映射

```
DevPilot/
├── backend/  frontend/  skills/public/   # DeerFlow 上游（不改）
├── skills/custom/                        # ★ DevPilot 研发 Skills（5 个）
├── devpilot/evaluation/                  # ★ DevPilot 评测体系
├── docs/                                 # DevPilot 设计文档（11 份）
├── docs/upstream/                        # DeerFlow 上游文档（对照）
├── config.yaml  .env                     # 模型配置（DeepSeek V4）
└── README.md                             # 项目定位 + 目录说明
```

## 6. 工作量评估与里程碑

| 里程碑 | 内容 | 状态 |
| --- | --- | --- |
| M1 | 本地跑起 DeerFlow（Docker + DeepSeek V4） | ✅ 完成 |
| M2 | 跑通一个研发任务，验证核心链路 | ✅ 完成 |
| M3 | 填充 5 个研发 Skills 的 Prompt（基于真实运行效果） | ✅ 完成 |
| M4 | 实现评测体系（judge.py + 挂载点） | ✅ 完成 |
| M5 | 端到端验证：研发任务 → 产物 → 7 字段评测 | ✅ 完成 |

### M2 验证结论（2026-08-13/14）

端到端研发闭环已跑通：**需求 → 写代码（write_file）→ 写测试 → 执行（bash）→ 5 用例全部通过**。

关键发现与配置调整：

1. **`sandbox.allow_host_bash` 默认 `false`**（安全默认）：`LocalSandboxProvider` 不是安全隔离边界，
   故默认关闭 bash 执行、只允许读写文件。DevPilot 的研发闭环依赖「执行测试」，故在**单用户本地
   可信环境**下设为 `true`（`config.yaml` → `sandbox.allow_host_bash`）。如需隔离执行，改用
   `AioSandboxProvider`（Docker 沙箱）即可，无需再开此开关。
2. **历史锚定现象**：模型在旧线程里曾 3 次断言「无 bash 工具」，即使开启后仍顺着自己的历史继续
   拒绝；全新线程立即可用。→ 遇到「工具缺失」类问题，**先换新线程验证**，避免被历史带偏。
3. **记忆系统生效**：早期「模型坦白无法执行命令」被抽取为长期偏好（`[preference | 0.90]`）并注入
   后续线程——说明 memory 链路正常，但也提示评测体系需对「过时偏好」做时效处理（见 M4）。
4. **容器内无 pytest**：gateway 容器 Python 3.12 仅有标准库，测试需 `python -m unittest` 或
   `pip install pytest`。研发 Skills 的 Prompt 应默认引导 `unittest`（零依赖）。

### M4 验证结论（2026-08-14）

评测体系落地于 `devpilot/evaluation/`，纯逻辑部分（`judge.py` + `metrics.py`）零依赖、
15 个 unittest 用例全绿：

1. **纯逻辑**：7 字段钳制、`compute_overall` 加权（task .35 / code .30 / test .20 /
   confidence .15）× (1 − 幻觉率)、`<think>` 剥离、JSON 解析（camelCase/蛇形/代码围栏/缺 overall/
   垃圾输入）、`aggregate` 均通过。
2. **CLI**：`python -m devpilot.evaluation.cli` 可独立对任意产物目录评分。
3. **挂载点**：`extension.py` 走 DeerFlow 官方 `plugins:` 机制（`devpilot.evaluation.extension:install`），
   实现 `TaskLifecycleContributor`。已用真实 `load_extensions` 验证：`install()` 正常注册、
   无诊断告警、`has_task_lifecycle=True`；子任务/失败 outcome 正确短路。触发条件 = lead 任务
   `completed`，写报告到 `outputs/evaluation/<run_id>.json`，全程 fail-open。
4. **部署注意**：`plugins` 是 startup-only 字段（改后需重启）；`devpilot` 需对网关进程可 import
   （`pip install -e devpilot/` 或 `PYTHONPATH=/app/project`）。

### M5 验证结论（2026-08-14）

对 M2 真实产物（回文判断任务，`palindrome.py` + `test_palindrome.py`，5 个 unittest 全通过）
跑通端到端评测，DeepSeek V4 作为 Judge 输出 7 字段报告：

| 字段 | 值 |
| --- | --- |
| taskScore | 95 |
| codeScore | 90 |
| testScore | 90 |
| hallucinationRate | 0.0 |
| confidence | 92 |
| overall | 92 |

评测报告（摘要）：需求全部达成（空串视为回文、忽略大小写与非字母数字字符、统一小写），
实现简洁符合 Python 惯用法；测试覆盖核心分支但缺少「全非字母数字」「混合大小写/符号」
「非回文带符号」等边界用例；未提供研发过程摘要，置信度略减。

→ **研发任务 → 产物 → 7 字段评测** 闭环已验证。剩余工作为产品化接入（前端展示评测报告、
评测结果入库与趋势看板），不在当前里程碑内。

## 7. 风险与回退

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| DeerFlow 上游迭代 | fork 落后上游 | 定期同步（README_upstream 记录版本） |
| 定制点侵入核心 | 升级冲突 | 坚持扩展机制优先；改动核心需最小化并留对照 |
| 国产模型能力边界 | 复杂任务质量 | 多模型路由（Pro 主 / Flash 辅助） |
| Docker Hub 访问 | 首次构建慢/失败 | 预拉取镜像 / 配置镜像加速 |
