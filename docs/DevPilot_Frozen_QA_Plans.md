# DevPilot 冻结 QA JSON 评测计划

更新：2026-11-08。范围：**后端持久化/API 与逐样本预检**，不是运行器、调通证明、验收或报告证据。

## 为什么需要单独冻结计划

保存 cURL 请求版本只保存接口定义；冻结数据集只锁定样本与参考答案。真正的可复现评测还要固定两者的组合、输入/输出字段、模式与预算，不能在运行途中读取随意改变的页面表单，也不能将历史库存快照当作执行授权。

本轮将这些设置组合成 `qa-json-plan.v1`。创建计划不会访问目标接口，不要求平台工作模型，不启动任何压测；实际 Worker 与独立启动确认仍待开发；后续 UI 切片已接入冻结确认与元数据浏览。此前保存的请求版本与旧组件效果/性能入口不会被自动替换。

## 已实现

- 本人项目支持多个组件；每个组件支持多个只追加计划版本。标签按 NFKC/空白/大小写规范化去重，修改设置必须新建版本。
- 服务端重取同项目/同组件的请求版本，比较客户端看到的受保护密文摘要，并重新验证认证加密上下文、请求结构与完整性。
- 服务端重取同项目已冻结 QA revision/hash；从独立参考表重算包含金标的完整数据指纹，缺参考、坏样本或版本变化均拒绝。金标仅用于完整性核验，**不传给请求映射器或目标组件**。
- `QAJSONBinding` 固定输入/输出路径；输入必须替换已存在的 JSON 字符串叶子。按样本 ID 字符串升序逐条生成临时完整请求，只保留输入样本数量和正文字节汇总，不保存或返回渲染后的秘密请求。
- 效果模式必须恰好覆盖全部样本一次；性能模式必须至少覆盖全部样本，以固定顺序循环到指定请求数。每个不同样本都实际预检，重复次数按该顺序计入 UTF-8 正文字节预算。
- 冻结 response mode、模式、并发、请求总数、单请求超时、总时限、正文总字节上限；记录样本顺序版本、人工复核策略、请求结构指纹和预检汇总，整体再计算确定性 SHA-256。
- 所有写入和审计同事务提交：请求内部解密审计、计划、计划冻结审计。映射/预算/唯一约束/审计失败均回滚，不留下半成品。
- 加密、数据指纹重算和逐样本渲染通过 `asyncio.to_thread` 离开事件循环。公共列表/详情/审计查询不读取样本、金标或请求密文，读取不要求密钥。
- 创建需要 `evaluation_projects:write` + `review`、明确 `confirmed: true`，拒绝内部 Agent 代替人确认。列表/详情需要 read，审计需要 review；认证与 owner 隔离保留。

## API

```text
POST /api/evaluation/projects/{project_id}/components/{component_id}/plans
GET  /api/evaluation/projects/{project_id}/components/{component_id}/plans
GET  /api/evaluation/projects/{project_id}/plans/{plan_id}
GET  /api/evaluation/projects/{project_id}/plans/{plan_id}/audit
```

合成请求示意（ID/hash 由实际读取的元数据替换）：

```json
{
  "version_label": "QA baseline v1",
  "request_version_id": "request_version_id",
  "request_protected_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "dataset_id": "dataset_id",
  "dataset_revision": 2,
  "dataset_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "binding": {
    "schema": "qa-json-binding.v1",
    "input_pointer": "/messages/0/content",
    "output_pointer": "/choices/0/message/content"
  },
  "response_mode": "json_text",
  "limits": {
    "mode": "effectiveness",
    "concurrency": 2,
    "request_count": 100,
    "timeout_ms": 30000,
    "wall_time_ms": 300000,
    "max_total_body_bytes": 1048576
  },
  "confirmed": true
}
```

上述效果请求仅在数据集恰好有 100 条时满足覆盖条件。数字为合成配置示例，不是客户历史指标或平台实测结果。

参数边界：效果并发 1–8，性能并发 1–64，请求数 1–10000，超时 100–300000 ms，总时限不短于单请求超时且最多 3600000 ms，正文汇总最多 64 MiB；QA 最多 500 条。总字节仅计算映射后请求正文，不是全 HTTP 线上流量、响应预算或云账单上限。时限是未来执行截止预算，不保证所有请求都能在该时间成功完成。

