# DevPilot 文档导航旧快照（2026-11）

> 历史归档：当前导航由 [docs/README.md](README.md) 维护。以下日期段落保留整理前的模块说明和引用，不作为当前交付、路线或状态来源；合同/历史收据不因整理而删除。

## 先看这里

- [当前能力、运行状态与缺口](DevPilot_Delivery_Status.md)
- [数据理解与 QA 数据构建待开发范围](DevPilot_数据集与指标规范.md)
- [评测数据构建与执行工作流（目标合同）](DevPilot_评测数据构建工作流.md)
- [效果测试工作台与逐条响应证据](DevPilot_效果测试工作台设计.md)
- [AI 性能测试工作台与工具集成决策](DevPilot_AI性能测试工作台设计.md)
- [模块实现进度与重构路线](DevPilot_实现进度与下一步.md)
- [全民审核规则与 Linux 验收接续](DevPilot_Equal_Review_and_Linux_Acceptance.md)
- [候选验收包与检查清单](DevPilot_Acceptance_Package.md)
- [Windows 验收 Runbook](DevPilot_Windows_Acceptance.md)
- [两周冲刺建议与迁移风险](DevPilot_Sprint_Plan.md)
- [逐轮交付历史与验证收据](DevPilot_Delivery_History.md)
- [根开发指南](../AGENTS.md) / [后端开发指南](../backend/AGENTS.md) / [前端开发指南](../frontend/AGENTS.md)

以下日期段落保留各模块原始范围；后续实现、当前验证与部署状态以上述入口为准。

## 文档维护与权威来源

- 当前代码/部署/候选/验证事实只以[交付状态](DevPilot_Delivery_Status.md)为准；模块级待办/实施顺序/验收状态只以[实现进度](DevPilot_实现进度与下一步.md)为准。
- 领域规则由单一规范拥有：数据与 verdict 见[数据集与指标规范](DevPilot_数据集与指标规范.md)，数据生命周期见[数据构建工作流](DevPilot_评测数据构建工作流.md)，逐条结果访问见[效果工作台](DevPilot_效果测试工作台设计.md)，性能负载/指标/工具见[性能工作台](DevPilot_AI性能测试工作台设计.md)，API 与 schema 由相应契约文件细化。
- [业务流程与迭代计划](DevPilot_业务流程与迭代计划.md)维护产品迭代 backlog；需求分析只维护 FR/验收要求；开发计划和冲刺文件保留历史排期/建议，不得各自复制当前实现状态。
- [交付历史](DevPilot_Delivery_History.md)、带日期的 CI/模块收据、`docs/reviews/` 和 `docs/upstream/` 是历史证据或上游来源，不作为当前状态入口。不得因重复摘要删除真实失败、CI、迁移和回滚证据。
- 整理文档时优先删除重复的“当前状态”段并改为链接；除确认未引用、非合同、非许可证、非证据的废弃草稿外，不批量删除文件。模块合同若被新版本替代，应保留历史并写清 superseded-by 与版本边界。

当前数据能力限于人工 JSON/JSONL 导入、结构校验、自审冻结，以及将冻结数据版本绑定到 QA 计划/执行候选。项目外材料批次、多组件候选构建、项目归档、组件适用范围校验和无参考答案用例执行均为待开发目标；详见[评测数据构建与执行工作流](DevPilot_评测数据构建工作流.md)、[数据集与指标规范](DevPilot_数据集与指标规范.md)及[当前交付状态](DevPilot_Delivery_Status.md)。

## 2026-11-15：QA 调度准入只读诊断（候选，未部署）

[固定拒绝投影](DevPilot_Scheduling_Admission.md)：管理员显式权限读取 `qa-scheduling-admission.v1`，明确 legacy scheduler 仅覆盖 component tests、QA 链未准入；恒不授权调度/释放/重试，固定 blockers，无 DB/配置/证据读取。运维工作台提供独立的管理员显式点击只读展示（有界严格校验、无重试或调度控件）。

