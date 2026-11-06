# DevPilot 领域定制层

> 2026-11-06。定位从通用研发定制调整为 AI 组件评测；以下严格区分当前代码与目标。

## 当前结构

~~~text
devpilot/
├── pyproject.toml
└── src/devpilot/
    ├── toolkit/       # effect/perf/transports/report，初版组件测试
    │   └── tests/     # 32 个纯单元测试
    └── evaluation/    # legacy：代码产物七字段 LLM-as-Judge
        └── tests/     # 15 个纯单元测试
~~~

Gateway 的 backend/app/component_tests/service.py 调用 toolkit；不是已经由 Lead Agent 自动完成端到端评测。
当前基础文本判定与阶梯负载可复用，但仍有误 PASS、待审分母、TLS/凭据、耐久执行、原始观测与 Docker 打包问题，见[审计](../docs/DevPilot_现状审计与修复清单.md)。

## 目标边界（待实施）

本包承担纯领域 schema、数据质量、指标/门禁、适配器、报告事实模型。业务持久化、鉴权、审批、调度与 DeerFlow 工具桥接置 backend/app；模型调用通过协议注入，不扩散对 app/harness 的反向依赖。既有 evaluation runner 和文本 judge 的惰性 deerflow import 属迁移遗留。
七字段 taskScore/codeScore 等只用于历史编码产物，不作为 CV/QA/Agent 统一验收标准。未被版本管理的 skills/custom 不属于已交付功能；领域技能需可打包、可测试、可追踪。

## 文档和测试

[总索引](../docs/README.md) · [数据/指标](../docs/DevPilot_数据集与指标规范.md) · [实施计划](../docs/DevPilot_业务流程与迭代计划.md)

仓库根目录 PowerShell：

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'devpilot/src')
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/evaluation/tests -v
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/toolkit/tests -v
~~~

本轮 47 项通过，但未运行全栈、真实模型或 Docker；新版本需求尚无完整实现。宿主 backend 通过 ../devpilot editable 引用，本包必须同时存在于镜像 builder/runtime 和开发挂载路径，当前缺口待修复。
