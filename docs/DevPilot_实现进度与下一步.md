# DevPilot 实现进度与下一步

更新：2026-11-19。此文件是唯一的模块级开发进度账本：逐项状态、先后依赖与下个验收门槛在这里更新。代码/部署/候选/验证事实以[交付状态](DevPilot_Delivery_Status.md)为准；功能实现入口、API/schema、权限、失败语义和测试说明见[功能实现说明](DevPilot_Feature_Implementation_Spec.md)。旧日期切片已原样移至[实现切片历史](DevPilot_Implementation_Slices_Archive_2026-11.md)。

## 当前里程碑

文档目标合同覆盖材料构建、无 expected 执行、共享原生证据、效果浏览器和性能工作台。DOC-01 正在统一跨文档的证据字节/状态、盲审可见范围和功能 ID；应用代码尚未进入这些新闭环实现。目标规格与当前已交付能力继续分别记录。

当前产品链：

```text
材料批次/人工数据 → 组件适用数据版本 → RequestSpec/冻结计划 → 授权执行
    → 每条原生请求/响应与技术观测 → 效果或性能结果浏览 → 复核/评估修订 → 报告/复测
```

现有源码已有人工 JSON/JSONL 导入、自审冻结、版本/hash 绑定、部分计划准入/有界执行、加密提取文本、逐条复核、独立审核/评估/报告切片。项目外材料解析与构建、reference optionality、原生 HTTP body artifact、结果查询/访问 API、效果浏览器、性能负载与结果工作台仍未闭环。`evaluation-schedules` 与 `/api/component-tests` 是兼容/legacy 路径，不扩展为新 QA/performance 核心。

## 开发进度

| 功能 ID | 功能                                                      | 状态      | 依赖/下一出口                                                                                                                                                                                    |
| ------- | --------------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| DOC-01  | 文档职责、历史归档、合同冲突和模块导航收敛                | 开发中    | 保留 CI/迁移/失败证据；统一 EVID-02/EFF-01..03 口径、核链接/测试路径，跑格式与 diff 检查后提交。                                                                                                 |
| DAT-02  | optional expected/reference 兼容迁移                      | 待开发    | 先冻结输入/reference/hash revision 兼容规则；无 expected 不阻止已授权调用/原生响应采集；reference 必需指标缺失影响 assessment，不拦截采集。                                                      |
| EVID-02 | 原生请求/响应 artifact、capture status、budget 和失败恢复 | 待开发    | 与 DAT-02 schema 协同；先扩共享 attempt 的有界 raw-byte contract 并写失败测试，再做 App additive encrypted storage/receipt、稳定 ID、hash/size/media/header allowlist 与 exact-ID unknown 对账。 |
| EFF-01  | 运行与 case 结果查询 API                                  | 待开发    | 依赖 EVID-02 manifest：固定总数、稳定 cursor/filter、project/owner/fence、普通 DTO 不解密；盲审列表不可泄露他人决定；越权/篡改 cursor/hash 拒绝。                                                |
| EFF-02  | 分类 evidence grant/access API                            | 待开发    | 依赖 EFF-01 与 assignment/round/reveal 权限；逐类型审计、短时 access ID、no-store、Range/body caps；不得复用 owner 旧详情绕过盲审。                                                              |
| EFF-03  | 效果结果浏览器                                            | 待开发    | 依赖 EFF-01/02；运行概览、case 筛选、详情分区、显式加载/授权、切页清明文与 late-response fence；不取代任务复核 UI。                                                                              |
| DAT-03  | 项目外材料批次、解析、逐组件候选、单项目归档与审核冻结    | 待开发    | 依赖 DAT-02/data applicability contract；先 deterministic parser 与人工提取状态，再受限 Agent 候选；不绕过审核冻结。                                                                             |
| PERF-01 | 性能 scenario/profile、循环 manifest 与预算预检           | 待开发    | 复用 DAT-02/EVID-02/EFF-01 的 case/request/evidence identity；有限 request cap、可选 duration first-limit、warmup、timeout、deadline、drain。                                                    |
| PERF-02 | 性能 durable worker、逐请求 dispatch/evidence             | 待开发    | 依赖 PERF-01/EVID-02；warmup/measurement/unknown/failed 全部留痕，不重试不续跑；采集失败不改分母。                                                                                               |
| PERF-03 | 性能 metrics API 与工作台                                 | 待开发    | 依赖 PERF-02；versioned quantile/usage/source/applicability，summary 与逐请求证据 hash/population 对账。                                                                                         |
| PERF-04 | AIPerf/GuideLLM adapter spike                             | 待开发    | PERF-02/03 后，只在隔离 Mock 上验证 durable ACK 回调和证据桥；不满足则维持 external-unverified 对照。                                                                                            |
| R1      | Legacy `/component-tests`/schedule 路径收敛               | 待开发    | 新链路覆盖并经迁移/只读 parity 验收后再停止旧写入；不双写，不改写旧 run。                                                                                                                        |
| A1      | 模块化扩展：报告正式发布、知识审核推广、CV 全链、通知     | 部分/待排 | 按用户目标和各自合同分批进入，不阻塞当前数据构建→结果浏览主链。                                                                                                                                  |

**实施顺序**：DOC-01 → DAT-02 与 EVID-02 schema 协同 → EVID-02 shared attempt/artifact/fault recovery → EFF-01 → EFF-02 → EFF-03 → DAT-03 → PERF-01 → PERF-02 → PERF-03 → PERF-04 → R1。每个阶段先测试失败、再修复；当前切片全量测试与精确 SHA Actions 未核验前，不把下一阶段记为已验收。可并行准备 DAT-03 的只读 parser fixture，但不可绕过 DAT-02/EVID-02 合同形成第二套执行格式。功能 ID、合同细节统一引用[功能实现说明](DevPilot_Feature_Implementation_Spec.md)及各领域 owner 文档。

## 开发记录

| 日期       | 范围                    | 结果/证据                                                                                                                                  | 当前状态                                   |
| ---------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| 2026-11-19 | 架构/业务合同与模块矩阵 | 新增数据构建、效果、性能工作台目标规格及功能到代码/API/权限/失败恢复/验收映射；源代码与缺口盘点见[交付状态](DevPilot_Delivery_Status.md)。 | 文档收敛与交叉核验中；未开始应用代码实现。 |

后续每个实现切片追加一行：feature ID、commit SHA、失败回归与修复后的命令/结果、精确 Actions 链接、迁移/部署/业务验收状态。定向通过不替代全量结果；真实服务/部署须单独授权。