## 2026-11-15：本地 QA 目录残留清单（候选，未接入 App）

[固定文件名、仅元数据](DevPilot_Local_QA_Directory_Residue.md)：`python -m devpilot.local_qa_residue inventory` 只报告已知文件名是否存在及大小/修改时间；不读内容、不发现其他文件、不删除，明文副本与崩溃产物仍需独立人工处置。

## 2026-11-15：多级签核要求纯核心（候选，App 咨询接入）

[显式策略下的技术判定](DevPilot_Signoff_Requirement_Core.md)：`evaluate_signoff_requirement` 只根据调用方给出的所需不同审批人数、已批准人数与最新决定返回 satisfied/固定 blockers；纯核心不存储策略、不强制、不读取批准文档。App 签署进度可从追加式项目咨询策略读取阈值，显式查询参数优先，附加咨询性 requirement；结果不是批准或授权。

## 2026-11-15：离线技术指标 CLI（候选，未接入 App）

[本地 JSON 投影命令](DevPilot_Offline_Metrics_CLI.md)：`python -m devpilot.qa_metrics_cli` 显式读取有界普通文件，输出 TTFT/吞吐、裁判校准、图像差异或多级签核要求固定投影；拒绝符号链接/超限/未知字段，缺失值保持 `null`，无网络/模型/证据读取，结果不是 PASS 或批准。

## 2026-11-15：CV 图像差异纯核心（候选，未接入 App）

[整数像素差异统计](DevPilot_CV_Metrics.md)：`devpilot.qa_cv_metrics` 只比较等尺寸整数像素矩阵，输出 changed/ratio/MAE/max 与 identical/within_threshold；不解码、不访问网络、不调用模型，也不是质量或批准。

## 2026-11-15：模型裁判校准纯核心（候选，未接入 App）

[人工/裁判一致性统计](DevPilot_Judge_Calibration.md)：`devpilot.qa_judge_calibration` 只统计双方确定的 pass/fail 配对；缺失/uncertain 显式排除，无确定配对时 `insufficient` 且数值为 null，绝不填零或当作批准。未接入 App，无模型调用。

## 2026-11-15：流式指标纯核心（候选，未接入 App）

[TTFT/内容吞吐投影](DevPilot_Streaming_Metrics.md)：`devpilot.qa_stream_metrics` 对单次可观测流输出固定技术投影；缺失/不可观测/不适用显式 `unavailable`/`not_applicable`，绝不填零，也不代表 PASS 或批准。未接入 App 证据/API/UI，无模型调用。

## 2026-11-15：Lost Worker 安全合同（候选，未部署）

[只读分类与明确阻塞](DevPilot_Execution_Safety_Contract.md)：`execution_safety.classify_held_reservation` 对单行占用给出固定技术投影；deadline、队列与终态都不证明 Worker 死亡，恒不授权 release/reclaim/requeue/retry/resend/dispatch；类型伪装、未知状态与不一致行失败关闭。回归锁定调度器与正式批准不能导入/触发执行仓库，运维路由只有聚合 GET。没有新 API、迁移、UI、后台清理器或配额处置。

## 2026-11-15：正式批准首切片（候选，未部署）

[显式人类批准、职责分离与撤销审计](DevPilot_Formal_Approval.md)：`eval_0015` 在不可变独立评估之上追加具名审批人的 `approved`/`revoked` 修订，固定 assessment revision/hash 与 ALL 分母；要求采集完成、独立复核完整、冻结阈值（若定义）达标，且审批人账号须已存在并完成初始化、不得是 owner 或该 run 任一盲审/仲裁人（预检以 `approver_account_not_found` 阻塞）。撤销须附理由并追加审计；另有只读预检、项目级最新 revision 索引、有序审计列表、运行级与项目级链完整性校验、签署进度聚合（仅元数据，不授权），以及数据集页内嵌的批准面板（显式加载/预检/创建/撤销/链完整性/签署进度，未知写只按原 ID 对账）。`eval_0016` 另存项目级咨询性签核政策（append-only、仅 owner 显式、不强制）。只有 owner 记录、没有审批人专属登录、强制多级签核、通知或导出权限；阈值达标与 case PASS 都不产生批准。

