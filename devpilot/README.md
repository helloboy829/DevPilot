# DevPilot 定制层

本目录存放 DevPilot 基于 DeerFlow 2.0 的**研发场景垂直化定制**，与上游 DeerFlow 代码保持边界清晰。

## 目录说明

```
devpilot/
├── pyproject.toml     # 可安装包声明（便于 gateway 以 `pip install -e` 引入）
├── evaluation/        # 评测体系（7 字段 LLM-as-Judge，见 evaluation/README.md）
│   ├── judge.py       #   纯逻辑核心（零依赖）
│   ├── metrics.py     #   指标聚合
│   ├── runner.py      #   对接 deerflow 模型工厂
│   ├── cli.py         #   命令行入口
│   ├── extension.py   #   post-run 自动评测挂载点（plugins 机制）
│   └── tests/         #   15 个 unittest 用例
└── README.md
```

研发专用 Skills 放在 `skills/custom/`（DeerFlow 原生自定义技能约定），不在本目录。

## 定制范围（已确认，去掉多租户与计费）

| 模块 | 位置 | 状态 |
| --- | --- | --- |
| 研发专用 Skills（5 个） | `skills/custom/` | ✅ 已填充 Prompt（代码生成 / Bug 修复 / 测试生成 / 代码审查 / 架构评审） |
| 评测体系 | `devpilot/evaluation/` | ✅ 已实现并端到端验证（CLI + post-run 扩展挂载点） |
| 操作级审批（后续） | 待定 | 基于 DeerFlow guardrails/authz 扩展 |

## 与上游的关系

- 上游：`bytedance/deer-flow`（MIT）
- 组织方式：平铺 fork（源码直接拷贝进本仓库，不带 .git 历史）
- 定制原则：优先使用 DeerFlow 扩展机制（`skills/custom`、`plugins`、MCP、middleware），避免改动核心代码
