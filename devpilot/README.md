# DevPilot 领域定制层

## 显式本地执行命令（2026-11-10）

`python -m devpilot.local_qa_cli` 默认仅离线预检，使用独立 manifest、敏感 bindings 和 input-only 文件。实发必须单独确认结构 fingerprint、输入使用及**私有明文输出**，并显式配置 host allowlist、新目录；完整复用共享 run/collector/TLS 固定传输和一次性 SQLite journal。每次发送前检查全部 DNS answers，未知结果/策略拒绝停止后续 ordinal，不恢复或重发。结果仅 external/unverified technical / NOT_EVALUATED，不是平台证据/批准；不是平台授权 exporter 或完整锁定依赖发行包。合成验证无真实目标调用，无 App/API/依赖/迁移/部署或配置改变。见[合同与离线示例](../docs/DevPilot_Local_QA_Command.md)。

> 2026-11-06。定位从通用研发定制调整为 AI 组件评测；以下严格区分当前代码与目标。

## 共享有界单次采集（2026-11-10）

`qa_json_attempt.py` 固定 `qa-json-attempt.v1`，共享实际单次收集的 deadline、流读取、分类、敏感内部观测与关闭流程。必传 client factory，无默认网络/凭据能力；App 仍提供动态 policy，并持有准入、dispatch-before-I/O、运行预算、证据与未知结果不重发权。复用已有 HTTPX，不是无 site packages 核心；单次可导入不等于完整独立 runner/export、执行许可或批准。见[合同与验证](../docs/DevPilot_Shared_QA_JSON_Attempt_Core.md)。

## 共享响应核心（2026-11-10）

`qa_json_response.py` 固定 `qa-json-response.v1` 的纯 bounded HTTP JSON 响应分类/缓冲/提取；App 有界 QA 采集已共用此实现，保留 transport、准入、派发和未知结果不重发语义。只在正常响应结束后提取，结果仍为敏感内部值，不是 verdict 或公共 DTO。标准库隔离解释器及实际 wheel 验证不意味着完整包零依赖或独立执行工程已完成；没有新 API、依赖/迁移、执行开启或部署。见[合同与验证](../docs/DevPilot_Shared_QA_JSON_Response_Core.md)。

## 共享请求准备核心（2026-11-10）

`qa_json_request.py` 固定 `qa-json-request.v1` 的不可变发送值投影；App 已共用原样请求/条件 identity header 准备。保留重复/显式 headers 与 64→65 派生边界，body 编码仍在原 attempt deadline 内。无渲染、发送、授权或凭据解析；不是公共导出 DTO/完整 runner。见[合同与验证](../docs/DevPilot_Shared_QA_JSON_Request_Core.md)。

## 共享固定目的地传输（2026-11-10）

`pinned_http.py` 固定 `pinned-http.v1` 的实际 HTTPX origin/Host/SNI/TLS/零重试机制，App 已共用；显式 resolver callback 仍由 App 执行 allowlist 与 ALL DNS answers 检查。拒绝会触发二次 DNS 的非 literal/scoped 返回值；错误/取消/关闭不重试。此层需要已存在的 HTTPX 依赖，不是无 site packages 的纯核心，也不是独立执行/导出授权。见[合同与验证](../docs/DevPilot_Shared_Pinned_HTTP_Core.md)。

## 当前结构

```text
devpilot/
├── pyproject.toml
└── src/devpilot/
    ├── toolkit/       # effect/perf/transports/report，初版组件测试
    │   └── tests/     # 58 个纯单元测试
    └── evaluation/    # legacy：代码产物七字段 LLM-as-Judge
        └── tests/     # 15 个纯单元测试
```

Gateway 的 `backend/app/component_tests/service.py` 调用 toolkit；不是已经由 Lead Agent 自动完成端到端评测。
当前基础文本判定与阶梯负载可复用，首批固定分母和缺指标门禁已修复；仍有裁判/能力验证、TLS/凭据、耐久执行、原始观测与 Docker 打包问题，见[审计](../docs/DevPilot_现状审计与修复清单.md)。

