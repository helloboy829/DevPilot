# 不可变平台 QA 项目报告草稿 / Immutable QA project report drafts

**后续追加（2026-11-08）：** 现在可从历史存档显式下载 [固定 Word 草稿](DevPilot_QA_Word_Draft_Export.md)，无新迁移、不重算指标、不自动批准。本文原切片中的未支持 DOCX 说明保留为历史范围。

日期：2026-11-08。范围：真实平台证据引用、一个项目多个组件、模板版本冻结和追加修订。**不是正式报告审批或平台整体完成。**

## 产品流程

`报告 → 平台结果 → 多组件报告存档`：

1. 明确加载本人项目，再加载运行、模板和最近 100 条历史存档；初次打开不读取平台证据。
2. 选择效果运行，点击验证汇总，检查组件 / 计划 / 人工通过数与全部冻结样本分母 / 汇总标识。
3. 每组件添加一个完整复核运行，最多 10 个组件。不把未复核、待确认或缺输出证据的运行当成完整结果；存在 FAIL 也能如实存档。
4. 填写标题，选择中英文模板的明确版本，独立确认不可变草稿存储。请求只提交运行 ID 与已看过的 summary hash，**不提交客户端指标或渲染正文**。
5. 服务器重新验证证据与最新复核，冻结每组件摘要、模板全文与版本/hash、渲染 Markdown 和存档 hash。同一事务写入报告与每运行审计。
6. 打开历史草稿、下载服务器已存储的 Markdown；选择它作为修订来源，再添加/验证所需组件并创建新记录。旧版本不覆盖，旧模板不需要仍存在于当前目录中。

页面保留现有人工单组件 / 多组件填报、多轮 Agent 需求澄清和报告建议区；它们是**未验证草稿**，不得混入平台证据。报告 Agent 不参与数字计算、批准或写入本存档，也不自动调用目标或模型。以后接模型时应提供独立的建议/叙述修订与人工确认流程，不得让模型改写冻结事实。

## 指标与批准边界

- 固定分母：最新人工 PASS / 全部冻结效果样本。每组件独立保留分子、分母和精确值，不跨组件做简单平均。
- 仅 review_complete 且无 blockers 的效果运行可存档；重复性能请求不混算。
- 不是全部 PASS 检查、验收门槛检查、正式出具或审批。始终 acceptance: not_approved。
- 本轮没有性能/TTFT/TPS 报表、CV 图像执行、整改复测关系、团队复核、电子签章、DOCX/PDF、模板上传编辑或定时授权。
- 内置 verified-qa-project-{zh,en}@1.0.0 是脱敏的基础布局，不是客户历史报告原件或其指标副本。

## API 与权限

项目路径：`/api/evaluation/projects/{project_id}`。

| 方法与相对路径 | 用途 |
| --- | --- |
| GET /report-templates | 当前双语模板目录 |
| GET /report-archives | 最近 100 条元数据，无正文/样本/敏感证据 |
| GET /report-archives/{archive_id} | 校验并读取原样冻结的历史文档 |
| PUT /report-archives/{archive_id} | 独立确认的新草稿或追加修订 |

全部限登录 owner + evaluation read/review，拒绝内部 Agent；PUT 另需 write。读写 private/no-store，错误不回显私密载荷。无 update/delete/自动发布路由。用户启用自定义助手并不授予它人工复核或报告存档的权限。

完整存档含项目/组件名称和汇总结果，属于私有项目数据，不能上传 GitHub。自动测试只用合成场景，日志不记录真实文档。

## 幂等、未知写入与并发

- 客户端先生成 32 位十六进制存档 ID，再发送一次 PUT；同 ID/相同请求返回同一收据，不重新读取当前模板或证据。不同请求冲突。
- 返回不明时保留 ID/原请求，禁止自动重试和新建写入，只提供明确 GET 同一 ID 核对。404/失败/不匹配不能当成没有提交，不自动换 ID。
- 页面内切换项目仍保留待核对 ID；离开页面前提示保留它。没有浏览器持久存储，跨页面的完整恢复体验仍待后续实现。
- 所有 crypto 和源验证在事件循环外。最后锁定项目，再按运行 ID 有序锁定全部运行，重读完整源快照；期间有人复核或项目变化则拒绝创建，不保存旧数字。
- 修订串行追加：supersedes_id 同项目、只能有一个后继，每根修订号唯一，旧存档永不原地修改。
- 冻结内容使用完整文档 hash 校验；这不是外部数字签章，也不声称能抵抗有权同时改数据库内容和 hash 的攻击者。

## 追加迁移与本地服务

代码 App head 为 **eval_0008**，仅从 eval_0007 追加 evaluation_report_archives。不修改旧迁移或 Harness ledger。升级测试保留项目、加密请求、计划、派发、输出、人工复核和执行表，并验证重复升级。

本地最后核验仍是 **eval_0006**。本轮限权外只读 Docker 管理检查继续无响应；登录页 HTTP 200 不等于新版已经部署。未清空账号、配置或数据卷，未重启 Docker、切换上下文或改动无关容器。部署必须先恢复 Docker，再在线一致备份、只更新 gateway/frontend、核对账号/配置 hash/挂载/旧数据/Harness ledger/新 head 后才能宣告成功。

## 验证与后续

后端测试覆盖完整平台源校验、多个组件、同组件重复运行拒绝、跨项目拒绝、固定分母、历史冻结、修订分叉拒绝、幂等、模板消失后的读取、篡改检测、并发复核、事务回滚、权限和旧 head 迁移。前端 DOM 与合成浏览器测试覆盖显式读取、独立确认、多组件/移动端、修订、不执行 HTML、未知 PUT 同 ID GET、项目切换和迟到响应隔离。实测结果在提交前记录于进度文档；Linux CI 必须核对本轮完整 SHA，不能沿用上轮绿灯。

下一步：独立批准/正式出具、可恢复报告操作历史、整改复测证据链与独立定时准入；不能以本草稿归档替代这些门禁。

## English summary

Owner-only immutable project QA report drafts bind reverified server-side summaries to a full template version/layout and rendered Markdown. One complete effectiveness run per component, at most ten; failures remain honest, no pooled metric, performance/TTFT or automatic approval. Client-supplied metrics/Markdown are rejected. Explicit human consent, same-ID receipt reconciliation, ordered run locks, full snapshot rechecks and atomic audits prevent stale or ambiguous writes. Revisions append without overwriting history. Agents remain separate, unverified suggestion providers. App migration eval_0008 is additive; the last confirmed local deployment remains eval_0006 pending Docker recovery and a backed-up code-only update. This is not completion of formal reporting or the overall platform.
