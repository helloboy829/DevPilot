# 外部 QA 技术隔离接收工作台 / External QA technical quarantine workspace

## 范围 / Scope

在 /workspace/datasets 的独立面板显式接通既有 external-qa-intakes API，
不是上传外部输出、接受证据或证明外部运行成功。后端合同见
[持久隔离接收](DevPilot_External_QA_Quarantine.md)。一致甚至完全伪造的技术声明
仍为 **NOT_EVALUATED**；evidence、approval、dispatch、resume、resend 均为 false。

This candidate workspace consumes existing human/owner APIs. It adds no migration,
dependency, policy/grant enablement, model/target call or deployment. Candidate head
remains eval_0014; the historical eval_0009 receipt is not this machine's runtime.

## 显式流程 / Explicit workflow

1. 选择项目并填写准确历史 export ID；主动打开安全回执，再读取其冻结 plan。
   只允许完整 baseline_inputs，绑定数据/请求版本、hash、schema、ALL 样本、
   请求总体及冻结请求字节预算。当前 grant 过期不禁止另行授权的技术存档。
2. 填写原始规范 UUID，分别选择身份回执和对账 JSON。每份读前至多 8192 bytes，
   实际长度一致，fatal UTF-8，无 BOM；保留原空白并计算实际 bytes SHA-256。
3. 显式本地校验严格技术 schema、decoded duplicate keys、整数、层级、总体、
   状态/观测合计及预算。错误不反射文件正文或服务器敏感错误。
4. 分别确认准确来源/原 ID、仅含技术元数据、不可信且不授予任何权限；
   再显式 PUT。编辑输入/文件或执行其他操作均撤销三份确认。
5. 完整验证回执才展示不可变技术档案；原始 bytes hash 与 canonical hash 分开。
   哈希只校验完整性，不是签名，不能重新认证已丢弃原 bytes 或外部派发。

No automatic request, latest-source selection, grant/policy/bundle/key lookup,
software fetch, gold/output read, CLI execution, polling or retry is introduced.
Existing plans, owner/independent review and report/retest routes are unchanged.

## 未知结果与生命周期 / Unknown outcomes and lifecycle

- PUT 前在父页内存登记原 intake ID 和安全 expected metadata；不登记原文件或 PUT body。
  父页 cross-project write ref 和组件 operation ref 防重入。
- PUT 失败/未知、malformed success、后续 GET404 都保留原 ID；
  **仅显式 GET 同一 ID，不重发 PUT、不换 ID、不自动重试/轮询。**
- 项目/语言切换保留父页 pending，epoch、AbortSignal、文件 token 和异步 hash
  完成后检查阻止晚到结果恢复旧数据或清除新 scope 状态。
- page-memory 不是持久恢复系统；刷新/离开页面前需人工保留原 ID，之后显式打开历史。
  不写 localStorage/sessionStorage/IndexedDB，不持久缓存技术文件或敏感资料。
- PUT body 至多 32768 UTF-8 bytes，读响应时至多 262144 bytes；要求 JSON MIME、
  严格可选长度及 fatal UTF-8，有界流溢出取消并释放 reader。

Unknown writes never grant resend authority. Exact source, inspection, original
hashes, canonical hashes and byte lengths are checked again against pending
metadata. Ref locks remain held through asynchronous receipt-hash verification.

## 历史与审计 / Historical reads and audit

显式输入历史 intake ID，只读原隔离档案；不要求重新打开当前来源或查当前 policy。
审计逐页主动加载，每页至多 50 条，严格检查项目/intake、unique event ID、
连续 sequence 和 cursor；不以时间戳代替顺序、不自动读下一页。
存储文本用 React 文本节点及 pre 字面显示，不能用 Markdown/HTML renderer。

## 验证与交付 / Verification and delivery (2026-11-11)

- 前端专项：policy **20**、API **8**、DOM lifecycle **19**，共 **47 passed**；最终完整 **158 files / 1,359 passed**。ESLint/typecheck、整个 frontend Prettier 和九份公开指南格式均单独核验。
- 后端新增 **2 passed**：必跑的 committed fixture/source/parser/archive-hash 检查，以及真实合成 PUT → GET → audit、重复 PUT409 的夹具生成。网络替身和 socket fail-closed 生效，不读取私有配置或真实资料。最终联合 **257 passed**。
- 初始隔离后端基线 **13,332 passed / 19 skipped / 11 deselected / 40 warnings，1030.56s**；最终标准全量 **13,334 passed / 19 skipped / 11 deselected / 40 warnings，1391.03s**。领域 **15 / 58**、Blocking IO **72 passed**、Ruff **1,277 files**、offline lock 通过。
- 原六路由 normal/static-demo 两次性能构建和原预算通过；正常生产构建后专项 Chromium **6 passed**、完整 **242 passed**，独立 auth-enabled 生产构建后 auth recovery **2 passed**。全部本地浏览器命令显式 retries=0，测试期间固定 build ID，临时回环服务由本模块独占并在 finally 结束；不改变 Playwright 超时或断言。
- 首轮类型/import/Prettier 诊断已修正并重新检查。保留原始红灯：性能首轮误用 auth-disabled 使 login307；使用正确 auth-enabled 环境后原检查通过。浏览器首轮并发构建超过原 webServer120s，未执行场景；随后独立构建、在同一已构建产物上完成原浏览器门禁。没有删除测试、放宽资源预算或增加重试/超时。
- 专项/联合/完整检查有覆盖重叠，不能相加宣称独立覆盖数量。API fixture 和浏览器 mocked API 是合成离线回归；auth recovery 不是实际登录用户验收，也不证明外部结果真实性、部署或正式批准。
- 公开源码/提交归档一致性、证据复制 hash、精确四个专用 CI 资源收尾、独立 commit/push 与新 SHA 全部实际 Actions/jobs 另行核验。成功 push 不等于 CI 成功；本机原始证据仅在 ignored .deer-flow/ci/20261111-external-quarantine-workspace/，不提交配置、数据库或客户资料。

The backend-generated public fixture is required, never silently skipped. These
local gates verify deterministic source/count/budget bindings and no-resend
lifecycles, not external execution authenticity. Final source/evidence receipts,
owned-resource closure, the module commit and all actual exact-SHA Actions jobs
remain separate delivery checks; previous CI or a local pass cannot substitute.

## 兼容与回退 / Compatibility and rollback

本模块不新增依赖、迁移或后端运行时，不改旧 plan/review/report/retest/API。
如需代码回退，单独撤销本 UI/测试/文档提交并重新验证；不降级既有 eval_0014
后端迁移，不删除技术档案/审计，不重发未知写入，不替换数据库或生产配置。
Rollback requires a separately reviewed commit and CI; it never authorizes
migration downgrade, data deletion, execution enablement or automatic deployment.

## 后续 / Remaining

外部敏感输出与可信证据接纳、本地加密保留、冻结 QA 调度、失联 Worker 安全运维、
正式批准、授权保留数据升级及真实用户验收仍未完成。不能把技术接收面板当成整个
平台完成，也不能从未部署候选代码推断当前运行行为。