## 2026-11-14：候选 SQLite 升级与恢复演练

[合成版本矩阵、WAL 备份与独立还原](DevPilot_Candidate_Upgrade_Recovery.md)：真实 Harness/App 迁移、39 张旧表全部行/schema、账号、历史密文和报告/复测/Word；逐级或直接升级到 53 张表（`eval_0015` 加入正式批准两表；后续 `eval_0016` 增至 54），注入提交后结果丢失并从旧备份恢复到新路径。只复制主数据库会漏 WAL；恢复旧备份会丢弃之后的新写。不操作业务库，不等于部署、PostgreSQL 原生恢复、Windows 或正式批准验收。

## 2026-11-14：本地保留管理命令

[显式检查、到期处置与原 ID 对账](DevPilot_Local_QA_Retention_Commands.md)：复用输出前 durable receipt 和真实锁/文件 API；处置需 operator 原 disposal UUID、两个 hash 及单独同意。无 key/解密/执行/自动删除，不把未认证 metadata 或文件缺失当作来源、PASS、安全擦除或批准；plaintext 副本治理和 Windows 实际验收仍独立进行。

## 2026-11-11：本地 QA 加密输出与保留候选

[独立输出保护 / Protected local output](DevPilot_Local_QA_Protected_Output.md)：显式 operator key、分离同意、完整认证链、同 descriptor 持锁打开、到期精确一次删除和原 ID 只读对账。v2 软件分发含 12 个锁定运行依赖；不等于平台证据、正式批准或部署，半写输出保留治理仍待完成。

[外部 QA 技术隔离接收工作台 / External QA quarantine workspace](DevPilot_External_QA_Quarantine_Workspace.md)：显式历史来源、两份有界技术文件、三确认、原 ID GET-only 对账与字面审计；本轮本地门禁通过（前端 1,359 / 后端 13,334 / Chromium 242 / auth recovery 2），源码/资源/提交/精确 SHA CI 分别核验；不接纳敏感证据、不授予执行或批准。

## 当前追加：外部 QA 技术元数据持久隔离接收（2026-11-11）

[独立授权、历史来源与不可变技术档案](DevPilot_External_QA_Quarantine.md)：两份有界声明、三项精确确认、完整 baseline 历史导出与冻结 plan 对齐、ALL 总体/预算、canonical 与原始声明 hash 区分、重复取消排空、原子审计和同 ID GET-only。完全一致的伪造也不是可信证据或批准；无敏感输出导入/UI/执行/部署。候选 `eval_0014` 本地最终门禁通过：专项 68、后端全量 13,332、前端 1,312 passed；受测源码、资源收尾、独立提交与精确 SHA CI 分别核验，不能冒用前轮 CI 或推断部署。

## 当前追加：授权配置导出工作台（2026-11-10）

[显式导出、原 ID 对账与有界下载](DevPilot_Authorized_QA_Export_Workspace.md)：datasets 界面加载精确 policy/grant/冻结来源，三份创建同意、单独下载同意、page-memory pending 和跨项目锁；未知 PUT/GET404 只查询原 ID。metadata discovery 不读敏感数据，下载核 exporter/receipt pin 与大小；不启用执行、不自动取软件/传输接收方或部署。候选仍为 eval_0013，门禁/提交/精确 SHA CI 分别记录。

## 当前追加：平台授权 QA 配置导出候选（2026-11-10）

[授权、分级、API 与安装验证](DevPilot_Authorized_QA_Exports.md)：默认关闭、精确 operator grant、人类 owner 与分离同意；骨架或获准 baseline 全量输入，ALL 请求值需重新绑定。加密不可变 ZIP、源快照复核、原 ID GET 对账与顺序审计。候选 eval_0013；无 UI/执行许可/金标或验收集输入/结果导入/正式批准/部署。

