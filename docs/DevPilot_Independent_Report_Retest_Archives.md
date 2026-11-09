# 独立评估修订绑定的报告与复测档案 / Independent assessment archives

> 2026-11-09 后端/API 与工作区 UI 候选。App head `eval_0012`，现有部署仍为 `eval_0009`。未部署、未启用执行、未完成整个平台或用户验收。以下反引号标记的字段是合同，不是批准凭证。

## 1. 独立命名空间，不切换旧语义

本切片把已经归档的**明确历史独立评估修订**绑定到不可变报告草稿与同基准复测。既有 owner 自复核报告、复测、模板与下载路由完全保留，不在原路径静默换分母或改为独立意见。

- 模块：`app.evaluation.qa_independent_archives`。
- 表：`evaluation_independent_report_archives`、`evaluation_independent_retest_archives`；追加迁移 `eval_0012`，不改已部署迁移或 Harness ledger。
- 来源 DTO：`run_id`、`summary_hash`、`assessment_id`、严格整数 `assessment_revision`、`assessment_hash`。客户端不能提交统计、决定或自动生成的批准。
- 报告模板固定为 `independent-qa-project-en@1.0.0` / `independent-qa-project-zh@1.0.0`；布局正文独立保存，不是旧模板目录的动态别名。
- 状态始终 `not_approved`；完整双盲复核、PASS、冻结标准 `met` 都不是正式批准或项目验收。

## 2. 来源语义与证据限制

只读取已归档评估的公开不可变 document/receipt、冻结 plan/run、组件 ID/项目 ID，以及派发的 ordinal/sample ID。绝不为存档读取 Q/A/金标、owner 票、当前任务/决定、请求密文或输出密文；历史读取不依赖当前解密 key。

校验 owner/project/run/plan/hash、明确评估 ID/修订/收据、固定独立政策、全部冻结效果样本及顺序、完整技术采集、每条确定 PASS/FAIL 与任务承诺、全量计数/分母、严格类型及整数冻结阈值。provisional、缺失、不确定、技术缺失或有 blockers 的评估不能作为来源。未达阈值但完整的评估仍可如实存档，不能只挑成功样本或藏掉 FAIL。

**这是历史评估承诺的完整性验证，不是重新解密当前原始证据或重做独立裁决。** hashes 是服务端完整性校验，不是外部数字签章，不抵抗能同时改写数据库及所有校验值的攻击者。评估原始验真边界见[独立全样本评估](DevPilot_Independent_Assessments.md)。

任务后来重开或产生新评估，不追溯重写旧修订；人类可明确选择旧的完整修订。文档显示选定 ID、修订、hash、政策和历史语义，不冒称当前任务已经全部完成。若业务要求正式批准必须引用当前状态，应另建版本化审批合同，不能在本档案隐式加入“最新指针”。

## 3. 报告、复测与原子性

报告最多十个组件，每组件一份明确来源，不跨组件平均或拼接总体正确率；保存完整模板/版本/hash、组件摘要、固定 Markdown 与独立来源承诺。修订只追加，禁止一个父修订产生两条后继。旧档案打开不重新渲染当前模板。

复测两侧必须是不同 run/计划/规范化版本，执行时间严格不重叠，冻结 QA/修订/hash、schema/criteria、映射、模式、全预算及独立政策相同，逐样本 ID/顺序相同。保存 PASS→PASS / PASS→FAIL / FAIL→PASS / FAIL→FAIL、两侧任务承诺及全量分母差值。不同明确评估修订可对同一 run 对另建比较；唯一键绑定项目与两侧 assessment ID，不追随当前意见。

重验证、hash 和渲染在线程中运行。最终事务按项目锁 → 排序 run 锁 → 所有来源整快照重读；档案和逐 run 审计原子追加。相同 ID/请求返回原收据，不同请求冲突。未知写入只显式 GET **同一 ID** 对账，不自动重发或换 ID。

## 4. API 与权限

