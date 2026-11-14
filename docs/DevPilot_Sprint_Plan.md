# DevPilot 两周冲刺计划

编制：2026-11-14。建议以 2026-11-16 至 2026-11-27 的十个工作日为窗口，按一名开发者约 **80h** 估算；这是待执行的范围建议，不是已完成记录或上线承诺。依据：[当前状态](DevPilot_Delivery_Status.md)、[业务流程与迭代方向](DevPilot_业务流程与迭代计划.md)、[工程约束](../AGENTS.md)。

2026-11-14 进展：加密输出运行时与显式管理命令已实现，`7ba1484` 的 4 workflows / 8 jobs 全成功。现补充[合成 SQLite 升级与恢复演练](DevPilot_Candidate_Upgrade_Recovery.md)：真实双 ledger、39 张旧表、WAL 在线备份、`0009 → 0014` 与新路径还原；本模块最终门禁/精确 SHA CI 另行记录。候选镜像/浏览器验收、PostgreSQL 原生恢复、明文副本、更广泛崩溃产物和 Windows 仍待完成。

## 优先处理什么

用户最先需要的是：用当前源码在可重复环境中运行已有工作台，并把 QA → 冻结 → 合成采集 → 独立复核 → 历史报告这条路径交给人验收。已有大量候选代码，继续增加 CV/模型裁判入口的收益低于修复环境、确认精确 SHA CI 和完成候选版本的运行验真。

开发环境升级的直接门禁是可重复依赖、通过的精确 SHA CI、迁移/数据兼容、私有配置保留、镜像与源码一致、可恢复备份和回退演练。**正式批准未完成阻止“正式质量验收/accepted”宣称，但不要求先开发所有业务功能才能验证候选环境。** 新 QA 调度和 lost Worker 自动释放在安全合同完成前保持关闭；本地 retention CLI 接入不阻断平台原有受控链路。

## 迁移依赖与技术债

实际 `down_revision` 链：`eval_0009 → eval_0010 → eval_0011 → eval_0012 → eval_0013 → eval_0014`。五个候选迁移是顺序升级，不能只执行最后一个，也不能将 `eval_0014` 当作 Git HEAD。

| 迁移        | 新增职责                         | 语义依赖与验收重点                                                                  |
| ----------- | -------------------------------- | ----------------------------------------------------------------------------------- |
| `eval_0010` | 双盲 case 任务、决定、仲裁与审计 | 冻结 case/证据、两名独立评审和第三仲裁；owner 隔离、租约/重复取消、未知写原 ID 对账 |
| `eval_0011` | 不可变独立评估修订               | 验真 `0010` 的 ALL 冻结样本结论；缺项/冲突不能完整，revision/CAS 不覆盖历史         |
| `eval_0012` | 独立历史报告与复测档案           | 绑定 `0011` 的具体 revision/hash；同基准、完整分母，历史 Word/PDF 不读最新来源      |
| `eval_0013` | 授权配置导出及审计               | 业务上绑定冻结 plan/grant，不依靠报告授予导出权；数据库迁移仍排在 `0012` 后         |
| `eval_0014` | 外部技术声明隔离接收及审计       | 外键绑定 `0013` 原 export；canonical/原始声明 hash 区分，一致伪造仍未验证           |

债务集中在源码与旧运行环境之间的距离、文档历史与当前状态混用、严格合同跨层维护、取消/崩溃后的本地输出编排，以及独立批准/失联 Worker 机制尚未闭环。原链路的 Word/PDF、技术导出和元数据接收已有实现，不重新按“完全未开发”估算。

升级风险与对策：

- schema 与应用镜像必须成套验证；新增表/外键/约束虽属 additive，仍须用合成 `eval_0009` 数据库演练 `0009 → 0014` 并核对历史数据。不得把 additive 等同于无风险，不复制私有业务数据库到测试环境。
- 备份必须可恢复，除评测表外还要验证账号、Harness ledger、配置与挂载；数据库升级后不能只换回旧镜像就宣称完整回退。优先采用保留备份的恢复演练，不在业务库上试 downgrade。
- operator key、策略/grant、账号角色属于独立运行配置；新源码不能代替配置授权。默认关闭执行/外发，不通过生成 key 或真实请求来“证明可用”。
- Linux 安装/CI 不证明 Windows 本地通过；当前 stopped 业务容器与旧部署收据也不证明最新候选已运行。明确分别验收。

