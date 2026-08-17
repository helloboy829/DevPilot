# DevPilot 评测体系（7 字段 LLM-as-Judge）

对一次研发任务做机器可读的 7 字段评分，用于 DevPilot 的质量度量与后续优化闭环。

## 7 字段评分标准

| 字段（camelCase） | 含义 | 范围 |
| --- | --- | --- |
| `taskScore` | 任务完成度 | 0–100 |
| `codeScore` | 代码质量 | 0–100 |
| `testScore` | 测试覆盖与通过情况 | 0–100 |
| `hallucinationRate` | 幻觉率（越接近 0 越好） | 0–1 |
| `confidence` | 评测置信度 | 0–100 |
| `overall` | 综合评分 | 0–100 |
| `report` | 评测报告摘要 | 文本 |

综合评分公式（见 `judge.py::compute_overall`）：

```
overall = (taskScore×0.35 + codeScore×0.30 + testScore×0.20 + confidence×0.15)
          × (1 − hallucinationRate)
```

## 模块结构

```
evaluation/
├── judge.py      # 纯逻辑核心（零依赖）：SEVEN_FIELDS、EvaluationResult、compute_overall、
│                 #   parse_judge_output（剥离 <think>、代码围栏后取 JSON）、build_prompt
├── metrics.py    # aggregate()：一批结果的均分 / 幻觉率 / 通过率
├── runner.py     # judge_with_model()：惰性调用 deerflow.models.create_chat_model
├── cli.py        # 命令行入口 + collect_artifacts()（扫描工作区产物）
├── extension.py  # post-run 自动评测挂载点（TaskLifecycleContributor，走 plugins 机制）
└── tests/test_judge_metrics.py  # 15 个 unittest 用例（纯逻辑，无外部依赖）
```

`judge.py` / `metrics.py` 不依赖 `deerflow`，可独立单测；`runner.py` / `extension.py`
只在使用时惰性 import `deerflow`，避免加载扩展时拖慢网关启动。

## 两种用法

### 1. CLI（已验证端到端）

对一次研发任务的产物目录做评测，输出 7 字段 JSON 报告：

```bash
# 在 repo 根目录，PYTHONPATH 含 repo 根 + backend/packages/harness
python -m devpilot.evaluation.cli \
  --requirement "实现一个回文判断函数 is_palindrome(s)..." \
  --workspace /path/to/task/workspace \
  --tests /path/to/test-output.txt \
  --out report.json
```

参数：
- `--requirement` / `--requirement-file`：任务需求文本（二选一）
- `--workspace`：产物工作区目录（扫描源码/文本文件，上限 40 个文件 × 4000 字符）
- `--tests`：测试输出文件（`python -m unittest -v` 之类的通过/失败信息）
- `--transcript`：研发过程对话摘录（可选，用于幻觉率/置信度）
- `--model`：评测用模型名（默认取 `config.yaml` 首个模型）
- `--out`：报告输出 JSON 路径

### 2. post-run 自动评测（挂载点，已验证加载）

通过 DeerFlow 官方 `plugins:` 扩展机制，在**主智能体（lead）任务成功完成后**
自动收集该线程工作区产物 → 评测 → 写报告到 `outputs/evaluation/<run_id>.json`。

`config.yaml`：

```yaml
plugins:
  - use: devpilot.evaluation.extension:install
    config:
      enabled: true
      model: deepseek-v4      # 可选，评测用模型名
      requirement: "..."      # 可选，静态需求（覆盖工作区 task-requirement.txt）
```

触发条件（`extension.py`）：`info.kind == "lead"` 且 `outcome == completed`；
子任务、失败/中断不触发。全程 **fail-open**——任何异常只记日志，不阻断研发主流程。

**前置条件**：`devpilot` 必须能被网关进程 import。二选一：

```bash
# 方式 A：可编辑安装进网关 venv（一次性）
/app/backend/.venv/bin/pip install -e /app/project/devpilot

# 方式 B：网关进程环境变量加 repo 根
#   docker-compose gateway service -> environment: PYTHONPATH=/app/project
```

改 `plugins` 需要重启网关（`plugins` 是 startup-only 字段）。

## 运行单测

```bash
python -m unittest discover -s devpilot/evaluation/tests -v
```

15 个用例覆盖：评分钳制、overall 回填、camelCase 序列化、`compute_overall`
加权与幻觉惩罚、`strip_think_blocks`、`parse_judge_output`（干净 JSON / 蛇形 /
代码围栏+think / 缺 overall / 垃圾输入）、`build_prompt`、`aggregate`。