- [External QA technical metadata inspection / 外部 QA 技术元数据检查](DevPilot_External_QA_Metadata_Inspection.md)

## 当前追加：独立本地 QA 锁定软件分发（2026-11-10）

[完整成员/hash 闭包与新环境安装合同](DevPilot_Local_QA_Distribution.md)：九个固定 runtime wheel、独立六项构建锁、全部 35 源码成员/metadata/RECORD、许可和纯合成示例；新 venv 无网络完整安装、实际已安装命令 mock run/receipt/原 ID 对账。软件 integrity 不等于平台来源/导出权限，数据授权/输出治理/隔离导入仍待完成。无部署或真实调用。

## 当前追加：本地发送前身份回执（2026-11-10）

[独立身份回执](DevPilot_Local_QA_Run_Receipt.md)在 journal 创建后、start/reserve/DNS/send 前独占写入并确认文件 fsync，失败不重试。异常后可不打开敏感输出而取得原 ID；不证明当前状态/交付/来源/批准，缺失也不是未发送证明，不续跑或重发。

[本地 QA 只读对账命令](DevPilot_Local_QA_Reconciliation.md)：实际离线 CLI，原 ID 技术快照、ALL 分母、未知不重发；不读输出、不恢复运行、不导入平台证据。

## 2026-11-10：显式独立本地 QA 命令候选

[本地命令 / Local QA command](DevPilot_Local_QA_Command.md)：离线默认、分离输入/凭据、显式实发与私有明文输出同意，复用共享 run 和耐久 journal；精确 host、ALL DNS answers、TLS、不重发，结果仅外部未核验技术状态。不等于授权平台导出、受控依赖发行、证据导入或批准。

## 独立本地 QA run 耐久适配候选（2026-11-10）

[单次本地 journal 与共享核心适配](DevPilot_Local_QA_Run_Journal.md)：发送前 commit、每 ordinal 一次、累计预算不回收、未知结果不重发、读写取消排空；无默认网络客户端/API/CLI，重开只读，外部技术记录不是平台证据/批准。

## 当前追加：共享有界单次 QA JSON 采集（2026-11-10）

[固定版本单次采集核心](DevPilot_Shared_QA_JSON_Attempt_Core.md)共享现有完整 deadline/流处理/分类/关闭流程，App 通过显式 factory 保留动态出站 policy 和准入/dispatch/no-resend；不是第二套 runner、执行/导出授权或批准。

## 当前追加：共享 QA JSON 请求准备核心（2026-11-10）

[固定版本请求投影](DevPilot_Shared_QA_JSON_Request_Core.md)让 App 共用 literal URL/method/body/headers 准备，保留条件 identity、重复编码和历史 64→65 边界。无数据读取/发送/导出权限，纯源码及 wheel 自检不是完整 runner；准入、dispatch/no-resend 仍属 App。

## 当前追加：共享 QA JSON 响应核心（2026-11-10）

[固定版本响应核心](DevPilot_Shared_QA_JSON_Response_Core.md)将现有采集的单次 JSON 响应语义提到纯 devpilot，App 共用同一实现。无实发/部署或完整脚本导出；取消、unknown/no-resend 与历史 hash 不变。

[QA 关闭重复取消排空](DevPilot_QA_Shutdown_Drain.md)：唯一 Worker 取消、同一 shield waiter、排空后传播取消与清理状态；不回收丢失 Worker 或重发。

[路由资源预算与加载边界](DevPilot_Route_Resource_Budgets.md)：保留六条原预算，隔离文档导航对工作台的构建依赖，完整动态 HTML 样式按真实预览懒加载；不部署、不改变执行或批准边界。

[执行诊断工作区](DevPilot_Execution_Diagnostics_Workspace.md)：管理员显式只读加载、严格有界响应与账号隔离，显示五态占用与六类聚合安全分类，并交叉校验其一致性；不释放/回收/重试或执行。

