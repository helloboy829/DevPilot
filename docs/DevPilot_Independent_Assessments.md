# 独立复核评估修订 / Independent assessment revisions

> 工作区候选（2026-11-09）：独立逐条复核已具备共享中心与内联 UI；本切片新增服务端独立评估预览及不可变运行评估修订。候选 App head 为 `eval_0011`，最近独立核验的运行部署仍为 `eval_0009`。未迁移生产、部署、开启执行或调用真实目标/模型。

## 1. 范围与不能混淆的概念

`app.evaluation.qa_assessments` 从已冻结的效果计划、全部样本、持久派发、加密输出和独立逐条决定构建评估。此处策略明确标记 `post_collection_assessment`：它不是补做或声称此前已经存在的预运行独立审批，也不改变执行准入。

- 预览：`qa-independent-assessment-preview.v1` / `verified_independent_assessment_preview`。
- 修订：`qa-run-assessment-revision.v1` / `immutable_independent_assessment`，显式追加，历史不覆盖。
- 所有结果均 `acceptance=not_approved`；完整复核、全部 PASS 或阈值 `met` 都不构成正式批准。
- 后续界面切片已在 `/workspace/datasets` 添加独立评估预览、历史与归档入口；仍不接入既有报告、Word 或同基准复测。旧 owner 自复核的汇总/hash/历史路径保持不变。后续报告需要显式选择评估修订，不能静默换分母/评审来源。

## 2. 分母、证据与阻塞

仅接受 effectiveness 模式且全部冻结样本数 1–500；性能重复不能充作效果样本。每个 ordinal 都在分母，不接受客户端指标、过滤器、部分任务列表或“只看已通过任务”。

每个 case 验证冻结输入/参考、派发技术观测及加密输出；每个当前轮次任务验证 definition/subject、三名不同指定人、assignment/decision 状态、加密理由及确定性结论。共享冻结源只验真一次，全部敏感验真在线程中运行，不在事件循环做批量解密。

| 状态                                       | 评估结果                                              |
| ------------------------------------------ | ----------------------------------------------------- |
| 两盲审一致 PASS/FAIL，或有效仲裁 PASS/FAIL | 对应逐条结果；仍非正式批准                            |
| 分歧或仲裁 uncertain                       | uncertain，阻塞完整评估                               |
| 无任务、待处理任务或撤销任务               | unreviewed，不能因撤销负面任务而消除阻塞              |
| 同一 ordinal 多任务存在 PASS 与 FAIL 冲突  | uncertain，并标记 conflicting_independent_resolutions |
| 缺输出、技术错误或采集未结束               | 保留全样本分母，技术/采集阻塞；不能人工补成 PASS      |
| 当前证据/定义/结论损坏                     | 通用冲突或完整性错误，不能输出“已验证”计数            |

全部当前任务都参加，不能选择“最后一条看起来更好”的任务。重开任务的新轮次改变当前预览，但不追溯修改既有评估修订。历史任务轮次仍由原服务显式打开；本评估绑定归档时的当前轮次。

若计划包含冻结 v2 criteria，沿用整数比较：`PASS * 10000 >= 全冻结样本数 * min_pass_rate_bps`。存在任何阻塞时，即使门槛为零也为 incomplete。未包含 criteria 的旧计划不自动补默认阈值。owner 自复核记录完全不参与此路径，既不会替代独立投票，也不会因 owner 意见改变而更新独立 summary hash。

## 3. 权限、数据和接口

前缀：`/api/evaluation/projects/{project_id}/review-runs/{run_id}`。

| 方法和后缀                       | 作用                                                                      |
| -------------------------------- | ------------------------------------------------------------------------- |
| GET independent-assessment       | 当前独立评估预览，最终锁内复查并审计                                      |
| GET assessments                  | 最近最多 100 个修订的安全元数据，不含 document/case 内容                  |
| GET assessments/{assessment_id}  | 打开固定历史文档，仅校验归档自身，不用当前意见重算                        |
| POST assessments/{assessment_id} | 显式追加修订；传 summary_hash、expected_previous_revision、confirmed=true |

上述全部要求已认证人类 owner + 项目 read/review；POST 另需 write。内部 Agent、被指派复核人或其他 owner 不能借窄任务授权读取整个项目评估。响应沿用 private/no-store、有界请求体和通用错误；不新增更新/删除/执行/审批接口。

评估仅包含安全运行/组件/计划元数据、全样本计数、阈值状态及 case/task/轮次/结论 hash 绑定；不含 Q、实际 A、参考、理由、actor ID、请求 secret 或密文。hash 是完整性指纹而非独立签名；不能宣称能抵御持数据库写权限者重算所有 hash。

## 4. 并发、追加和不确定写入

预览/追加先读取完整快照，离事件循环验真；在与任务变更相同的 run 锁下重读全部快照。重开、决定变化或源变化均拒绝陈旧结果。追加还比较上一个 revision，范围 1–1000，文档和技术审计在同一事务提交。

客户端提供 32 位小写十六进制 ID，同 ID 同请求可返回原回执；不同请求拒绝。503/连接丢失不能证明没写入，客户端只按相同 ID GET 核对，不自动 POST 重发、生成新 ID 或推进 revision。缺回执需要显式人工刷新与判断。

允许归档 provisional 评估，保留未完成证据状态，但不允许称为完整或批准。旧文档绑定归档时的 summary 与 case/task 结论，不查询当前模板或重算当前决定。

## 5. 数据库和验证

新增 `eval_0011` 仅追加 `evaluation_run_assessments` 与 run/revision 索引；不改 `eval_0010` 或任何已部署修订，不碰 Harness ledger。表含 owner/project/run、revision/time、请求/hash 和安全 JSON 文档；唯一 run/revision、复合 run FK 和边界检查由数据库约束。

