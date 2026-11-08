# 冻结 QA 报告的 Word 草稿导出

日期：2026-11-08。此切片基于不可变报告存档，不代表正式批准、完整报告产品或平台整体完成。

## 使用流程

1. 在「报告」的已验证平台报告区，选择项目，显式载入运行、模板和历史存档。
2. 完成效果样本人工复核后，可选择多个不同组件的完整运行，独立确认并存档草稿；也可直接打开既有历史版本。
3. 核对版本与存档哈希，点击「下载 Word 草稿」。Markdown 下载仍保留。
4. 下载的 `.docx` 包含标题、真实多组件 Word 表格、证据引用，以及中英文「草稿 / 未批准」标识和存档收据。

导出不发送被测接口请求、不调用模型、不创建数据库修订，也不会将人工填报或 Agent 建议混成平台实测结果。自定义助手对所有登录用户开放，但不因此获得人工批准或他人数据权限。

## 冻结和版本

- 输入只能是服务器重新校验哈希后的历史存档，不接收客户端正文/指标，不读取当前模板重新排版或重新计算分数。
- `qa-docx-v1` 固定渲染语义；修改转换规则必须引入新 renderer ID。模板版本、草稿修订与 renderer 版本是不同维度。
- 附录保留 archive ID、revision、template ID/version、archive hash、冻结 Markdown SHA256 和 renderer ID。
- 同一环境内 ZIP 时间和成员顺序固定，重复导出字节稳定；不承诺不同 zlib 版本之间压缩字节完全相同。
- 只转换冻结格式中的标题、小节、项目符号和表格；不支持任意 Markdown 插件、上传模板、宏、嵌入物或外部链接。

## API 与安全

`GET /api/evaluation/projects/{project_id}/report-archives/{archive_id}/exports/qa-docx-v1?archive_hash={viewed_hash}`

- 必须是登录的人类 owner，并有 evaluation read/review；不要求 write，内部 Agent 调用拒绝。智能体开启不改变此边界。
- 缺少/无效收据 422，已打开的收据与存档不符 409；篡改存档拒绝导出。只返回安全错误，不回显内容。
- 存档解码、哈希检查和 ZIP/XML 生成均在事件循环外。无文件写入、外呼或生产新增依赖。
- 限输入 Markdown UTF-8 200000 字节、5000 行、每表 16 列；拒绝非法 XML 字符和参差表格。
- HTML 只作为文本，XML 由序列化器转义；OOXML 包仅含文档、样式、属性和内部关系，没有外部 relationship 或活动内容。
- 返回 DOCX MIME、`private, no-store`、`nosniff`、固定安全附件名与 `X-DevPilot-Renderer`。
- 前端只在明确点击时请求；检查 MIME/renderer、流式上限 512 KiB 和 ZIP 前缀，拒绝登录 HTML/错误 JSON。前端检查不替代后端文档有效性验证。
- 下载期间锁定重复操作；组件卸载/项目切换后丢弃迟到响应。失败不生成文件，不改变已打开的冻结正文。
- 文档可能包含私有项目名称和指标，属于项目材料；不能提交 GitHub。仓库夹具完全合成。

## 验证与边界

后端测试覆盖真实 ZIP/XML 成员、表格、实体/中文、草稿/收据、独立读取器、输入上限、历史模板消失/移除运营密钥后的合法读取、权限、篡改和 off-loop。独立读取使用现有 Harness 的 MarkItDown/Mammoth，不为测试新增 python-docx 依赖。

浏览器测试使用真实 renderer 输出的**合成** DOCX，检查 1280/390 宽度的点击、下载名和完整字节，以及失败无文件。后端另比较该夹具全部解压 XML 部件，避免将伪造 `PK` 字符串冒充有效 Word。浏览器使用合成 API，不声称真实网关或人工 Office 验收。

待完成：独立审批/正式出具、PDF、脱敏空白客户模板精确字段映射、模板管理、跨页面恢复和整改复测证据链。此版本不是任意文件转换服务，也不承诺 Office/LibreOffice 视觉排版已经人工验收。App head 仍为 eval_0008，无新迁移。

本地 Docker 管理接口仍无响应，最后确认部署 head 为 eval_0006。没有更新容器；部署仍须先备份，再仅更新 gateway/frontend，核对账号、配置、挂载、旧数据和 Harness ledger。HTTP 200 不是新版上线证明。

## English summary

Explicit owner/human read-review access exports frozen archived QA drafts as DOCX through the pinned `qa-docx-v1` renderer. It preserves historical Markdown, real multi-component tables and receipt metadata without current-template lookup, model/target calls, metric recomputation or approval. XML/ZIP work is off-loop and bounded; there is no active content, external relationship, runtime dependency or migration. Browser downloads are explicit, bounded and scope-fenced. Synthetic API/browser tests and an independent existing reader verify structure and bytes; formal approval, PDF, arbitrary/customer template mapping and real Office visual acceptance remain out of scope. Local service deployment remains unverified pending Docker recovery and a data-preserving upgrade.
