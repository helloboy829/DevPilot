# DevPilot 现状审计与修复清单

> 2026-11-06，本地代码基线。本轮只更新文档，以下运行时问题**尚未修复**。

## 1. 已存在的能力

| 模块 | 路径 | 边界 |
| --- | --- | --- |
| 对象/运行 API | backend/app/gateway/routers/component_tests.py | CRUD、effect/perf、历史/JSON 报告，非完整项目流程 |
| 后台调用 | backend/app/component_tests/service.py | asyncio 任务和每进程 semaphore，非耐久队列 |
| 核心工具 | devpilot/src/devpilot/toolkit/ | HTTP/OpenAI/Dify 四 transport、基础效果、阶梯压测、JSON |
| 存储 | backend/packages/harness/deerflow/persistence/component_tests/ | component_tests / component_test_runs，非数据治理模型 |
| 页面 | frontend/src/app/workspace/component-tests/page.tsx | 聊天工作台中的表单/JSON 页 |
| 旧评分 | devpilot/src/devpilot/evaluation/ | 代码产物七字段 judge/CLI/post-run，非通用模型评分 |
| 底座 | backend/app/、backend/packages/harness/、frontend/ | Gateway/Agent/沙箱/鉴权/聊天，非领域闭环 |

未发现已接通的模板导入、类 Postman 调试/接入确认、独立测试工程导出、完整人工复核中心、数据生成审核、冻结验收集、业务审批、正式报告模板、整改工单与受控知识推广闭环。现组件测试直接调 toolkit，不是 Lead Agent 自动编排。

## 2. 修复清单与退出条件

| ID / 优先级 | 证据与问题 | 修复与回归要求 |
| --- | --- | --- |
| F01 / P0 | **已复现**：perf_eval 对全失败且只配 p95 阈值返回 PASS；默认成功率下限 0，缺指标跳过 | 明确最小成功数、成功率门槛；缺必需指标 BLOCKED；每个必测档验收，不只取最高档 |
| F02 / P0 | **已复现**：成功但缺 TTFT，配置 TTFT 阈值仍 PASS | 适用性与可用性分离；方案拒绝不适用阈值，运行缺证据阻断 |
| F03 / P0 | **已复现**：API/前端接收 structure/reference_values/field_completeness，effect_eval 不支持 | 实现并测试或入口 422/隐藏；能力声明一致 |
| F04 / P0 | **静态发现**：backend 依赖 ../devpilot；Dockerfile 构建/运行未拷贝包 | builder/runtime/开发挂载一致；干净构建和容器 import；本轮未实际构建 |
| F05 / P0 | **静态发现**：service/transports 显式 verify=False，URL 仅非空检查 | TLS 默认校验/信任 CA；SSRF、DNS、重定向策略；不简单封掉内网 |
| F06 / P0 | **静态发现**：ORM api_token 为明文 Text，通用 to_dict 返回映射字段 | credential_ref、存储加密、DTO 排除；所有响应/日志/报告泄密回归；未声称跨用户攻击已证实 |
| F07 / P0 | **静态发现**：params 任意字典无统一上限，create_task 无界排队 | 强类型限额、全局/用户配额、429、负载许可；拒绝 NaN/负值/超大值 |
| F08 / P0 | **静态发现**：无 durable claim/lease/restart recovery | 耐久任务/租约/心跳；效果恢复与性能重新开窗分离 |
| F09 / P0 | **静态发现**：配置/client 在 try 外；取消无专门终态处理 | 覆盖初始化/配置异常、取消与资源释放，不遗留 running |
| F10 / P1 | **静态发现**：仅 JSON；有 openpyxl 不等于已有 Excel 报告 | 模板版本/证据/审批/脱敏，按用户真实模板适配 |
| F11 / P1 | **静态发现**：toolkit 测试未显式纳入 backend 默认目录，未找到该域专属服务/前端测试 | CI 纳入；补 API、owner、恢复、前端与 E2E |
| F12 / P0 文档 | 旧 README 为 SaaS/九 Agent/Milvus；声称五个研发 Skills 已交付但 tracked 文件缺失 | 本轮更新文档与路径；历史 live 声明不是当前验证 |
| F13 / P0 | **已复现**：_build_effect_report 对 1 passed + 1 manual_review 输出 auto_pass_rate=1、overall=PASS；待审被移出分母 | 新主通过率以冻结 N_total 为分母；待审为 NEEDS_REVIEW；旧 auto_pass_rate 仅作辅助且不能放行 |
| F14 / P0 | **静态发现**：PerfLevelResult 仅聚合，service 将 levels 写 raw.json，未持久化逐请求 PerfSample；TPS 使用 total_tokens（可含输入）且混合估算来源 | 保存每请求 timing/attempt/token 来源与输入输出分开；补 mean；指标离线重算/报告不可冒充纯输出 TPS |

复现摘要：
- F01：success_rate=0，p95 缺失，criteria={perf:{p95_latency_max_ms:100}} → 旧逻辑 PASS。
- F02：success_rate=1，ttft_p95_ms=None，criteria={perf:{success_rate_min:1,ttft_p95_max_ms:10}} → 旧逻辑 PASS。
- F03：validation_type=structure → unsupported validation。
- F13：两条数据一条 passed、一条 manual_review → 旧逻辑 PASS / 自动通过率 100%；新版主通过率应为 1/2 且待复核。

## 3. 验证范围

本地 Python 3.9.12；项目要求 3.12+；未发现 uv、backend/.venv、frontend/node_modules、config.yaml、extensions_config.json。
自定义纯逻辑 unittest 已验证 **47 项通过（15 evaluation + 32 toolkit）**，不覆盖上述误判，也不是 Gateway/前端/部署验收。

根目录 PowerShell：

~~~powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'devpilot/src')
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/evaluation/tests -v
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/toolkit/tests -v
~~~

未运行完整后端、前端、Docker、真实接口或全链路。旧 M1–M5 完成记录不可替代当前证据。

## 4. 修复原则

先复现测试，后代码；存在假 PASS 和安全缺口时不先扩大自动生成/压测。兼容旧 API，但新运行收紧验证。旧结果标 legacy/unverified，不自动升级为新版 PASS。每项修复附测试、文档和验收证据。

## 5. 最新意见的文档增量与验证（2026-11-06）

已补充接口调试/接入确认 → 共享核心平台执行/独立导出、人工复核中心+结果内嵌、Decision/Resolution/Assessment 分层，并同步 API/表/事件/迭代/验收与设计样例。清理日/法/俄 README 并修复中英入口，未删除运行时模块或 UI locale；全仓搜索仍命中历史 demo 对话里的旧上游路径，保留这些历史快照，不将其视为现行导航。

- 文档检查：27 个 Markdown、97 个本地链接、3 个 JSON 围栏、5 个 JSON 文件、2 条 JSONL、20 列 UTF-8 BOM CSV，未发现断链/语法/编码错误；RequestSpec 的 input.question 与数据样例绑定一致。
- 重新运行 evaluation 15 + toolkit 32 = **47 项既有纯单测通过**；git diff --check 通过。旧单测包含旧口径断言，不代表本清单 P0 已解决。
- 本次未改运行时代码、未实现新增 API/页面/独立 runner，也未运行完整后端/前端/容器/真实目标；上述新验收用例仍待开发。