主要回归：`test_qa_assessments.py`、`test_qa_assessments_router.py`、`test_qa_assessments_migrations.py`。覆盖独立分母/仲裁/技术失败/owner 隔离、冻结 v2 阈值、篡改、并发 CAS、事务回滚、重开竞争、未知写入和 SQLite/PostgreSQL 增量迁移与原数据保留。临时数据库使用合成数据与测试 key，不接入部署库。

本轮最终完整后端 **12,231 passed / 19 skipped / 11 deselected / 40 warnings**，Ruff check/format **1,232 文件**、纯领域 **15 / 58 passed**；定向 104 项与全量重叠，不相加。本轮不重跑前端或部署。实际失败及修正过程见[隔离环境记录](DevPilot_CI修复与隔离开发环境.md)与[交付矩阵](DevPilot_Delivery_Status.md)。此文描述代码合同，不能代替运行部署、真实多账号 UI 或用户最终验收证据。

English: this slice adds owner/human-only, all-sample independent assessment previews and explicit immutable revisions. All source/decision verification runs off-loop and is rechecked under the run lock. Incomplete/uncertain evidence blocks threshold satisfaction. Historical owner summaries and report/retest paths remain unchanged; this is not approval, execution enablement or a deployed upgrade.

## 8. 独立评估工作区 UI（2026-11-09）

`IndependentAssessmentPanel` 与旧 owner 自复核区分开显示，使用现有评估 API；不新增后端、迁移或依赖。列表、全样本预览/最近 100 修订及历史正文均由用户明确读取，无轮询。严格 DTO 边界检查 scope、策略、项目/运行、全量 ordinal/计数/分母、任务绑定、阻塞与非批准状态；这不是客户端密码学验真，也不另算阈值。指标仍由服务端决定。

归档必须先看过预览与历史，另勾选确认；仅提交看过的 `summary_hash`、`expected_previous_revision`、`confirmed=true`。允许不完整 provisional 归档，但永远不是批准。写锁和同步页内 Map 在 POST 前保留唯一 ID；任何未知写入只允许同 ID GET 核对，404 也不解锁重发。Map 跨项目切换保留，离开/刷新整页不持久化，用户应自行记录 ID。迟到响应只记录原范围回执，不污染新项目/运行。已确认回执后还需明确刷新预览/历史，才可开始下一修订。

历史按固定 ID 打开，不调用当前预览重算；列表打开另核对修订、hash、时间。修订上限 1,000 禁止继续写。错误不暴露原始异常且清除失效显示。样本/任务指纹按需展开，无 Q/A、金标、理由或人员身份；文本不渲染 HTML/外链，不写敏感浏览器缓存。键盘确认、390px 移动端与桌面由模拟 API 浏览器门禁覆盖，不代替真实多账号联调。旧报告/Word/复测依旧使用旧来源，未被静默切换。

### 独立评估 UI 候选的隔离验证（2026-11-09）

本轮新增两个单测文件（严格 DTO 19 项、DOM 8 项）及 4 项桌面/390px 模拟浏览器用例。完整前端 **1,152 passed / 146 文件**（最终 26.3s），完整模拟浏览器 **210 passed**（248.2s）、独立登录/设置恢复 **2 passed**（1.6s），浏览器均 `--retries=0`。定向 27 / 4 项包含在对应全量，不相加。整个 frontend Prettier（含指南）、ESLint/TypeScript 与生产构建通过；本轮没有重跑后端 12,231 项，不挪用前轮结果当新证据。

首次仅同步测试到旧快照，两文件因缺新模块变红；实现同步后，一项 fieldset 继承 disabled 的测试读取方式错误、DOM 查询类型选项及导入顺序暴露并修正，保留原失败日志。首次构建因跨快照 node_modules symlink 被 Turbopack 拒绝；改用同盘硬链接的独占依赖树，未放宽构建根、下载依赖或修改共享缓存标识；修正后生产构建和完整门禁通过。旧 Worker 偶发派发失败的根因仍未确认，本轮未声称解决。

这是公开源码快照、既有 Docker Node 依赖、合成 API 和容器 loopback 站点的验证，不是实际后端/多账号联调、远端 CI、正式批准或用户验收。没有生产迁移、key 生成、执行开关、真实模型/目标调用、提交、推送或部署。候选 head `eval_0011`、最近独立核验的部署 head `eval_0009`；独立报告/复测显式绑定、正式批准与保留数据部署仍待交付。

本 UI 轮资源收尾已独立核验：30 份 Docker 日志/JSON 先导出并逐项验 SHA-256，834 份公开源码/测试/指南与测试快照一致；随后仅删除本轮独占快照、12 个辅助文件及已备份证据副本，宿主 staging 亦精确删除。仅停止本轮 Node CI，其余三个 CI 始终停止；最终全部 14 容器的 ID/镜像/运行或停止/restart/OOM 签名恢复测试前状态、9 行镜像标签清单不变。无可安全删除的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除；业务四服务 healthy，诊断 ok。五个明确 Node 缓存标识哈希未变，不声称整个缓存树已审计。资源收尾后的追加仅为文档，不代表重跑完整套件或已部署。

## 2026-11-09：独立历史来源档案后端/API 候选

后续 [独立评估报告/复测档案](DevPilot_Independent_Report_Retest_Archives.md) 在独立命名空间绑定明确 assessment ID、修订和 hash，追加候选迁移 `eval_0012`，不切换本文既有 owner 自复核路径、历史模板或导出。完整历史修订可以明确选择，不追随当前任务；provisional 不可作完整来源。独立选择 UI/Word、正式批准、远端 CI 与备份部署仍待完成；运行部署仍为 `eval_0009`。此前章节保留原切片边界。
