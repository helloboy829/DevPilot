# 授权 QA 配置导出工作台 / Authorized QA configuration export workspace

## 交付范围 / Scope

本模块把[已有授权 exporter](DevPilot_Authorized_QA_Exports.md)接到
`/workspace/datasets` 的独立区域，不新增第二 runner、发送入口或批准。
默认关闭的 operator policy 仍由后端决定；浏览器不能配置、生成 key、开启
execution 或向接收方自动传输文件。候选 App head 仍为 `eval_0013`；没有新依赖、
迁移、权限 action、生产配置或部署。

This slice exposes the existing recipient/grant-bound exporter through an explicit
owner workspace. A configuration is **NOT_EVALUATED**, not execution authority,
trusted result evidence or formal approval. Historical deployment receipts do not
establish this machine's runtime or an upgrade of the candidate.

## 使用流程 / Explicit workflow

1. 选择项目后，不自动读取导出策略、计划、回执、敏感输入或档案。
2. 点击 **Load export policy and grants**，取得 serving-process 的当前策略快照；
   不默认选择 grant，不跟随 latest。授权必须精确绑定 owner/project/plan/hash、
   recipient、tier、origin 和到期时间。
3. 显式选择 grant、点击 **Open selected frozen plan**，核对同项目/ID/hash、
   effectiveness 模式、v1/v2 schema 和 ALL frozen sample count。
   `baseline_inputs` 只能对应 baseline，不得将 acceptance 输入导出。
4. 分别确认精确来源/授权/接收方/级别、数据离开平台，以及外部目的地、负载、
   输出保护和保留控制责任；每次编辑、刷新或操作都会撤销已有确认。
5. 创建配置档案后，浏览器检查返回的完整回执。下载另需单独确认，并加载匹配的
   enabled policy、完全相同且未过期的 grant 与 software pin；后端再次核验。
6. 骨架输入不完整；baseline 档案包含 ALL frozen inputs，但不含金标、历史输出或
   请求值。**所有请求值必须重新绑定**；软件需另经可信渠道取得和核验。

English: policy, exact source, three creation consents and a separate download
consent are explicit. A process policy snapshot is not a source-validation or
permission guarantee. The UI does not fetch software, invoke the local CLI,
resolve request values or authorize execution. Skeletons remain incomplete.

## 未知写入与生命周期 / Unknown writes and lifecycle

- PUT 前生成 32 位小写 hex ID，先写入父页面 `Map`，再发请求。
- 父页面同时持有跨项目 write ref lock；组件按项目/locale keyed，使用同步
  operation ref 和 unmount epoch 阻止重复操作与晚到响应。
- PUT 失败、格式错误、错误来源或未知结果都保留原 ID；GET 404 也不证明未写入。
  **只可显式 GET 同一 ID，不重发 PUT、不自动换 ID、轮询或自动重试。**
- 切换项目再返回仍保留 page-memory pending ID。旧项目晚到成功不能清除 pending，
  也不能在新 scope 打开回执；返回原项目再手动对账。
- 浏览器不持久缓存 pending、输入或 ZIP。离开页面前需人工记下未决 ID；再次访问
  可显式输入历史 ID 读取，而不是自动寻找 latest。
- pending 对账还校验整个 grant、request binding、ALL count、software hash 和
  **查看过的 source-plan schema**；不因相同顶层 ID 就信任错误回执。

Unknown delivery never grants resend authority. Page-memory state survives project
switches, not navigation/reload; the displayed original ID is the recovery handle.
Lease/grant expiry is checked again at creation click, before binary GET and after
awaiting the response, not only during the previous render.

## 后端 metadata 与下载合同 / Backend metadata and download

新增 `GET /api/evaluation/projects/{project_id}/export-capabilities`，要求 human、
owner、`evaluation_projects:read` 与 `evaluation_exports:read`。数据库只查询项目
所有权；不读 request/bundle ciphertext、samples、references 或加密 key。
只返回同 owner/project、当前未到期的配置 grants；disabled 时隐藏 retained grants
与 software pin。读操作亦通过既有 drain，在重复取消时排空数据库访问再传播取消。

Response schema: `platform-qa-export-capabilities.v1`, project, checked time,
enabled flag, software pin, response-byte limits and scoped grants. Authority flags
are literally `execution_authorized=false`, `approval=false`,
`verdict=NOT_EVALUATED`. No-store/private handling and exact existing permissions
remain authoritative; this route does not create an export or audit a sensitive open.

配置 ZIP GET 沿用既有 owner/human/review/download permission、精确 viewed receipt
和 download confirmation。新增响应 pin：

- `X-DevPilot-Exporter: platform-local-qa-config.v1`
- `X-DevPilot-Receipt-Hash: <verified viewed_receipt_hash>`

