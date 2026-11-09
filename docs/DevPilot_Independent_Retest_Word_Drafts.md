# 独立历史重测 Word 草稿 / Independent historical retest Word drafts

> 2026-11-09。独立候选模块；不是部署、正式批准或真实用户验收。App migration head 仍为 `eval_0012`。无新增依赖、迁移、生产配置或执行开关，不改变旧档案/hash、旧 `qa-docx-v1` 或 `independent-qa-docx-v1` 的文档语义。

## 1. 为什么是单独的导出合同

独立重测档案保存结构化比较事实，**没有存储 Markdown、模板或报告修订号**。本模块不伪造报告档案，不声称“只导出存储 Markdown”，也不从当前评估或模板重建事实。新 renderer `independent-retest-docx-v1` 是存档公开事实的**固定双语投影**：格式和字段白名单由本版本代码冻结；改变其语义必须使用新版本 ID。

- GET `/api/evaluation/projects/{project_id}/independent-retest-archives/{retest_id}/exports/independent-retest-docx-v1?archive_hash={viewed_hash}`。必须显式打开档案并使用已查看 hash，不默认 latest。
- 人类 owner + 项目 read/review；不需要 write。不授予 reviewer 项目成员权限、共享权限、执行或批准权，内部 Agent 不可用。
- 复用原有历史档案 GET 的 off-loop 完整性验证，再 off-loop 渲染。无需解密 key，不读当前 task/assessment/template、owner 票、Q/A、gold 或密文。后续重开、评估修订或 key 移除不改写旧文档。
- 展示存档项目/组件/时间、archive/benchmark hash、两侧 run/plan/summary 和 assessment ID/修订/hash、完整样本分母、存档计数/技术状态/通过率及冻结 criteria/status、同基准预算/映射、存档转变计数/差值，以及 **ALL 冻结样本**的 sample ID、ordinal、两侧结果/case hash/公开 task-round-resolution 收据。
- 不重算通过率、差值或 criteria 判定，不加入任何批准结论。完整性/样本数/来源镜像的防御校验只是拒绝不一致文档，不替换原始数字或重新生成评估。v1 无 criteria 的来源保持无 criteria，不自动补默认阈值。
- 只选取固定公开字段；未知扩展字段不进入文档。名称、标签、指针和 URL 是字面文字，不解释为 HTML/Markdown、图片或外部链接。中英说明始终包含 DRAFT / NOT APPROVED；哈希不是外部签章。

## 2. 有界文档与错误

- 完整样本总体 1–500 个样本，ordinal 连续、sample ID 不重复、两侧来源/样本/任务承诺一致、历史独立来源完整；不以分页、已通过子集或截断掩盖缺失。
- 有效 XML 字符；单文字字段最多 200,000 UTF-8 字节，公开投影最多 2,000,000 字节，OOXML 部件合计最多 4,000,000 字节，最终包最多 524,288 字节。超出任一限制拒绝整个下载，不截断。两侧任务收据合计最多 20,000。
- 标准库 OOXML，固定六个部件/条目顺序/ZIP 时间；重复导出相同字节。只复用报告 v1 中已冻结的低层 XML/样式/关系原语，未调用或修改其报告渲染器。无宏、嵌入对象、活动内容或外部关系。
- 成功响应使用精确 MIME、`X-DevPilot-Renderer`、`private, no-store`、`nosniff` 和固定文件名 `independent-retest-{id}.docx`。无需虚构 revision。
- 无/畸形 receipt 422，已查看 receipt 不符 409，未找到/无权限沿用既有隔离边界；档案完整性/数据库错误沿用通用错误。渲染拒绝只返回通用 422，不返回 attachment、敏感字段或异常细节；不重试。

## 3. 显式工作区下载

只有打开明确的独立历史重测档案后才显示下载按钮，使用独立 retest namespace/renderer，不走 owner 或 independent-report Word 路由。认证 fetcher 显式 no-store GET，校验 MIME/renderer、流式上限及 ZIP 前缀；这些校验不是外部签名或完整 OOXML 验真。

沿用页内 ref 锁、确认撤销、项目/语言/unmount 晚响应屏障。双击只发送一次，错误不自动重试；保留已打开档案。Blob URL 使用后释放；无持久敏感缓存、轮询或自动下载。原有 pending IDs、写入同 ID GET-only 对账、未知结果包括 404 不重发的规则不变。

## 4. 验证入口与证据边界

- `backend/tests/test_independent_retest_docx.py`：真实双语 OOXML、固定 fixture 字节、独立 MarkItDown 读取、全部 500 样本、来源/分母/字段白名单、文字安全、v1 无默认 criteria、存档值不重算和整体拒绝边界。
- `backend/tests/test_independent_retest_docx_router.py`：真实合成独立档案、off-loop/无需 key/当前来源、owner/人类/独立权限、已查看 hash、GET-only/命名空间、通用失败与旧导出隔离。
- 独立 API→Worker 合成回归增加重开后历史重测 Word 读取，无当前来源/key、无重发或额外 dispatch。
- 前端 API/DOM 覆盖精确 retest renderer、MIME/流/大小/错误、显式一次下载、锁/卸载晚响应/保留档案；模拟 Chromium 以真实生成 fixture 检验桌面/手机、键盘、字节/文件名、无敏感请求和失败不重试。

本轮精确结果记录在[交付矩阵](DevPilot_Delivery_Status.md)。失败日志与最终结果保存在 ignored `.deer-flow/ci/20261109-independent-retest-word/`，不提交本地配置、原始客户材料或容器快照。模拟身份/浏览器不等于真实多账号验收；CI push 不等于 CI 成功，须按完整 SHA 核验。

## 5. 排除项与回退

PDF、正式批准政策/角色/版本/撤回合同、真实多账号验收、保留业务数据的迁移/部署和平台最终验收仍未完成。无模型/目标调用、自动批准、通知或运行启用。历史部署收据不能当成本模块已部署；另行授权后才能升级。

回退本模块源码即可；没有数据转换。历史独立重测 JSON、旧 owner/独立报告 Word、模板和 hash 保持不变。不得通过弱化复核/分母/断言、放宽超时或重试绕过失败。

## English summary

A separate human-owner, read/review GET binds an explicitly opened historical independent retest receipt to `independent-retest-docx-v1`. Retest archives have no stored Markdown or report revision: this is a pinned bilingual, allowlisted projection of stored comparison facts, ALL frozen cases and both historical assessment commitments. Archived integrity verification and rendering are off-loop, without keys, current sources, metric/criteria recomputation or approval. Deterministic bounded OOXML has literal text and no active content/external relationships; exceeding any bound rejects the whole export, never a truncated population. The explicit authenticated frontend preserves locking, late-response fences, no-store and no-retry semantics. Existing archives/hashes and both report Word renderers remain unchanged. PDF, formal approval, deployment and real multi-account acceptance remain separate unfinished work.