[执行占用只读诊断](DevPilot_Execution_Reservation_Diagnostics.md)：人类管理员独立权限、仅技术合计、不证明 Worker 已死亡，不释放/回收/重试或执行。

[真实登录的合成多账号 QA 回归](DevPilot_Authenticated_QA_Regression.md)：真实密码/JWT/CSRF/RBAC 与独立 cookie 的离线主链，不是真实用户、浏览器或部署验收。

[独立历史报告/重测 PDF 草稿](DevPilot_Independent_PDF_Drafts.md)：固定嵌入字体与历史公开投影、显式收据下载；不是正式批准或部署。

[独立历史重测 Word 草稿](DevPilot_Independent_Retest_Word_Drafts.md)以固定双语格式投影存档比较事实，保留 ALL 样本和历史评估收据，不重算指标或授予批准。

[开发接续分析与模块计划](DevPilot_Development_Plan.md)记录当前源码、上一提交 Actions、运行观察及分模块门禁；[独立历史 Word 草稿](DevPilot_Independent_Word_Drafts.md)使用单独 renderer，不改变旧 owner Word 或批准边界。

## 独立主链合成回归 / Independent workflow regression

- [独立 QA 主链离线集成回归 / Independent QA workflow regression](DevPilot_Independent_Workflow_Regression.md)：HTTP/真实 Worker、双盲复核/仲裁、历史评估/报告/复测/Word；合成测试不是部署或正式批准。

## 2026-11-09：独立逐条复核中心与内联界面（候选，未部署）

[独立复核范围与合同](DevPilot_Independent_Case_Review.md)：明确指派两名不同盲审人和第三名仲裁人，owner 不可兼任；仅授予冻结 case，不开放项目成员/普通数据权限。候选现增加 `/workspace/reviews` 中心及项目内联分配/详情，共用同一人类专用服务；显式加载、领取、打开证据、追加决定及历史轮次结果，未知写入只核对同一 ID。任务/UI 切片为 `eval_0010`，最新独立档案候选 head `eval_0012`，运行仍为 `eval_0009`。**独立评估 API/修订 UI、历史报告/复测绑定 API/选择 UI 已有候选；正式批准与保留数据部署尚未完成**；没有真实模型/目标调用，不是整个平台完成。

- [独立全样本评估与不可变修订（候选）](DevPilot_Independent_Assessments.md)：`eval_0011`，服务端全量独立结论验真与明确读取/归档 UI；不切换旧报告/复测，不是批准，未部署。

## 当前状态入口（2026-11-09）

请先读[当前交付矩阵](DevPilot_Delivery_Status.md)，区分代码、部署、测试和未完成范围。下文保留各日期的历史切片与证据，旧的“未部署 / Worker pending / 报告未持久化”等说明只适用于当时，不覆盖后续已交付主链。正式审批、完整复核工作台与整个平台仍未完成。

## 本轮新增：执行前冻结效果标准（2026-11-08）

[标准与判定边界](DevPilot_Frozen_Effectiveness_Criteria.md)：新 v2 计划冻结版本化阈值，完整人工证据下按全样本精确判定，不是正式批准；报告新模板和同基准复测保留标准。无迁移或自动外呼。当前服务部署与新提交验证分别记录，历史 CI 不代表本轮成功。

[只读 Docker 诊断](DevPilot_Docker_Diagnostics.md)：有界元数据检查，区分 Docker 无响应、应用状态与磁盘风险；不自动重启、不读取日志/凭据或修改数据。

