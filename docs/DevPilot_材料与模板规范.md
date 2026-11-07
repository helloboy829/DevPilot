# DevPilot 材料与模板规范

## 已实现切片：手工草稿而非正式报告（2026-11-07）

新增内置中英文模板 `component-evaluation-zh/en@1.0.0`，固定版本与事实/模板快照，提供 Markdown/JSON。尚不接收 DOCX/XLSX 模板上传、不支持模板编辑、正式审批或服务端历史保存。手工事实必须标注未核验，不因模板排版生成正式验收结论。模板更新另发版本，旧版不覆盖；后续模板生命周期与映射见 [报告模块设计](DevPilot_报告模块设计.md)。


> 2026-11-06；目标交换规范 v1.0，**当前尚无完整模板导入/渲染器**。示例是脱敏设计样例，不可直接对外发压测。

## 2026-11-07 真实材料导入补充

清单导入保留组件版本、功能层级/需求映射、模型/算力、字段说明、原始来源及每组件门槛/负载；序号不连续不代表缺组件，按有效组件记录计数。先预览映射与缺项，绝不导入即调用。跳过 Office 的 ~$ 临时锁文件，不当作损坏业务文件。

将请求样例、候选预期、已审金标、参考模板和运行结果明确分开；同一数据的不同修订不相加算独立样本。金标模板空值必须显示“待补齐”。原始文件先隔离/扫描、脱敏并登记权限，不执行上传脚本；凭据转 credential_ref，不进 Git/模型上下文/脚本导出。

正式报告模板增 evaluation_mode、指标公式/人群、冻结分母、阈值批准记录、环境/拓扑/模型映射、运行参数、证据清单和签审。BASELINE 显示“摸底，仅供参考，不构成验收结论”；加权评分不可自动写进二值准确率栏。审批时自动对账摘要、表格、指标和逐条证据。

参见[材料分析](DevPilot_历史材料分析与设计校准.md)，原件只保存在本地授权资料区。

## 1. 提测清单

Excel/CSV 建议一个组件版本一行，复杂样例和附件另表/文件并用 ID 引用：

| 字段 | 要求 |
| --- | --- |
| 项目/组件名称、业务负责人 | 必填；责任方与联系方式按隐私策略 |
| component_kind | model / agent，和任务类型分开 |
| model_family / task_type | 如 llm / qa，cv / image_classification；支持范围按 capabilities |
| supplier_version、部署指纹 | 必填或明确 unknown，未知时限制验收结论 |
| 完整 cURL | 原件隔离；解析预览/脱敏；不能直接交 shell |
| 凭据 | 经专门渠道登记 credential_ref，不写报告/常规表格 |
| 输入/输出样例 | 成功/错误/流式片段；附件 ID/hash；样例不等于金标 |
| 参考来源 | 原件、版本、授权/用途、可定位证据、敏感级别 |
| 预期与验收口径 | 合理答案、容差、拒答、错误预算和关键切片 |
| 负载许可 | 允许目标、并发/请求/时长、时间窗、费用和停止联系人 |
| 限制 | 是否副作用/会话、网络/证书、签名、异步、输入大小 |

表头：[submission-template.csv](templates/submission-template.csv)（UTF-8 BOM，便于 Excel 打开）；结构化样例：[submission.example.json](templates/submission.example.json)。导入必须先预览确认；错误到文件/行/字段，合法字段不因一行错误全部丢失。原始 cURL 的密钥应提取转存或要求替换，普通下载仅提供脱敏版本。

## 2. 数据交换

一条 case 一行 JSONL，[dataset.example.jsonl](templates/dataset.example.jsonl)；图像、文档用受控 artifact ID，不接受任意本地绝对路径或隐式远程下载。
字段定义见[数据集规范](DevPilot_数据集与指标规范.md)。source_refs 必须指向已授权来源；expected/rubric 由裁判读取，不传目标。验收集 split=acceptance，synthetic 仍需审核。

## 3. 方案配置

[plan.example.json](templates/plan.example.json) 示意固定数据、请求修订、效果/性能负载与门槛。阈值只演示格式，不是适用于全部组件的推荐值；实际数值、最小样本、重复次数由评审确定。
config 不能包含凭据明文、任意 Python/shell 或禁用 TLS 的用户选项。变更产生新 revision；执行只引用冻结计划，不能带临时 params 覆盖。

## 4. 报告事实模型与模板映射

以[report-template.md](templates/report-template.md)作基础结构；收到真实 DOCX/XLSX 模板后，建立“模板占位符→事实模型路径→格式→必需性”映射并做样张比对。
必须包括：被测对象/版本、范围/来源与授权、数据质量、方案和阈值、环境、分母、效果/切片/争议、各负载档性能、token/时间口径、缺失/不适用、错误、整改/复测、结论与审批、证据索引/局限。

- 不通过和阻断也可生成评测记录，不得包装成通过报告。
- 数值/表格由程序输出，解释可由 LLM 草拟并引用证据。
- 缺必填事实模板校验失败，不能模型补写。
- 先结构化 JSON + 可读报告，再按实际需求适配 DOCX/XLSX/PDF；依赖存在不代表功能完成。

## 5. 整改与知识交换

[remediation-template.md](templates/remediation-template.md)记录问题、影响切片、证据、责任人、修复版本、基准和复测范围。
历史材料导入先脱敏和授权确认，再结构化映射与人工审核。供“学习”的是经审查知识和规则版本，不是把原件无差别发送外部模型。

## 6. 调试、导出与人工复核交换材料

- [RequestSpec 示例](templates/request-spec.example.json)展示请求/环境/输入绑定/内容流规则，和原 cURL 同存脱敏引用；原始 secret 不进入普通文档。调试检查、Confirmation 的 hash/环境/版本与批准范围进入证据包。
- [导出请求示例](templates/script-export-request.example.json)只是目标设计，不是当前可下载执行的脚本。真正工程须包含 runner、锁定核心/依赖、配置、获准数据、README、无秘密的 .env.example、自检、manifest/hash 和统一结果格式。分别声明骨架/可执行/execute_only，金标与 input 分授权。
- [人工复核示例](templates/review-decision.example.json)包含 assignment/revision/subject hash、动作、理由、证据；人从登录身份确定。导出复核记录不默认夹带全部敏感 Q/A 或盲测答案。
- 报告事实模型增加 required_review_open_count、review_policy/coverage、decision/resolution_refs、run_assessment_refs、来源为 platform/external 及信任标识；已发布件不能随复核重算原地变化。

三类 JSON 是待实现契约的格式说明，example_only/notes/占位 hash 不属于正式提交字段。具体 schema/version 在实现 PR 发布，不能仅通过 JSON 语法就宣称业务可执行。