Browser download uses the existing authenticated/CSRF fetcher, one GET, no-store
and redirect rejection. It validates MIME, both pins, exact optional decimal
Content-Length, the receipt size and 5 MiB ceiling, streamed overflow/truncation and
ZIP signature. Invalid streams are cancelled; no error page is saved. A valid Blob
is only an operation-local value; the object URL and temporary anchor are released
in `finally`, and scope/expiry are rechecked before saving. The encrypted bundle
hash is **not** claimed to be a plaintext ZIP hash, signature or provenance proof.

## 历史记录与审计 / History and audit

显式输入精确历史 ID 可读取 metadata，即使 policy disabled 或 grant 过期。
这不授权下载。审计通过按钮逐页加载，验证 owner/project/export/action、连续 sequence
和精确 cursor；时间戳不是顺序，空页不自动轮询。不存在 owner 复核或正式批准替代。

Receipt, capability and audit DTOs use strict parsers; plan reads allow the existing
full plan representation but return only the needed safe metadata. Stored values
are rendered as text, not HTML. Existing report/retest/export routes are unchanged.

## 验证与证据 / Verification and evidence

- 后端专项覆盖项目/权限/人类隔离、过期与 disabled 授权、SQL/key/敏感数据边界、
  下载 headers 和重复取消排空。
- 前端 policy/binary/DOM 专项覆盖无 mount fetch、三份独立同意、刷新撤销、精确来源、
  到期检查、未知 PUT/GET404、跨项目 pending、晚到 fence、历史 metadata 和审计。
- 新增 schema 篡改反例先红后绿；早期 DOM 回归捕获 stale-render expiry，现已在
  点击时及下载 await 后核验。完整类型门禁亦捕获并修正本模块测试的类型错误。
- 浏览器夹具由真实合成 API 生成，不修改 ID 冒充另一份 ZIP。后端独立核验 stored
  receipt/request fingerprint、真实 ZIP 的六个成员及每个 member hash；浏览器核验
  创建请求/下载字节、桌面 1440 / 手机 390、键盘操作、无横向溢出及未知写入不重发。

All tests use isolated synthetic auth/data/keys and mock transport. No customer
material, private configuration, real model/target call, deployment or user
acceptance is claimed. The generated fixture contains synthetic baseline inputs
only; it is not a software artifact or trusted external result.

### 本轮结果 / Session results

本模块最终本地门禁已通过；专项包含于完整套件，不相加为独立通过数：

| Gate                                                   | Result                                                             |
| ------------------------------------------------------ | ------------------------------------------------------------------ |
| Backend focused                                        | 71 passed, 21.31s                                                  |
| Standard backend `make test`                           | 13,260 passed / 19 skipped / 11 deselected / 40 warnings, 1324.62s |
| Pure-domain unittest suites                            | 15 / 58 passed                                                     |
| Blocking IO                                            | 72 passed / 2 warnings, 7.84s                                      |
| Ruff check / format and offline lock                   | 1,271 files; all passed                                            |
| Frontend focused policy / binary / DOM                 | 19 passed                                                          |
| Full frontend unit                                     | 155 files / 1,312 passed, 14.0s                                    |
| ESLint / TypeScript / full Prettier / production build | Passed                                                             |
| Existing six-route resource budgets                    | All passed with unchanged thresholds                               |
| Focused real-ZIP synthetic Chromium                    | 5 passed, 9.8s                                                     |
| Full Chromium / auth recovery                          | 236 passed, 5.8m / 2 passed, 1.6m; zero retries                    |

早期能力接口缺失的 4 项失败、DOM 到期检查及 schema 篡改各 1 项失败、
本模块类型检查和全目录格式检查的失败均保留，并在修正后重跑原门禁。
浏览器日志中未夹具化的后台 token-usage 请求存在 loopback ECONNREFUSED；
这是 mock-only 前端环境的观察，不冒称真实 Gateway 联调或用户验收。
没有提高超时、降低断言、启用执行或用自动重试掩盖失败。

实际受测快照与宿主 **1,391 份 Python/domain 及 852 份前端公开源文件**逐项
SHA-256 一致，72 份初始日志/快照/结果文件导出后逐项验 hash。文档最终格式与
专用资源收尾另行核验；资源、提交归档和精确新 SHA 的实际 Actions 是独立门禁。
本地绿灯不证明 push/CI，旧模块的成功也不覆盖本轮。

## 排除与后续 / Exclusions and next work

仍未交付：外部结果的持久隔离导入、本地敏感输出的加密与保留、冻结 QA 调度、
lost-worker 安全处置、正式批准及另行授权的保留数据升级/真实用户验收。
本模块不以 PASS、阈值达标或配置完整性替代这些工作。

Rollback is source-only until deployment is separately authorized. No deployed
migration is modified, no automatic retry/release/reclaim is added, and historical
archives and hashes are untouched. The whole platform remains incomplete.