生产/开发 Compose 增加核心服务 HTTP 健康检查与 nginx 初始就绪依赖；这不是自动恢复，也不代表现有容器已应用。[探测范围与部署边界](DevPilot_Docker_Diagnostics.md#服务健康与启动顺序)。

- [同基准整改复测 / Same-benchmark retesting](DevPilot_Same_Benchmark_Retesting.md)：不可变逐条变化档案、固定分母与按需前后 Q/A；不是正式验收。

## 当前本地状态：已备份更新（2026-11-08）

[Docker 恢复与保留数据升级](DevPilot_Local_Recovery_and_Upgrade.md)：当前运行代码为 `0fd689da83a4ac7646250447fb6d044599a823c5`，App head `eval_0009`；在在线一致性备份后仅替换 gateway/frontend 并重载原 nginx，没有重启 Docker Desktop。账号、旧记录、配置、挂载和数据库完整性核验通过；全部现有账号的整改复测、助手、数据、报告和模型界面桌面与移动端只读冒烟通过。验收后精确删除两个无容器引用的旧 DevPilot 镜像标签，保留仍被引用的验证镜像与所有数据卷。该完整运行 SHA 触发的六项 Actions 均成功；Windows 本地完整回归仍有独立待修失败。没有配置模型、密钥或启用真实评测外呼。下面早期“待恢复/未部署”及旧运行 SHA 属于历史切片，不是当前状态；后续仅测试/文档提交不需重新构建应用镜像，其 CI 仍须独立核验。

## 当前：冻结 Word 草稿导出（2026-11-08）

[Word 草稿导出](DevPilot_QA_Word_Draft_Export.md)从历史存档生成真实多组件 DOCX，固定 renderer、模板版本和事实，不重新调用模型/目标、不批准。App head 不变；Docker 重启后已恢复，应用升级需备份和独立核验。存档提交 13ace1d 六项 Actions 均已通过，Word 改动须另核验新 SHA。

## 当前：不可变平台 QA 报告草稿（2026-11-08）

[多组件报告存档](DevPilot_Immutable_QA_Report_Archives.md)追加服务端已验证指标引用、完整模板版本/布局冻结和不覆盖历史的修订。人工填报与 Agent 建议不混入实测事实，全部仍为未批准草稿。代码 head 为 eval_0008，本地最后核验仍为 eval_0006；Docker 管理 API 无响应，未更改账号、配置或数据卷。下节是前一切片的历史说明。

## 当前：独立执行与已验证人工汇总（2026-11-08）

[独立授权执行](DevPilot_Admitted_QA_Execution.md)将冻结计划、有界 Worker、加密输出和复核接通，默认不启用运营外呼；执行提交 `0e56c3b60216350c3f598414b8b4eb02d842494a` 六项 Actions 已通过。[固定分母汇总](DevPilot_Verified_QA_Summaries.md)按全部冻结效果样本与最新人工决策给出已验证预览，不是已批准报告。代码 head 为 eval_0007，本地最后核验仍为 eval_0006，Docker 恢复并完成保留数据升级前不算部署。下面的条目保留各历史切片原有范围，由本节说明当前连接状态。

## 当前追加：加密输出证据与人工复核（2026-11-08）

[逐条证据与复核切片](DevPilot_QA_Evidence_Review.md)增加内部加密输出与技术观测的原子存储、Q/A/预期/来源同屏、人工三态结论及修订历史；App head 为 eval_0006。仅项目 owner 自复核，缺证据不能通过，计数不冒充准确率。没有新增执行入口、目标调用或 Worker；冻结定义仍不是执行批准。

## 当前追加：耐久派发日志（2026-11-08）

[技术派发日志](DevPilot_Durable_Dispatch_Journal.md)实现不可重派序号、同事务预算预留、票据防篡改、未知写入和过期整次中断；该切片引入 eval_0005（当前 head 为 eval_0006）。没有新增执行 API、Worker、输出证据或质量判决，后续先补独立准入再接采集器。

## 当前追加：有界单次采集内核（2026-11-08）

[内部单次 QA 响应采集](DevPilot_Bounded_QA_Attempts.md)实现单次发送、响应/超时边界、取消清理和未知派发不重试。无运行 API、Worker、判分或持久证据，不把采集成功当作效果 PASS。

## 当前追加：请求版本与冻结 QA 计划（2026-11-08）

[加密请求版本界面](DevPilot_Request_Version_UI.md)支持从 cURL 调试器明确保存及浏览元数据；[QA 计划后端](DevPilot_Frozen_QA_Plans.md)与[确认界面](DevPilot_Frozen_QA_Plan_UI.md)固定请求/数据版本、JSON 映射和有限参数。当前仅冻结定义与逐输入预检，不是执行授权、运行结果或报告证据。

## 当前追加：项目组件与不可变提测清单（2026-11-07）

[项目组件与提测清单](DevPilot_项目组件与提测清单.md)记录已实现的 owner 组件关联、冻结 QA 版本绑定、服务端库存快照和 App 迁移 eval_0002。不是可执行方案、验收通过或报告证据；旧文档“尚无组件关联”仅代表上一轮。

## 本轮实现状态（2026-11-07）

[实现进度与下一步](DevPilot_实现进度与下一步.md)：评测优先首页、模型四协议连接、报告有界多轮与[项目/QA数据最小闭环](DevPilot_QA数据最小闭环.md)已落地；原始材料理解、QA 候选构建和完整数据治理仍待开发。该矩阵是目标路线图与当前代码之间的校准入口，当前状态以[交付状态页](DevPilot_Delivery_Status.md)为准。

## 报告 Agent 增补（2026-11-07）

已新增默认关闭的受限报告 Agent：显式授权、汇总指标 allowlist、复用模型工厂/无工具 LangGraph、人工确认附录与输入变更失效。未配模型仍可人工报告；不代表整个评测 Agent 闭环已完成。

## 报告模块增补（2026-11-07）

[报告模块设计与实施边界](DevPilot_报告模块设计.md)：已实现人工填报、计数/指标校验、指定模板版本草稿及 Markdown/JSON 下载；未实现持久历史、模板管理、正式审批、Word/PDF 或平台结果引用。该实现不代表 I0 全部门禁已退出。

> 基线日期：2026-11-06。定位：**AI 组件评测工作台 + 自动化评测 Agent**。
> 2026-11-06 建立文档基线，2026-11-07 开始 I0 首批核心判定修复（见现状审计）；不代表运行时代码已实现全部目标方案。旧版“通用研发 SaaS / 九 Agent / Milvus 必选”设计由新版取代，历史可通过 Git 查询。

## 2026-11-07 增补

- [历史材料分析与设计校准](DevPilot_历史材料分析与设计校准.md)：授权历史材料的脱敏结论、摸底/验收和数据/评分口径。
- [CI 修复与隔离开发环境](DevPilot_CI修复与隔离开发环境.md)：真实失败原因、可复现命令及验证范围。

## 阅读顺序与事实来源

1. [可行性分析](DevPilot_可行性分析.md)：可行条件、范围和投入边界。
2. [现状审计与修复清单](DevPilot_现状审计与修复清单.md)：代码证据、已复现问题与环境限制。
3. [需求分析](DevPilot_需求分析.md) → [业务流程与迭代计划](DevPilot_业务流程与迭代计划.md)。
4. [数据集与指标规范](DevPilot_数据集与指标规范.md)：数据质量、分母和判定的唯一规范；材料批次、组件级归档与原生响应评估见[评测数据构建与执行工作流](DevPilot_评测数据构建工作流.md)。
5. [系统架构](DevPilot_系统架构设计.md) → [DeerFlow 改造方案](DevPilot_基于DeerFlow的改造方案.md)。
6. [前端交互设计](DevPilot_前端交互设计.md) → [接口调试与脚本导出](DevPilot_接口调试与脚本导出设计.md) → [人工复核工作台](DevPilot_人工复核工作台设计.md) → [材料与模板规范](DevPilot_材料与模板规范.md)。
7. 详细设计：[LangGraph](DevPilot_LangGraph工程设计文档.md)、[Prompt](DevPilot_Prompt工程设计文档.md)、[API](DevPilot_API接口设计文档.md)、[实时通信](DevPilot_实时通信协议设计.md)、[数据库](DevPilot_数据库详细设计.md)、[知识库](DevPilot_RAG知识库与数据架构设计文档.md)。
8. 交付保障：[测试方案](DevPilot_测试方案.md)、[部署运维](DevPilot_部署与运维设计.md)。
9. [技术依据与决策](DevPilot_技术依据与决策记录.md)。

事实优先级：已验证代码/测试优于现状描述；目标契约以数据与指标、API、数据库设计为准。发生冲突应修改文档和契约，不能让模型临场解释。

## 状态标记

- **已存在**：找到代码，不等于完整验收。
- **已复现**：本地最小用例已观察到问题。
- **静态发现**：代码推导，尚未运行对应服务或构建。
- **目标设计 / 待开发**：不可当作当前可用能力。
- **已验证**：须附环境、命令、结果与范围；纯单元测试不能写成端到端验收。

## 不变的产品决策

- 数据质量、证据和复现优先，不追求 Agent 数量。
- Agent 辅助规划、生成和解释；确定性程序负责执行、计数、阈值与状态流转。
- 首版受控内部部署，不做计费型 SaaS；保留用户隔离，团队共享需单独授权设计。
- 不新增第二套通用 Agent Runtime；复用 DeerFlow，新增领域业务和有界 Worker。
- 参考答案/验收集不能进入目标提示词或不受控的聊天记忆。
- 缺失必要证据不得自动 PASS。
- 一份 RequestSpec/执行核心连接调试、平台评测与可选独立脚本导出；不让 LLM 临场生成两套统计逻辑。
- 独立人工复核中心与结果页共享任务；人工决定、自动裁判与原始观测分层，不改写原始证据。

## 维护规则

只维护中文、英文项目文档；保留中文 DevPilot 入口与中英上游参考，不保留日/法/俄项目 README。此约定不限制被测材料、数据或 UI 支持的语言，也不删除开源许可/版权。frontend/public/demo 的历史对话快照包含旧上游 README 文本/路径，保留原貌，不作为现行文档入口或当前能力依据。

开发同时更新测试与相关文档；PR 标明完成/未完成、迁移影响、回退办法。里程碑仅随验收证据更新，不因日期到达自动完成。[templates/](templates/) 是目标格式示例，接口实现前不能直接上传执行。

## Current implementation update

See [DevPilot evaluation workspace delivery and configuration](DevPilot_Evaluation_Workspace.md) for the implemented cURL debugger, off-peak evaluation scheduling, multi-component drafts, opt-in field-intake agent and administrator model catalog. This update supersedes older “planned only” statements for those specific slices, not the remaining lifecycle roadmap.

## 导航与执行安全补充

- [导航与统一出站基线](DevPilot_导航与统一出站基线.md)：单一组件入口、可选自定义助手及调试/手动/定时统一出站策略；不代表完整评测流水线。

- [独立历史评估报告与复测档案 / Independent assessment archives](DevPilot_Independent_Report_Retest_Archives.md)：`eval_0012` 后端/API 与显式选择 UI 候选；独立来源与旧 owner 档案分离，非正式批准，尚未部署。

## 共享固定目的地传输（2026-11-10）

[共享 pinned HTTP 核心](DevPilot_Shared_Pinned_HTTP_Core.md)：原 App 通过显式动态策略 callback 共用固定 origin/Host/SNI/TLS/零重试机制，literal IP 围栏防止二次 DNS；保留准入/dispatch/no-resend/取消边界。不是完整 runner/exporter，无依赖/迁移/部署或真实调用。

## 共享完整有界 QA run（2026-11-10）

[完整编排合同](DevPilot_Shared_QA_JSON_Run_Core.md)：平台实际共用版本化 consumer/monitor/group，保留 dispatch-before-send、未知结果即停发、原 deadline/取消和 App DB 读写排空。完整回归/旧新实际 Worker 对照/实际 wheel 与源码证据分别核验；不是授权 exporter、实发 CLI、部署或正式批准。
