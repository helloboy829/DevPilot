# DevPilot 项目与 QA 数据最小闭环

## 后续切片说明：组件/提测库存绑定（2026-11-07）

本文记录 eval_0001 的 QA 基础；当前 App head 已通过新增 eval_0002 升级，旧迁移不改写。[项目组件与提测清单](DevPilot_项目组件与提测清单.md)支持关联安全组件库存与同项目 frozen QA revision/hash。它不执行测试，不读取请求凭据，不把用途标签变为验收结论；运行、结果复核和报告证据关联仍待完成。

日期：2026-11-07。本文描述本次实际实现，不代表完整 I1 数据治理或自动化评测闭环完成。

## 1. 本次能做什么

入口 `/workspace/datasets`，导航“项目与数据”。

1. 评测者创建本人项目。
2. 登记数据集名称、用途 `baseline` / `acceptance`、来源名称/引用、授权依据，并主动确认来源声明。引用只保存为文字，不访问文件或远端。
3. 粘贴 JSON 数组或 JSONL，整批替换草稿。服务端校验全部通过才事务提交，任何错误不部分导入。
4. 主动加载已保存的输入 Q、预期答案、来源与切片，并排检查；金标读取需要单独 review 权限并记录操作。
5. 勾选确认，以 revision 和内容 SHA-256 冻结版本。服务端重新计算持久行 hash；空数据、过期版本、hash 不一致或已冻结均拒绝。
6. 冻结后只读；纠错请另建数据版本，不覆盖旧版。可查看创建、替换、金标读取和冻结的元数据操作记录。

**冻结只代表用户确认该数据快照，不代表正确金标、来源授权已被核验、正式独立审核通过或测试验收通过。** 当前允许本人自审，尚无复核任务领取/双人审核/仲裁。用途是数据标签，未接执行模式/验收门禁。

## 2. 输入格式与界限

仅使用合成示例：

```json
[
  {
    "sample_id": "q1",
    "input": "Synthetic question",
    "expected": "Synthetic reference answer",
    "source_ref": "record:1",
    "slice_tag": "default"
  }
]
```

- `sample_id`：1..80 位 ASCII 字母、数字、下划线或短横；版本内唯一。
- `input` / `expected`：非空文本，各最多 10000 字符；`source_ref` 必填，最多 500 字符；`slice_tag` 可省略，默认 `default`，最多 80 字符。
- 最多 500 条，内容最多 **500000 UTF-8 字节**（十进制 500 KB）；外层 HTTP 请求上限 3100000 字节，兼容 JSON Unicode 转义开销。
- JSON 不允许重复 key、NaN、Infinity；拒绝非对象记录、未知字段、空金标、重复 ID 和规范化后相同的问题。规范化为 NFKC、空白折叠和 casefold，不是语义近重复检测。
- 导入是**全量替换**而非追加；成功后清空页面原文，必须重新读取持久样本再确认。当前为粘贴输入，无文件上传/逐条标注编辑器。
- 此最小 QA 契约即便 BASELINE 也要求预期答案；无金标调试/采集继续使用原有入口，不可借此宣称验收通过。
- 前端编辑待导入内容会隐藏旧金标、撤销确认；切换项目/版本、重载或错误也撤销确认。并发冲突为 409，需重新加载并审核，不静默重试冻结。

## 3. 实际 API 与授权

公共前缀：`/api/evaluation/projects`；以下 `/{project_id}` 均在该前缀之下。

| 方法 / 路径 | 权限 | 结果 |
| --- | --- | --- |
| GET /；POST / | read / write | 列出本人项目 / 新建 |
| GET /{project_id}/datasets；POST 同路径 | read / write | 列出版本 / 创建空草稿和来源声明 |
| GET /{project_id}/datasets/{dataset_id} | read | 版本元数据，不含金标 |
| GET .../samples | read | 输入与来源，不含 expected |
| PUT .../samples | write | `{revision, format, content}` 全量替换草稿 |
| GET .../references | review | 显式读取 Q/金标/来源，并记录 references_read |
| POST .../freeze | review | `{revision, content_hash, reviewed:true}` 人工确认冻结 |
| GET .../audit | review | 仅操作元数据，不含 Q/答案 |

权限全名分别为 `evaluation_projects:read` / `:write` / `:review`，与旧聊天权限分离。启用 RBAC 时需明确授予；沿用底座默认授权关闭模式时，已认证用户获得完整路由权限，但 owner 校验仍不可绕过。全部子资源均校验当前用户与项目/版本归属；没有团队共享或管理员跨项目读取入口。

