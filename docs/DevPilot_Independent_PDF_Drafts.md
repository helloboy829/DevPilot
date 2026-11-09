# 独立历史报告与重测 PDF 草稿 / Independent historical PDF drafts

> 2026-11-09 候选模块。只导出已显式查看的不可变独立历史公开投影，不是批准、签章、PDF/A、PDF/UA、部署或真实多账号验收。旧 Word/Markdown/档案/hash 不变。

## 1. 固定来源与授权

- 报告：`GET /api/evaluation/projects/{project_id}/independent-report-archives/{archive_id}/exports/independent-qa-pdf-v1?archive_hash={viewed_hash}`。
- 重测：`GET /api/evaluation/projects/{project_id}/independent-retest-archives/{retest_id}/exports/independent-retest-pdf-v1?archive_hash={viewed_hash}`。
- 人类 owner、独立 read + review 权限、严格 ID/已查看 hash；未知版本/跨 namespace 不兜底。收据不符 409，无/畸形收据 422；沿用 owner 隔离和内部 Agent 拒绝。
- 仓库只读指定存档，完整性与渲染均 off-loop。无需当前 key，不开当前任务、评估、模板、Q/A/gold、秘密或模型。

`app.evaluation.independent_pdf` **只消费两个既有固定 Word-v1 renderer 内部生成的 document.xml**，不接受外部 DOCX/XML/HTML。复用原 namespace、字段白名单和 ALL 总体，不新建指标逻辑。报告保留存储 Markdown 的原固定文字/结构和历史收据，不按当前模板重渲染；重测没有 Markdown/revision，保留原固定双语公开比较事实、全部 case 与两侧任务承诺。

PDF 与 source Word renderer 收据同时保留，不互相冒充。源 renderer/字体/布局/引擎改变需要另发版本，不覆盖 v1；每页含 `DRAFT / NOT APPROVED — 草稿 / 未批准` 和固定 renderer/page footer。

## 2. 有界静态布局与文字安全

固定 A4/边距/字号/行距，按嵌入字体 glyph advance 线性换行，长 hash/CJK 不裁掉。等宽网格单元格可跨页续写；全部行/字段输出或整体拒绝。无 HTML 执行器、图片、URL 识别、网络、系统字体查找或外部资源；Canvas 只画文字/网格，不创建链接、注释、附件、脚本、表单或打开动作。

- 内部 XML 最大 4,000,000 bytes，投影文字 UTF-8 最大 2,000,000 bytes，最多 20,000 个顶层块。
- 最多 512 页，最终 PDF 最大 8,388,608 bytes；任一越界整体拒绝，不输出截断总体/部分文件。
- CRLF/CR 定义为 LF，Tab 为四空格；其他文字不归一化或替换。字库外 glyph、组合标记、控制/格式字符及需要复杂整形的 RTL/Arabic-number 文字整体拒绝，不静默丢字/方框。v1 支持固定字库覆盖的中英文字，不声称支持任意 Unicode/双向排版；原档案仍可读取或用其他已有格式导出。
- `reportlab==4.4.10` 固定 Canvas/TTFont、PDF 1.4、`invariant=1`、压缩和固定非敏感 metadata。线程锁串行化共享字体子集状态；每次校验引擎版本/字体 SHA。错误只返回通用 422，无异常详情/attachment/重试。
- 测试环境同输入重复/并发字节一致，不是跨任意 Python/zlib 的字节承诺、外部签名或批准凭证。无正式签章/可访问性标签。

## 3. 固定字体、许可和重建

字体、原许可/manifest 在 `backend/app/evaluation/export_fonts/independent_pdf_v1/`，不用可能受镜像排除规则影响的通用 assets 目录。上游 SIL OFL 1.1 和引擎 BSD 许可分别保留，不与项目许可混同。

| 项目         | 固定值                                                                       |
| ------------ | ---------------------------------------------------------------------------- |
| 上游仓库     | `notofonts/noto-cjk`                                                         |
| 上游 commit  | `f8d157532fbfaeda587e826d4cd5b21a49186f7c`                                   |
| 上游文件     | `Sans/Variable/TTF/Subset/NotoSansSC-VF.ttf`，2.004                          |
| 上游 SHA-256 | `d68bafcb48a2707749396aa12bbbd833cb70401f3a9a689fd2902c7e0d295964`           |
| 许可         | `Sans/LICENSE` 原字节复制为 `OFL.txt`                                        |
| 构建工具     | 仅隔离构建环境 `fonttools==4.61.0`，无运行依赖                               |
| 实例化       | wght=400，静态 TrueType，30,890 cmap 字符                                    |
| 衍生字体     | `DevPilot Export Sans` / `DevPilotExportSans-Regular`，保留版权/许可 records |
| 输出 SHA-256 | `3c7dfdf896efce570073376a39654dd98d4776fa9ecdbc0fe01c68418b190762`           |

