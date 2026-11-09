# 独立历史报告 Word 草稿 / Independent historical Word drafts

> 2026-11-09。候选模块，不是部署、正式批准或用户验收。App migration head 仍为 `eval_0012`；不修改旧 `qa-docx-v1` 的接口、渲染器、模板或存档哈希。

## 1. 合同与边界

- 独立 GET：`/api/evaluation/projects/{project_id}/independent-report-archives/{archive_id}/exports/independent-qa-docx-v1?archive_hash={viewed_hash}`。必须显式打开档案并提交已查看的收据 hash；不默认 latest。
- 人类 owner + 项目 read/review 权限；无需 write 权限。其他账号无档案可见性，内部 Agent 不可下载。此接口不授予项目共享、执行或批准权限。
- 只从独立档案表读取不可变 document，复用原有 off-loop 完整性验证，再 off-loop 渲染。无密钥要求，不重开当前任务/评估、不读取 Q/A、gold、密文或 owner 票、不查询当前模板、不重算指标。
- `independent-qa-docx-v1` 单独冻结渲染语义。支持独立中/英文 `1.0.0` 档案；只接受完整历史独立来源。Word 包含存档 Markdown、草稿警示、档案/模板/Markdown hash，以及每个来源的 run、assessment ID/修订/hash、summary hash。hash 是完整性承诺，不是外部签章。
- 存储 Markdown 的表格/标题转换为有限 OOXML；HTML/URL 只作为文字，不创建图片、链接、外部关系、宏、嵌入对象或活动内容。固定 ZIP 条目时间和顺序，重复下载字节一致，不改变历史档案。
- Markdown 上限 200,000 UTF-8 字节、5,000 行，每表最多 16 列；XML 字符必须有效；文件上限 524,288 字节。拒绝畸形表格、错误命名空间、非法收据或不完整来源，错误不回显私密内容。
- 响应 `private, no-store`、`nosniff`、固定安全文件名和精确 renderer header。错误不返回 attachment；收据变化 409、内容不可渲染 422、完整性/数据库错误沿用通用失败边界。无自动重试。

## 2. 工作区

独立报告区块只有在明确打开一个历史档案后才显示“下载独立历史 Word 草稿”。通过既有认证 fetcher 显式 GET，核验 MIME、独立 renderer、流式大小和 ZIP 前缀；不能把 HTML 登录页、旧 owner renderer 或错误响应保存为 Word。客户端结构校验不是 OOXML/签名验真。

页内 ref 锁阻止双击，下载过程撤销写入确认；卸载或项目/语言范围变化后丢弃迟到响应。Blob URL 用后撤销，不写持久浏览器缓存。原来的 pending ID Map、同 ID GET-only 写入对账和旧 owner Word 下载保持不变。

## 3. 验证入口

- `backend/tests/test_independent_report_docx.py`：真实 OOXML、中英文/多组件来源、确定性 fixture、独立 MarkItDown 读取、边界/命名空间/不完整来源拒绝和无活动内容。
- `backend/tests/test_independent_report_docx_router.py`：off-loop、无需密钥/当前来源、权限/owner/人类、已查看 hash、只读与隔离命名空间、通用错误和旧 Word 字节兼容。
- 前端 API/DOM 回归：独立 renderer、流式大小/错误、显式下载、双击、迟到响应与无重试。
- `frontend/tests/e2e/independent-word.spec.ts`：桌面/手机真实 fixture 下载、键盘、固定文件名/字节、文字安全、敏感请求禁用与 409 不重试。fixture 的所有字段和 Word 均为合成，不含客户材料。

本轮测试结果和精确提交/Actions 另记[当前交付状态](DevPilot_Delivery_Status.md)。未运行的门禁不算通过；模拟浏览器不是真实多账号授权联调。源码、失败日志和收尾收据保留在 ignored `.deer-flow/ci/20261109-independent-word/`，不提交本机证据或配置。

## 4. 未交付与回退

独立复测 Word、独立 PDF、正式批准、真实多账号联调、保留数据升级和最终用户验收仍未完成。无新增依赖、迁移、生产配置、key、执行开关或真实模型/目标调用。回退只需回退本模块代码；没有数据转换，已有历史档案与旧导出继续保留。

## English summary

A separate pinned human-owner GET exports an explicitly opened immutable independent report, bound to the viewed archive hash. It verifies the archived document and renders off-loop, without current templates, evidence decryption, live review state, metric recomputation, models, targets or approval. Deterministic bounded OOXML contains stored Markdown and public historical receipts only; text never becomes active content or external relationships. The authenticated frontend validates the bounded binary response, fences late downloads and never retries automatically. Legacy owner-review archives and `qa-docx-v1` remain unchanged. Independent retest Word/PDF, formal approval, real multi-account acceptance and deployment remain outside this module.