验证错误和预检错误使用通用 422，源版本/完整性冲突为 409，无权/错误归属为 404，加密密钥缺失、错误或认证失败为通用 503。响应 `private, no-store`，不回显输入、金标、URL路径、凭据或底层数据库错误。

## 不做出的承诺

- `scope=frozen_definition_only`：人工确认的是**冻结定义**，不是执行批准；不声称请求已调通、模型输出有效或效果/性能通过。
- 无 PATCH/DELETE/open/execute 路由，无调度触发、耐久 Worker、实时进度、自动裁判、报告引用或独立脚本导出。后续前端切片已增加[显式计划确认界面](DevPilot_Frozen_QA_Plan_UI.md)，仍不启动执行。
- 输出路径仅进行语法校验；没有真实响应，不能证明该字段实际存在。后续 Worker 必须校验 HTTP 状态、截断和响应模式，字段缺失或坏 JSON 记技术失败，不忽略失败分母。
- 仅支持 QA JSON 文本；不支持 SSE/CV/文件、TTFT 或 token 吞吐计算。非流式接口不伪造 TTFT；TPS 需要明确可信 token 计数来源。
- 指纹是完整性校验，不是数字签名、独立审批或运行时授权。数据库管理员仍可修改底层数据，服务层只追加并在读时校验；不宣称硬件不可篡改存储。
- 元数据中的标签、路径、ID仍可能有业务语义，不称完全匿名。公开仓库仅使用合成示例，客户材料/名称/历史指标/配置/数据库/备份不上传。

## 迁移与本地升级

新增 `eval_0004`，不修改已部署 `eval_0001/2/3`。新增计划/审计表和请求同组件复合唯一索引；复合外键在数据库层阻止跨项目、跨组件请求绑定。Harness ledger 不变。升级前做不覆盖旧备份的 SQLite 在线备份，升级后核对原账号完整行、已有评测行、配置哈希、数据卷及无关服务。

创建计划需要先保存加密请求，因此仍需独立运维密钥 `DEVPILOT_REQUEST_ENCRYPTION_KEY`。本轮不生成密钥、不改用户配置；当前本地缺模型与该密钥，不能声称真实组件或计划创建已验收。SQLite 回归不等于真实 PostgreSQL 交付验收。

## 验证和后续

TDD：先实际运行缺模块红灯，再运行缺路由 404 红灯，再实现。定向覆盖 DTO 严格性、完整冻结定义、固定顺序与预算、线程隔离、篡改拒绝、无密钥元数据读取、跨 owner/project/component、事务回滚、旧 eval_0003 无损升级与 Harness ledger 保留。本地全后端回归 **11640 passed / 73 skipped**（39 条依赖弃用/测试环境警告），定向组合 118 passed，纯领域两组分别 15/58 passed；全后端 Ruff 与格式检查通过。前端本轮未改源码，格式、ESLint 与类型检查重新通过，未冒称重新运行完整浏览器套件。

2026-11-08 已先做 SQLite 在线备份并检查完整性，再仅更新 Gateway；Frontend 保持上一轮已更新镜像。核对原账号完整行、已有评测数据、配置哈希、挂载与无关服务身份不变，Harness ledger 不变，App ledger 从 eval_0003 追加至 eval_0004。运行源码 6 文件 hash 一致，真实入口对所有已有账号的助手、手动配置弹窗、五主题、请求元数据和新计划只读路由检查通过；未调用模型、保存助手或创建业务数据。当前仍未配置模型与请求加密密钥。GitHub Actions 需在提交后按完整 SHA 另行核验，不将本地结果当作 CI 结果。

后续顺序：计划确认 UI → 独立启动审批/目标授权 → 耐久 Worker（租约、重启恢复、取消和不确定请求处理）→ 不可变逐条观测 → Q/实际A/预期/来源/技术错误人工复核 → 版本化报告证据与整改复测。Worker 接入前还需补齐重试/重复发送、响应预算和版本化运行指标契约，不能直接调用内部解密函数代替执行准入。

## 后端提交的 CI 核验

完整 SHA `08bd0e616a422cd1f98a0d8c8179d15d2e714e53` 实际触发的五项均已 success：Unit Tests、Frontend Unit Tests、Lint Check、Backend Blocking IO、Replay E2E (front-back contract)。普通 E2E Tests 因该提交未改 frontend 路径而未触发，不记作已通过。后续 UI 提交须按新 SHA 重新检查。