`scripts/build_independent_pdf_font.py SOURCE.ttf DESTINATION.ttf` 不下载，不在启动时运行。单独核对上游 bytes 后用固定工具构建，固定 timestamp/weight/name/table 顺序，删除失效签名/变体描述并输出 manifest。已在两个输出目录重复构建并核对同 SHA。字体随应用/OFL/manifest 分发，不单售。原始可变字体/工具 wheel 仅留 ignored 研究证据，不打进运行环境。

## 4. 依赖可重现性

唯一新增运行依赖 `reportlab==4.4.10`，pillow/charset-normalizer 已在原锁中；不升级其他包。用 Dockerfile 固定的 **uv 0.7.20** 从原锁真实解析，保留锁格式兼容，并检查开发容器 uv 兼容性。

解析时原可选 `tenki-sandbox` 官方索引返回 404，但**原锁官方 0.4.0 wheel 仍可获取**。根 `[tool.uv.sources]` 绑定原 URL；真实解析锁保留同一 `sha256:76d5ece2e1607b43705587d86277e983ef43601a86993077e379be8033a40b3e`。不删 Tenki extra、不降低 Python 支持、不换 SDK/版本、不伪造 lock；默认安装未启用/调用 Tenki。无迁移、私有配置或执行开关改变。

## 5. 工作区显式下载

显式打开独立报告/重测档案后才显示各自 PDF 按钮，不从最新评估推断来源。认证 fetcher + no-store GET，校验精确 MIME/renderer、8 MiB 流上限和 `%PDF-` 前缀，拒绝登录页/空/中断/超大响应。前缀不是完整 PDF 验真/签名，生成器和独立读取器测试承担结构验证。

沿用 ref 锁、项目/语言/unmount epoch 屏障、确认撤销和 Blob URL 释放。重复点击只发一次；迟到响应不能跨 scope 下载；失败保留档案，只显示通用提示，不重试/持久缓存。未知写入仍只允许同 ID GET 对账，404 也不重发；下载不增加写入/执行授权。

## 6. 测试与排除项

- `test_independent_pdf.py`：PDFMiner 读取、PDFium 实际栅格/每页 glyph 边界、每个原 Word 文字节点完整保留、嵌入字体/ToUnicode、无 active content、确定性/并发/无输入修改、真实二进制 fixture、全部 500 样本/最终任务承诺、文字/引擎/字体/页数/bytes 拒绝。
- 表格默认阅读顺序可能按视觉行交错，另用独立读取器原始绘制顺序逐项精确核对完整文字，不删除总体/收据断言。
- `test_independent_pdf_router.py`：真实合成档案、权限/人类/owner/receipt/version/namespace/GET-only、off-loop、不读当前来源/key、通用失败/不重试；旧 Word 回归并跑。
- 前端 API/DOM：精确 namespace、MIME/renderer/签名/大小/中断、一次下载/锁/卸载屏障、错误保留档案。桌面 1440px/手机 390px 模拟浏览器用真实生成 PDF 校验键盘下载、完整 bytes/文件名、无敏感请求及 409 不重试。
- 完整门禁实际结果见[交付矩阵](DevPilot_Delivery_Status.md)。ignored `.deer-flow/ci/20261109-independent-pdf/` 保留初始失败/最终日志、来源、hash/测试回执；不提交配置、客户材料或容器快照。

无部署、模型/目标调用、自动执行/重试、批准、签章、通知、key、迁移或账号改变。正式批准政策/角色/生命周期、经授权保留数据升级、真实多账号和最终用户验收仍未完成；不能宣称整个平台完成。回退源码/依赖即可，旧档案/模板/hash 不变。

## English summary

Separate pinned PDF GETs consume only internal Word-v1 historical public projections of explicitly viewed independent archives. Human-owner read/review, exact receipts, off-loop verification/rendering and namespace isolation remain mandatory. A fixed engine and reproducibly built OFL font draw bounded literal bilingual text and ALL frozen populations, without current-source/key reads, HTML, network, system-font fallback, active content, silent substitution, metric recomputation or approval. Unsupported text or bounds reject the whole export. Explicit downloads preserve no-store, locks, late-response fences and no-retry. Existing archives and Word bytes/hashes are unchanged. Synthetic reader/raster/browser tests are not deployment or real-account acceptance.