路径均在 `/api/evaluation/projects/{project_id}` 下：

| 方法      | 后缀                                        | 行为                              |
| --------- | ------------------------------------------- | --------------------------------- |
| GET       | `/independent-report-templates`             | 固定独立双语模板                  |
| GET       | `/independent-report-archives`              | 最多 100 份公开元数据，不返回正文 |
| GET / PUT | `/independent-report-archives/{archive_id}` | 显式历史打开 / 新建不可变草稿     |
| GET       | `/independent-retest-archives`              | 最多 100 份比较元数据             |
| GET / PUT | `/independent-retest-archives/{retest_id}`  | 显式历史打开 / 新建不可变比较     |

全部端点要求已认证 owner + human + read/review，写入再要求 write 及严格布尔 true 的独立确认。沿用 bounded 私有校验与 `private, no-store`；不在错误中回显客户值、SQL、参考答案或密文。没有执行、敏感原件打开、更新、删除、自动通知端点。

## 5. 验证与交付门禁

- `test_qa_independent_archives.py`：历史修订、严格来源/类型、全分母/阈值、隐私 SQL、并发幂等、最终复查、审计回滚、事件循环隔离、篡改、多组件及不同评估修订的比较。
- `test_qa_independent_archives_router.py`：七端点、owner/human/read/write/review、固定模板、确认/输入边界、隐私、未知写入 GET-only、旧档案隔离。
- `test_qa_independent_archives_migrations.py`：临时 SQLite/独占 PostgreSQL 数据库、eval_0011→head→降级→再升级、metadata parity、索引/FK/unique、所有旧表数据/真实合成复核历史/账号/旧档案及 Harness ledger 保全。测试库按确切 UUID 创建和删除，不迁移提供的共享库。
- 既有 owner 报告/复测与所有历史迁移回归继续执行。完整套件结果另记在[交付矩阵](DevPilot_Delivery_Status.md)，失败与修正日志都保留；定向与全量不得相加。

**未交付**：独立 DOCX/PDF、正式批准、真实多账号端到端验收、备份后升级与用户最终验收。远端 CI 须按实际推送 SHA 单独核验，不能外推旧记录。旧 `qa-docx-v1` 不静默接受新 schema。没有新依赖、模型/目标请求、生产 key 或自动执行策略变更。

## English contract summary

This backend/API and explicit workspace candidate pins immutable historical independent assessment IDs, revisions and integrity receipts in separate report/retest tables. It does not replace owner-review namespaces or reinterpret historical hashes. ALL frozen effectiveness samples remain the denominator; complete FAIL outcomes and unmet frozen criteria are retained, while provisional or uncertain assessments are ineligible. Selection never follows live task state or the latest assessment automatically.

Only public archived commitments and bounded frozen metadata are read, not Q/A, gold, owner votes, live decisions or encrypted payloads. Verification/rendering/hashing run off-loop; final project/ordered-run locks recheck complete source snapshots before atomic archive/audit append. Unknown writes reconcile by GET of the same ID, never automatic resend. Human owner read/review and additional write/explicit confirmation are mandatory. Every artifact remains a draft and not approved. No execution, new export renderer, formal approval, production migration or real target/model call is added.

## 6. 前轮后端离线验证结果（2026-11-09）

变更后完整后端：**12,284 passed / 26 skipped / 11 deselected / 40 warnings，593.12s**；最终定向 **104 passed，86.21s** 与全量重叠，不相加。两组纯领域测试另为 **15 / 58**；Ruff check 与 format **1,237 文件**通过。整个 frontend Prettier 和相关文档检查通过，但本轮没有重跑前端单测/浏览器/生产构建。

测试只使用既有 Docker CI、独占源码快照、合成数据/key 及独占 UUID PostgreSQL 测试库；不复制私有配置或业务数据库。运行/测试源码与快照逐项 hash 一致，后补文档单独检查。保留红灯/中间失败与修正后通过日志于 ignored `.deer-flow/verification/20261109/evidence/independent-archives-v2/`。这不替代远端 CI、生产升级、真实多账号联调、正式批准或用户验收；Docker 资源收尾另见运维记录。

