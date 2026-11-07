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
| F01 / P0 | **核心已修复（2026-11-07）**：全失败/零请求/无有效窗口不能 PASS，必需 p95 缺失不再跳过；见新增回归 | Gateway/真实负载与更完整有效性验收仍待完成 |
| F02 / P0 | **缺证据门禁已修复（2026-11-07）**：必需 TTFT 缺失、无效或覆盖成功请求不全时 FAIL；无阈值不要求 TTFT | 能力适用性、NOT_APPLICABLE/UNAVAILABLE 状态、缓冲检测与方案阶段拒绝仍待实现 |
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
| F13 / P0 | **核心已修复（2026-11-07）**：1 passed + 1 manual_review → pass_rate=1/2、overall=REVIEW；保留 auto_pass_rate 仅作诊断；缺结果记 not_run | 当前按传入 samples 固定分母，数据库冻结版本/正式人审与目标 NEEDS_REVIEW 生命周期仍待实现 |
| F14 / P0 | **静态发现**：PerfLevelResult 仅聚合，service 将 levels 写 raw.json，未持久化逐请求 PerfSample；TPS 使用 total_tokens（可含输入）且混合估算来源 | 保存每请求 timing/attempt/token 来源与输入输出分开；补 mean；指标离线重算/报告不可冒充纯输出 TPS |

复现摘要：
- F01：success_rate=0，p95 缺失，criteria={perf:{p95_latency_max_ms:100}} → 旧逻辑 PASS。
- F02：success_rate=1，ttft_p95_ms=None，criteria={perf:{success_rate_min:1,ttft_p95_max_ms:10}} → 旧逻辑 PASS。
- F03：validation_type=structure → unsupported validation。
- F13：两条数据一条 passed、一条 manual_review → 旧逻辑 PASS / 自动通过率 100%；新版主通过率应为 1/2 且待复核。

## 3. 文档基线验证范围（2026-11-06）

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

## 6. I0 首批核心判定修复（2026-11-07）

已按“先红灯、后实现”修复 F01、F13 的核心判定及 F02 的缺证据门禁，并扩展相邻回归：

- 效果主通过率固定为 passed/total；待审、错误、未执行保留。传入 samples 时不允许结果静默扩充分母；结果不足时逐项 not_run。未提供 samples 的 legacy 调用仍按 results 数量处理，不冒充正式冻结。
- manual_review 先检查目标调用错误；error 不能转成人工语义待审。成功的待审样本保留 actual/reference。
- 性能配置的延迟/TTFT 阈值不可因值为 None 而省略；非有限/负测量和缺覆盖不能放行。增加 latency_sample_count/ttft_sample_count 与 check_reasons；非流式未配 TTFT 时不要求其有值。阈值拒绝 NaN/Inf/负数，成功率范围为 0–1，判定以准确计数而非四舍五入比例为准。
- 报告摘要缺所需报告时 REVIEW；FAIL 优先，待审不被改成 PASS/FAIL。新增主通过率/分母/错误/未执行和性能失败原因。新报告与摘要标 assessment_version=component-test.i0.v1；不回写旧报告。前端仅同步兼容类型，未重做页面。

验证：本地 Python 3.9.12，evaluation 15 + toolkit 58 = **73 项纯单测通过**，比原基线新增 26 项；用例包含 transport/LLM mock，不调用真实目标/模型。修改的 6 个 Python 文件经 Ruff 0.14.11 按 backend/ruff.toml 检查与格式校验通过。前端按规定运行 python scripts/pnpm.py check，但因 frontend/node_modules 不存在、缺 eslint 未通过；本机 Node.js 20.19.5 也低于项目要求 22+。

补充文档检查：修改文件未发现疑似密钥，模板 JSON/JSONL 可解析，Git 空白检查通过；75 处本地链接引用无新增断链。backend/AGENTS.md 中另有 19 处提交前已存在的上游文档缺失引用，已识别为遗留导航问题，后续按实际保留模块整理，不创建空壳文档冒充实现。

**本节执行时尚未完成（后续环境与离线回归进展见第 7 节）**：完整 Python 3.12+/uv 环境、Gateway/前端/容器/真实接口验收；流式能力/缓冲有效性验证；裁判校准/更完整 schema 校验；安全、持久化与 F03–F09/F14。原型仍按最高并发档验收，吞吐仍可能含输入 token，raw 仍非逐请求采样。I0 仅完成首个切片，不代表正式可用或整体安全。

## 7. CI 与材料校准（2026-11-07）

已建立独立 Python 3.12 / Node 22 / 锁定 pnpm 的 Docker 验证环境，完成本地后端完整回归（含隔离 PostgreSQL/Redis）。修复失效文档/迁移 head 测试、恢复中英文文档路由、清理前端格式问题、隔离单测 DNS；make test 已纳入 73 项 DevPilot 核心回归（F11 测试入口部分已修复）。完整结果与跳过/抖动见[CI 验证记录](DevPilot_CI修复与隔离开发环境.md)，不代表生产 Docker 打包已验收。

已本地分析授权历史材料，新增[脱敏材料分析](DevPilot_历史材料分析与设计校准.md)，同步摸底/验收、金标/结构验证、加权评分、动态快照和耗时人群目标契约。业务新字段/新 UI 未实现，既有安全/耐久任务/生产打包问题仍未全部修复。

## 8. 报告草稿最小切片（2026-11-07）

新增 `devpilot.reporting`、Gateway `/api/reports/templates`/`preview`、`/workspace/reports` 页面及独立合成回归。支持人工填写对象/版本/效果/性能/证据，固定模板版本生成 DRAFT 并下载 Markdown/JSON；保留待审/未跑分母、指标缺失/统计人群/流式适用性和模板/事实快照。无模型/目标调用、无自动验收结论、无服务端存档、无审批或模板上传。既有 P0 安全/耐久/生产打包门禁仍须后续完成，不把本切片当作 I0 退出。详见 [报告设计](DevPilot_报告模块设计.md)。

完整回归中另外复现 browser URL 安全单测依赖真实 GitHub DNS，已只 stub 解析结果，保留生产 SSRF 逻辑与私网/非 HTTP 拒绝，新增无法解析/私网 DNS 回归。报告浏览器首轮两个失败来自通用 alert 选择器命中 Next 路由 announcer，改为按实际错误文本定位，未跳过错误断言；其余抖动及最终结果见 [验证记录](DevPilot_CI修复与隔离开发环境.md)。
