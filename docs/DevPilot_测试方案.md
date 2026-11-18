# DevPilot 测试方案 v3.0

## 授权 QA 配置导出回归候选（2026-11-10）

`test_authorized_qa_exports` 用合成数据/账号/key覆盖精确授权、数据 tier、全冻结源/预算、隐私、并发、重复取消读写排空、审计原子性/游标、损坏/体积；SQLite 外键 ON 和独占 PostgreSQL 迁移证明原表不变。独立 job 将纯分发 artifact/hash 交给 API 配置→新无系统依赖 venv 完整离线安装→实际已安装 `-I` CLI mock send/receipt/原 ID 对账，真实 socket/业务 imports 禁止。默认 skip 不是安装成功；完整门禁与精确 SHA CI 单独记录。[合同](DevPilot_Authorized_QA_Exports.md)。

## 报告 Agent 增补（2026-11-07）

新增报告助手测试使用完全合成资料：假模型运行真实无工具 graph；配置失败关闭、名称/自由文本/证据不外发、无重试/超时/并发槽、关闭 LangSmith tracing、坏 JSON/额外字段/工具调用/超长拒绝、权限与显式授权、事实/模板绑定、附录转义和事实不变。浏览器验证每次外发授权、人工确认附入和编辑失效。无外部真实模型、客户接口或客户报告验收，不将模拟回归当作模型质量评测。

> 2026-11-06。区分“平台软件测试”和“使用平台评测目标组件”；前者验证工具可信，后者评测业务对象，不能互相替代。

## 2026-11-07 真实材料回归要求（目标用例）

- BASELINE 无阈值可生成 INFO_ONLY 报告，不生成验收通过；ACCEPTANCE 缺批准阈值或必要参考源为阻断，不默认验收阈值。执行状态独立记录。
- 二值通过率必须能与整数计数对账；有半分/权重时输出 rubric_score 及公式，不能填入 case_pass_rate。
- 预测结构全对但没有真实值时 contract_valid 可以合格，value_verified 必须 false、数值准确性 UNAVAILABLE；不能仅凭行数和正数约束通过效果验收。
- 动态源缺快照时提示；同 case 跨 run/attempt 不扩冻结分母，不把不同数据修订合并或按运行结果过滤失败样本。
- 成功/全部/失败请求耗时与样本数独立；阈值与报告 metric_population 一致；错误/超时/截尾不静默丢失。
- 有副作用的知识更新未获压测/清理授权不得发负载；材料导入不执行上传脚本，密钥/PII 不得出现在导出和 Git。

现有工程回归见[验证记录](DevPilot_CI修复与隔离开发环境.md)，上述业务目标用例尚未全部实现。

## 1. 当前基线