## 7. 显式历史来源工作区（2026-11-09）

在 `/workspace/reports` 与 `/workspace/retests` 新增独立区块；旧 owner 自复核流程保留，不静默替换其来源或 Word 下载。

1. 显式加载项目、运行和档案。选择运行后，再显式加载评估修订元数据，明确选择并打开某个历史 ID；不默认最新修订、不自动读当前任务或证据。
2. provisional 可查看但不能加入来源。完整的旧修订即使后续任务重开仍可选择；UI 明示历史语义、ID/修订/hash、固定政策、ALL 样本与 `not_approved`。
3. 报告明确选择最多十个不同组件、标题和独立固定模板；打开旧档案后可将其用作下一修订的父档案。复测分别固定 baseline/retest；服务端仍负责冻结基准、预算、版本与时序最终验证。
4. 创建前需要独立确认。编辑/刷新撤销确认；同步页内 Map 在 await 前保存待核对 ID，项目/语言切换不丢失。ref 写锁阻止双击，epoch 隔离迟到或卸载后的响应。
5. 未知 PUT（包括 404、无效或被替换收据）只保留同 ID 的显式 GET 对账，绝不重发或自动换 ID。成功收据必须绑定原来源及父档案 root/revision。
6. 严格 DTO 校验命名空间、模板、完整来源、复测逐项决定/hash/任务承诺、转移总数、ALL 分母差值和 benchmark schema/criteria/preflight 的内部一致性。浏览器不重做阈值引擎，也不把结构或 hash 校验冒称外部签章/密码学验真。
7. 已存 Markdown 作为纯文本显示；显式下载固定 Markdown/JSON，复测仅 JSON。独立 Word/PDF 尚未实现，不调用旧 DOCX 路由。所有 UI 数据仅在页内，不写敏感浏览器持久缓存。

测试使用合成 fixture 和拦截 API；不等于真实后端联调、多账号授权验收或部署。报告页既有只读 `GET /api/reports/assistant` 能力查询被单独模拟允许；advisor POST、证据/金标/当前任务与执行请求仍被禁止。测试文件：

- `independent-archive-policy.test.ts`：严格命名空间/全分母、来源与父修订绑定、复测承诺/差值/基准自洽。
- `independent-archive-panel.dom.test.tsx`：显式读取/确认、provisional 拒绝、双击/未知写入/404/跨项目迟到响应及替换收据。
- `independent-archives.spec.ts`：桌面/手机的明确历史修订、键盘确认、文字安全、下载和敏感请求禁止。

## 8. 本轮前端验证结果（2026-11-09）

本轮 lint/typecheck、生产构建及完整前端 Prettier 门禁分别通过。最终单测 **1,164 passed / 148 文件**；完整模拟浏览器 **214 passed，零自动重试**；独立登录恢复 **2 passed，零自动重试**。归档定向 **12 项单测 / 4 项浏览器**与上述全量重叠，不相加。

浏览器测试曾发现手机长按钮溢出，修复后重建生产前端并全量重验；首次错误日志与回归红灯均保留。报告页既有只读能力 GET 的误报已校准，advisor POST 与敏感/执行请求的禁止断言保留。后端本轮未重跑：逐一复核 **1,267 份 backend 非 Markdown 文件**与前轮 12,284 passed 的测试源码 manifest 相同；这不是新增后端测试结果。

证据位于 ignored `.deer-flow/verification/20261109/evidence/independent-archive-ui/`，包含失败/修复后日志、源码与导出 hash 收据。只有精确推送 SHA 对应的 Actions 才能证明远端 CI；不把前轮结果、提交或推送成功等同于 CI/部署/真实多账号验收。候选 `eval_0012` 仍未部署，业务运行保持 `eval_0009`。
