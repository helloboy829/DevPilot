# DevPilot 测试方案 v3.0

> 2026-11-06。区分“平台软件测试”和“使用平台评测目标组件”；前者验证工具可信，后者评测业务对象，不能互相替代。

## 1. 当前基线

2026-11-07：自定义 evaluation 15 + toolkit 58 = **73 项纯单元测试通过**，新增 26 项锁定首批分母/待审/缺指标/无成功样本/摘要回归（先观察失败再修复）。原 47 项是文档基线，未覆盖这些误判。当前已修复范围见[审计清单第 6 节](DevPilot_现状审计与修复清单.md#6-i0-首批核心判定修复2026-11-07)。前端 check 因未安装 node_modules/缺 eslint 未通过；完整后端/Docker/真实接口尚未验证，不能据此宣称正式验收。

## 2. 分层测试

| 层次 | 必测内容 | 方法 |
| --- | --- | --- |
| 领域单元 | 分母守恒、空数据、阈值、缺指标、切片、容差、分位数、token 口径 | 无网络固定样本/性质测试 |
| Transport | blocking/SSE、首内容 token、坏 JSON、半包、错误码/超时、取消、usage 缺失 | httpx fake/mock server |
| 接入安全 | shell 注入、flags、multipart 引用、DNS rebinding、redirect、IPv4/6、CA、凭据 | parser 单测 + 受控网络集成 |
| 数据 | 来源许可、重复/泄漏、label 冲突、PII、冻结不可变、变更失审 | 代表性原件与恶意边界输入 |
| 业务 API | 身份/owner、审批、revision/idempotency、能力/参数上限、下载 | FastAPI 测试客户端 + SQL |
| Job/Worker | claim/lease/fencing、重启/取消/初始化失败、重复 attempt、原子 artifact | 故障注入、进程级测试 |
| 导出一致性 | 干净目录/独立环境、自检、受控依赖/版本、脱敏、判定能力声明、平台同核心等价 | 假服务 golden + 固定观测/可注入时钟 + 获准真实试点 |
| 人工复核 | Q/A/expected/来源、kind/action、权限、领取/双审/仲裁、版本重算/报告 | API/并发事务 + UI 人机流程与键盘测试 |
| 前端 | 工作流、状态、表单、审批、图像与证据、事件去重 | Rstest/DOM + Playwright |
| 部署 | devpilot 包、SQLite/Postgres 迁移、代理 SSE、权限、备份恢复 | 干净 Docker 构建/集成环境 |
| 领域验收 | 历史 QA/CV 项目与人工结论对照 | 冻结回放和人工审核 |

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

## 5. 性能度量自身的测试

用可控延迟/首 chunk/usage 的本地假服务校准时间与吞吐；验证 warmup 排除、窗口/drain 边界、重试计数、非文本 N/A、chunk≠token、每档/每重复聚合。发生器负载饱和时应标注测量失真。
对 LLMPerf/GenAI-Perf 外部 backend 先验证 workload/token/时间口径等价，不要求数值机械相同；在可解释差异前不混用报告。
真实压测必须显式 opt-in、授权窗口和硬预算，默认 CI 不访问真实组件。

## 6. 开发命令和 CI 门禁

后端遵循 backend/AGENTS.md 的 TDD：先写失败测试，后实现；完整环境下模块内 make test / make lint / make format。自定义纯包两套 unittest 必须另纳入 CI，不能以 backend/tests 已跑代替。
前端 host 命令一律经 scripts/pnpm.py，从根目录例如：

~~~powershell
python scripts/pnpm.py check
python scripts/pnpm.py test
python scripts/pnpm.py build
~~~

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