2026-11-07：自定义 evaluation 15 + toolkit 58 = **73 项纯单元测试通过**，新增 26 项锁定首批分母/待审/缺指标/无成功样本/摘要回归（先观察失败再修复）。原 47 项是文档基线，未覆盖这些误判。当前已修复范围见[审计清单第 6 节](DevPilot_现状审计与修复清单.md#6-i0-首批核心判定修复2026-11-07)。前端 check 因未安装 node_modules/缺 eslint 未通过；完整后端/Docker/真实接口尚未验证，不能据此宣称正式验收。

## 2. 分层测试

| 层次       | 必测内容                                                                     | 方法                                               |
| ---------- | ---------------------------------------------------------------------------- | -------------------------------------------------- |
| 领域单元   | 分母守恒、空数据、阈值、缺指标、切片、容差、分位数、token 口径               | 无网络固定样本/性质测试                            |
| Transport  | blocking/SSE、首内容 token、坏 JSON、半包、错误码/超时、取消、usage 缺失     | httpx fake/mock server                             |
| 接入安全   | shell 注入、flags、multipart 引用、DNS rebinding、redirect、IPv4/6、CA、凭据 | parser 单测 + 受控网络集成                         |
| 数据       | 来源许可、重复/泄漏、label 冲突、PII、冻结不可变、变更失审                   | 代表性原件与恶意边界输入                           |
| 业务 API   | 身份/owner、审批、revision/idempotency、能力/参数上限、下载                  | FastAPI 测试客户端 + SQL                           |
| Job/Worker | claim/lease/fencing、重启/取消/初始化失败、重复 attempt、原子 artifact       | 故障注入、进程级测试                               |
| 导出一致性 | 干净目录/独立环境、自检、受控依赖/版本、脱敏、判定能力声明、平台同核心等价   | 假服务 golden + 固定观测/可注入时钟 + 获准真实试点 |
| 人工复核   | Q/A/expected/来源、kind/action、权限、领取/双审/仲裁、版本重算/报告          | API/并发事务 + UI 人机流程与键盘测试               |
| 前端       | 工作流、状态、表单、审批、图像与证据、事件去重                               | Rstest/DOM + Playwright                            |
| 部署       | devpilot 包、SQLite/Postgres 迁移、代理 SSE、权限、备份恢复                  | 干净 Docker 构建/集成环境                          |
| 领域验收   | 历史 QA/CV 项目与人工结论对照                                                | 冻结回放和人工审核                                 |

## 3. I0 必须先补的红灯测试

1. 全请求失败 + 仅 p95 门槛：不能 PASS。
2. 无 TTFT + 必需 TTFT 门槛：不适用在计划阶段拒绝；应可测但缺失为 BLOCKED。
3. 空样本、无阈值、负并发、NaN/Infinity、超大请求/队列：拒绝或阻断。
4. structure/reference_values/field_completeness：实际实现或入口 422，UI/capabilities 一致。
5. 非最高并发档失败、有效样本不足、重复实验某次失败：不能挑最好结果放行。
6. parser 引号内 JSON 中分号不误作 shell；真实管道/重定向/命令替换不得执行。
7. token 在列表/详情/错误/日志/报告/SSE 中均不可见；未授权内网/metadata 地址拒绝，批准内网可用。
8. 初始化抛错、取消与重启后无永远 running；旧租约持有者写结果失败。
9. Docker builder/runtime 均可 import devpilot；开发模式挂载一致。
10. 1 PASS + 1 待审不能 overall PASS；冻结分母 2，通过率 1/2。逐请求证据可重算，input/output token 不混报。

## 4. 数据与裁判验收

冻结独立人工校准集，按业务风险设误放行/误拒绝/一致性阈值；不能采用模型自报置信度代替。抽检 PASS 与 FAIL，难例/不可回答/证据冲突单列。
去重与泄漏检查按主体/来源而非仅逐行；合成集和真实集分报。检测指标使用已知小例人工核算与参考实现对照；图像增强需标注一致。
Prompt/裁判/adapter/extractor 变更均重放校准和回归，未达标准不升级。所有测试保留版本与证据，不把试点数据回流到冻结盲测后再自证提升。

## 材料构建与无预期答案执行回归（待开发）

- 多组件 manifest 的完整组件分母、附件映射、共享附件引用、页/表/行/段落定位、损坏/加密/不支持材料提示人工提取；脚本和宏不会执行，压缩包路径穿越被拒绝。
- 项目外批次按逐组件记录成功/阻断/显式排除；归档只到一个所选项目，重复提交幂等，旧项目数据和 frozen hash 不被覆盖。
- 同批次已有组件显式映射、新组件显式关联；组件不匹配的数据集即使同项目也不能进入计划。
- 无 expected 输入经冻结 RequestSpec 映射并执行，原生响应/HTTP 状态/时延及 hash 可读回；expected 不出现在目标请求里。基于 expected 的指标为 UNAVAILABLE，不阻断运行；缺少其他有效依据时 assessment 不得 PASS。
- 有 expected 时按其执行金标评估；无 expected 但冻结了规则/rubric 时可按该依据评估。没有适用依据时为 NOT_EVALUATED，缺少方案必需证据时为 BLOCKED，已建立的人工/裁判复核尚未完成时为 PENDING；不得伪造分数。
- 上传材料对模型默认不外发；授权、模型连接和数据内容 hash 不匹配时构建被阻断；提示注入内容不能改变工具权限/归档目标。

## 5. 性能度量自身的测试

性能工作台还必须按[工作台实现合同](DevPilot_AI性能测试工作台设计.md)覆盖：request count 大于样本数的稳定循环映射；warmup/measurement/drain 不混样本；request_count 与 duration first-limit 语义、硬 deadline 和取消；每 ordinal 请求/原生响应证据、重复 case iteration 标识、超限/部分 artifact 写入恢复；样本小于 p99 建议门槛时 warning 而不是伪精确结论。Summary/档位结果与逐条数据库证据的 hash 和计数必须对账。

第三方 AIPerf/GuideLLM adapter 只使用隔离 Mock OpenAI 服务，验证每个发出请求的 durable ACK、一对一 dispatch ID、冻结 case/iteration 映射、取消与未知写入不重发、响应 hash 和流式/usage 口径。没有真实单请求回调/账本桥接的 CLI 运行仅测外部对照，不能标记正式平台结果。

用可控延迟/首 chunk/usage 的本地假服务校准时间与吞吐；验证 warmup 排除、窗口/drain 边界、重试计数、非文本 N/A、chunk≠token、每档/每重复聚合。发生器负载饱和时应标注测量失真。
对 AIPerf/GuideLLM 外部 backend 先验证 workload/token/时间口径等价，不要求数值机械相同；在可解释差异前不混用报告。GenAI-Perf 已退出新功能开发，只保留历史兼容口径参考，不作为新集成候选。
真实压测必须显式 opt-in、授权窗口和硬预算，默认 CI 不访问真实组件。

## 6. 开发命令和 CI 门禁

后端遵循 backend/AGENTS.md 的 TDD：先写失败测试，后实现；完整环境下模块内 make test / make lint / make format。自定义纯包两套 unittest 必须另纳入 CI，不能以 backend/tests 已跑代替。
前端 host 命令一律经 scripts/pnpm.py，从根目录例如：

```powershell
python scripts/pnpm.py check
python scripts/pnpm.py test
python scripts/pnpm.py build
```

Runner 会在 frontend 执行；E2E 依赖按 Playwright 配置安装，并测试代理后的 SSE。未具备 Python 3.12+/uv/前端依赖时如实标“未运行”，不能为通过检查修改声明或伪造记录。

## 7. 发布完成定义

代码/测试/契约/文档同步；离线回归、容器和迁移/回退演练通过；历史项目人工验收；无已知假 PASS、凭据泄露和未授权负载；报告可从证据重建。剩余局限、试点范围和人工责任写入发布说明。

## 8. 新增调试/导出/人工复核验收矩阵

1. cURL 解析不联网；真实 shell 结构拒绝，JSON 内容内合法分号保留；不读任意本地 @file。环境替换后仍执行出站/体积校验。
2. 人与 Agent 相同 RequestSpec 渲染同请求；不同 Worker 执行域明确提示。一次调通不能绕过正式数据/计划/负载许可；变更请求/环境/credential_version/提取器会失效确认。
3. 流包含角色/心跳/空 delta/内容/usage、跨包与断流；只有有效内容开始 TTFT。代理缓冲、未启用流式、状态流、Agent 答案流分别归类，缺失不是 0。
4. 从不含本机仓库的干净 Python 3.12+ 环境安装导出包并自检；固定依赖/正确入口/完整文件齐备，缺依赖或未授权金标时生成失败或显式仅骨架，不能返回“可执行”空壳。
5. 平台/工程用同假服务与固定观测比较请求、提取、错误、N_total、分档指标、阈值和缺失语义；计时设时钟/容差。token 输入输出来源不混用。导出默认 CI 不访问真实目标，发布前另有 opt-in 受控真实验收。
6. 导出无 token/PII/绝对路径/未获准答案；语义 judge 缺失可 execute_only，但只能 NOT_EVALUATED。修改文件标 custom/unverified，hash 正确不能单独证明真实；外部 PASS 导入不覆盖原 run、不自动通过。
7. 人审详情能定位组件/版本，完整 Q/A/expected/来源、长文本和 CV 图可用；资料不足、参考答案疑错、ERROR、NOT_RUN 不可误点通过。盲审时 REST 本身不返回他人决定，而非前端隐藏。
8. 单人领取竞争、过期提交、双人独立 actor、修订冲突、重开新 round/决定与幂等重复；原证据/旧决定不覆盖，临时草稿不算已审。
9. 90 PASS+5 FAIL+5 PENDING 经人审 3 PASS/2 FAIL 后为 93/100；必需 PASS 抽检未结束时不能正式放行；抽查不代表全部 pending。性能 invalid 需补证/重跑而非手改数据。
10. 新 assessment 的计数/verdict/事件原子一致，报告锁定旧 assessment；复核变化需新报告修订/审签，不能覆写已发布件。项目 SSE 重连/双流重复事件不重复计数。

这些是新增目标用例，尚未实现/运行；不能把本节列出用例当成测试已通过。

## 报告草稿回归（2026-11-07）

核心/路由：`backend/tests/test_report_previews.py`、`test_reports_router.py`；表单/API：`frontend/tests/unit/core/reports/`；浏览器：`frontend/tests/e2e/reports.spec.ts`。覆盖严格计数/固定分母、未测量非零、流式 TTFT 与覆盖、token 来源、模板精确版本/快照与 hash、极端值校验、结构转义、认证/权限/生成身份、字段/模板变化清除旧下载、生成时锁定、错误及空目录。fixture 均为合成，禁止加入客户名称或历史指标作为回归常量。此处浏览器 mock 后端，API 使用 TestClient，不冒充真实网关/目标全栈验收；审批和持久修订尚未实现，不存在对应完成的验收。