401 未认证；403 缺权限/受信任内部 Agent 禁止动作；404 不存在或不是本人资源；409 版本冲突/空版本/已冻结；413 过大请求；422 格式错误；503 持久仓储未启用。敏感响应 `private, no-store`，校验错误不回显提交值。来源声明和审核确认仅接受 JSON 布尔 true，不接受数字 1 或字符串替代；数据库异常转换为稳定503，当前路由不记录SQL异常原文或参数。认证用户持有合法凭据的外部自动化无法被可靠区分为真人，不能把勾选框宣传为真人身份证明。

## 4. 分层、持久化与迁移

- `devpilot.datasets`：纯标准库 JSON/JSONL 校验、问题规范化、canonical SHA-256，无 App/Harness/模型依赖。
- `app.evaluation`：严格 DTO、owner 仓储、自有表和迁移。Gateway 只提供认证/权限、大小限制与错误映射；没有数据 Agent 工具入口。
- 实际表：`evaluation_projects`、`evaluation_datasets`、`evaluation_samples`、`evaluation_references`、`evaluation_data_audit`。金标是独立表，但仍在同一数据库，**不是独立加密或数据库管理员隔离**。
- 与现有持久库共用 SQLAlchemy session factory；独立 Alembic 版本表 `devpilot_alembic_version`，当前 revision `eval_0001`。不复用/修改 Harness 的 `alembic_version`，也不修改 LangGraph 表。Harness autogenerate 排除 App 表及其索引/约束。
- Gateway 持久模式启动时在线程中执行版本迁移，避免同步 Alembic 阻塞事件循环；进程内序列化 Alembic代理。SQLite迁移使用 BEGIN IMMEDIATE，PostgreSQL事务 advisory lock 并沿用 postgres_schema/search_path。
- SQLite 文件库已回归验证。PostgreSQL代码路径和参数转发有测试，**尚未完成真实 PostgreSQL 服务集成验收**。memory模式不创建临时替代库，接口返回503；SQL echo配置为true会拒绝初始化此业务，防止内容进入SQL日志。
- 草稿更新/冻结使用 revision compare-and-swap；数据和操作记录在同一事务。hash含来源声明、用途及按 sample_id 排序的完整规范化样本，不受输入数组次序影响；格式标识固定为 `qa-dataset.v1`。
- hash不是签名，操作记录不是不可篡改账本。备份、数据库磁盘、APM、第三方日志及管理员访问仍需运营方控制。本次没有新增保留期限/删除/脱敏自动化。

## 5. 部署和回退

升级前由运营方备份既有数据库/卷；迁移属于加表，不重置账号、运行数据或模型配置。新代码启动失败应停止排查，不能降级为内存后继续接收数据。回退应用镜像可保留新增表与独立版本表；**不要执行 destructive downgrade 或删除数据卷**。未来 schema 修订需新迁移和兼容性检查，不能修改已经部署的 eval_0001。

前端页面不使用 localStorage、聊天记忆或持久 Query 缓存；参考答案只有显式请求后保存在页面内存并按文本渲染。这不代表浏览器/服务端/备份无其他残留，仍应遵循最小权限和数据分级。

## 6. 尚未接通与下个切片

- 项目与既有组件、提测版本、执行计划、报告项目字段尚未建立外键关联，不能把同名当成同版本。
- 尚无 Agent 构建数据、CV资产/标注、质量卡、近重复/跨集泄漏检测、分组隔离、独立双人审核和冻结批准流程。
- 本页审核的是数据集，不是实际模型输出的结果复核中心；后者需要 Q / 实际 A / 预期 / 证据 / 自动判定 / 人工裁决及理由并排。
- 冻结版本尚未提供给效果/性能执行器，现有定时任务仍使用其原有样本快照，不自动引用新数据集。
- 报告仍为人工指标草稿，不能因为出现项目表就宣称已引用可信结果或持久报告。

下一步优先建立项目/提测组件版本关联和统一 RequestSpec，再将冻结数据引用接入耐久执行与逐条观测，之后做实际结果复核和证据引用报告。安全、出站、负载与验收门禁继续依照总体计划，不因本切片而豁免。

验证记录见 [CI与隔离环境记录](DevPilot_CI修复与隔离开发环境.md)；完整目标契约见 [数据集与指标规范](DevPilot_数据集与指标规范.md)，进度见 [实现矩阵](DevPilot_实现进度与下一步.md)。所有测试和文档示例均为合成数据，不含客户名称或历史业务指标。