## Week 1：固定可交付基线（40h）

- [ ] **P0 · 8h**：关闭当前环境/CI 修复。记录准确 pushed SHA 和每项 Actions/jobs；从当前锁文件完成 Python 3.12/dev 环境、默认 collection、Blocking IO、Ruff、完整后端与实际安装门禁。交付源码/失败/修复/成功收据及隔离资源清单。
- [x] **P1 · 16h**：本地加密 incomplete-output retention 与真实 CLI 接入。输出前 receipt、重复取消、硬退出、未知写入和原 ID 对账回归/实际安装已验证；复用原 shared runner，分别确认加密输出与处置。`7ba1484` 精确 CI 已通过；明文副本、广泛崩溃产物和 Windows 验收独立保留，不补造旧目录 receipt、不认证未检查 ciphertext、不恢复/重发。
- [ ] **P0 · 8h**：候选迁移的隔离升级/恢复演练。核对完整迁移链，用合成旧账号/数据验证历史 hash、外键与回退恢复。交付备份/还原与版本矩阵；不更改或复制私有业务 DB。
- [ ] **P0 · 8h**：失败修复与门禁缓冲。处理可归因失败、记录跳过原因、更新模块文档；每个代码模块单独提交、测试、推送和核验 CI，不带已知失败进入下一模块。

Week 1 退出条件：存在一个可定位源码、依赖、测试、分发和迁移演练的候选基线；未解决项明确列出，不能把待验收写成已完成。

## Week 2：形成验收包并收敛后续合同（40h）

- [x] **P0 · 12h**：候选镜像和合成工作台验收包。已整理[候选验收包](DevPilot_Acceptance_Package.md)：精确 SHA/CI 核验、登录与 RBAC、盲审/仲裁、ALL 分母、历史评估与报告/复测、正式批准/撤销、未知写原 ID 对账、备份/回退与签收表；**实际镜像构建、环境替换与用户验收尚未执行**，另行按既有授权边界记录。
- [x] **P1 · 12h**：正式批准首切片的合同/API/失败测试设计。已交付 [正式批准首切片](DevPilot_Formal_Approval.md)（`eval_0015`）：append-only 批准/撤销修订、固定 assessment revision/hash、独立复核完整、冻结阈值（若定义）达标、审批人非 owner 且非该 run 盲审/仲裁、撤销附理由与审计、同 ID 幂等与原 ID 对账。只有 owner 记录；审批人专属身份、多人签核、通知、导出权限与用户验收仍未完成，不能把 case PASS 或阈值达标当批准。
- [x] **P1 · 8h**：lost Worker 与 QA 调度安全合同及最小回归。已交付[执行安全合同](DevPilot_Execution_Safety_Contract.md)：`classify_held_reservation` 只读固定投影，deadline/终态不证明 Worker 死亡，恒不授权 release/reclaim/requeue/retry/resend/dispatch；未知/不一致行失败关闭；回归锁定调度器与正式批准不得导入/触发执行仓库、运维路由只有聚合 GET。**释放、配额处置与 QA 调度准入仍未实现**，旧进程不可再发的证明仍缺失。
- [ ] **P0 · 8h**：集成/用户验收缓冲。处理跨模块或 CI 问题、核文档链接与资源收尾；总结能验收的范围和下一轮 backlog。部署、真实目标/模型或敏感数据处理不能因排期而隐式开启。

Week 2 退出条件：交付可由用户复核的合成验收包、已验证候选基线及明确的批准/运维后续合同；不宣称整个评测平台完成。若 Week 1 超时，先保 CI、数据和验收，推迟批准/调度设计任务，不压缩验证或削弱合同。

## 冲刺外保留项

敏感外部输出作为证据的导入、CV 适配、真实可观测 TTFT/TPS、模型裁判校准、整改通知、知识晋升和真实项目效果验收另行拆分。它们分别需要数据/目标/模型授权及可验证证据；技术元数据隔离接收不是上述功能的替代品。

English: The proposed 80-hour sprint prioritizes a reproducible candidate baseline, runtime retention integration, isolated migration/recovery rehearsal and a synthetic acceptance package. Formal approval and safe lost-worker/scheduling operations remain separately scoped contracts; no deployment or real calls are authorized by this plan.