## 目标边界（待实施）

本包承担纯领域 schema、数据质量、指标/门禁、适配器、报告事实模型。业务持久化、鉴权、审批、调度与 DeerFlow 工具桥接置 backend/app；模型调用通过协议注入，不扩散对 app/harness 的反向依赖。既有 evaluation runner 和文本 judge 的惰性 deerflow import 属迁移遗留。
七字段 taskScore/codeScore 等只用于历史编码产物，不作为 CV/QA/Agent 统一验收标准。未被版本管理的 skills/custom 不属于已交付功能；领域技能需可打包、可测试、可追踪。

## 文档和测试

[总索引](../docs/README.md) · [数据/指标](../docs/DevPilot_数据集与指标规范.md) · [实施计划](../docs/DevPilot_业务流程与迭代计划.md)

仓库根目录 PowerShell：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'devpilot/src')
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/evaluation/tests -v
python -B -X utf8 -m unittest discover -s devpilot/src/devpilot/toolkit/tests -v
```

2026-11-07 共 73 项通过，但未运行全栈、真实模型或 Docker；新版本需求尚无完整实现。宿主 backend 通过 ../devpilot editable 引用，本包必须同时存在于镜像 builder/runtime 和开发挂载路径，当前缺口待修复。

## I0 首批核心修复（2026-11-07）

- `EffectReport.pass_rate` 是主通过率，分母包含 manual_review/error/not_run；`auto_pass_rate` 保留为诊断项，不能放行。传入 samples 时以其长度为分母，缺结果显式 not_run，多余结果拒绝；这不是已落库的冻结数据集功能。
- 目标调用失败先记 error，不能转为人工语义待审。manual_review 保留实际输出和参考文本，尚无人工决策服务。
- 性能无请求/无成功/无有效时间窗不能 PASS；配置的 p95/TTFT 门槛必须存在且覆盖所有成功请求，未配置 TTFT 不要求其有值。`check_reasons` 说明失败原因。非有限/负阈值拒绝，成功率用准确计数判定。
- 新 JSON 报告和摘要带 `assessment_version=component-test.i0.v1`；旧 JSON 不改写。缺报告为 REVIEW，已知 FAIL 优先，其余待审不会被摘要改成 PASS。
- `latency_sample_count`/`ttft_sample_count` 仅是有效观测数，不等同于已经验证的流式能力/缓冲检测；不能据此声称满足全部目标 TTFT 规范。当前最高并发档验收、总 token 吞吐及仅聚合落盘仍属原型限制。

## 共享完整 run 编排 / Complete bounded run orchestration（2026-11-10）

`devpilot.qa_json_run` 的 `qa-json-run.v1` 由平台 Worker 实际共用，显式传入 clock/reserve/collect/record/check-active 能力。顺序为 input-only off-loop render → durable dispatch ACK → 余量检查 → 单次 collect → record；unknown 先停发，consumer/monitor/group 排空后 App finish。严格次数/并发/deadline 不替代 App 的授权/全局和整 run 字节预算。无默认客户端/凭据/DB/金标读取，无重试，不是授权 exporter/CLI。见[合同与门禁](../docs/DevPilot_Shared_QA_JSON_Run_Core.md)。

## 独立本地 run 耐久适配（2026-11-10）

`local_json_run` 复用真实 `qa_json_run`，为未来独立 CLI 提供私有 WAL/FULL SQLite 单 run journal、commit-before-collect、每 ordinal 一次、累计预算不回收与取消读写排空。仅保留无事务 idle WAL anchor，最终排空后 close/撤销 claim；重开只读，不续跑/重发；显式 collector/output/policy capabilities，不提供默认客户端或平台证据。source hash 仅声明，不是值/来源认证，collected 不是 PASS。见[合同与门禁](../docs/DevPilot_Local_QA_Run_Journal.md)。
