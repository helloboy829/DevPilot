# Legacy：编码产物七字段 LLM-as-Judge

> 2026-11-06。历史兼容模块，不是 DevPilot 的通用 AI 组件验收协议。产品已转向[评测工作台](../../../../README.md)，新版口径见[数据集与指标规范](../../../../docs/DevPilot_数据集与指标规范.md)。
> 旧记录中的端到端/插件加载声明本轮未复验，仅 15 项纯单测已复跑。不要将这个 fail-open post-run 评分用于正式通过门禁。

## 1. 当前范围

judge.py / metrics.py 为纯逻辑；runner.py / extension.py 在使用时惰性调用 DeerFlow 模型能力。cli.py 扫描编码任务产物并生成评分，extension.py 可在 lead 成功完成后触发兼容评分。

| 字段 | 范围 / 含义 |
| --- | --- |
| taskScore | 0–100，任务完成度 |
| codeScore | 0–100，代码质量 |
| testScore | 0–100，测试评价 |
| hallucinationRate | 0–1，模型主观估计，非经过标注统计的真实幻觉率 |
| confidence | 0–100，模型主观置信度，非已校准概率 |
| overall | 0–100，按下式聚合 |
| report | 文本摘要 |

~~~text
overall = (taskScore×0.35 + codeScore×0.30 + testScore×0.20 + confidence×0.15)
          × (1 − hallucinationRate)
~~~

以上权重属于历史编码评分，不能迁移为 CV/QA/Agent 统一权重。

## 2. CLI 与插件（具备完整环境时）

先按 backend 安装流程安装包括 ../devpilot 的本地依赖，再在 backend 的虚拟环境执行：

~~~bash
python -m devpilot.evaluation.cli --requirement "示例编码任务" --workspace /path/to/workspace --out report.json
~~~

命令需要已安装包、正确配置及模型访问权限；本轮未调用真实模型。

operator-controlled config.yaml：

~~~yaml
plugins:
  - use: devpilot.evaluation.extension:install
    config:
      enabled: true
      model: configured-judge-model
~~~

model 必须是实际配置的模型名。plugins 为 startup-only，变更需重启；不要写成 module:，也不要放到 API-writable extensions_config.json。插件异常只记录日志，不阻断原编码流程，因此不构成验收保障。
容器中的包路径须先修复，不能仅把 repo 根加入 PYTHONPATH：真实包位于 devpilot/src。

## 3. 纯逻辑测试

仓库根目录 PowerShell：

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'devpilot/src')
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/evaluation/tests -v
~~~

后续保留历史读兼容；正式评测采用 task-specific rubric、明确分母、待审/阻断与证据链，迁移不覆盖旧结果。
