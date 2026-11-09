# 独立逐条人工复核 / Independent case review

> 后续独立评估切片（2026-11-09）：新增全冻结样本评估预览及不可变修订 API，候选 head `eval_0011`，旧 owner 汇总/报告/复测不切换；原任务切片与 UI 记录保持历史范围。见[独立评估合同](DevPilot_Independent_Assessments.md)。部署仍为 `eval_0009`。

日期：2026-11-09。状态：**工作区后端/API 与共享复核中心/内联 UI 候选，未提交、未部署**。App 候选 head 为 `eval_0010`；最近核验的运行部署仍为 `0fd689da83a4ac7646250447fb6d044599a823c5` / `eval_0009`。不得用历史 Actions 或页面冒烟代替本切片验证。

## 1. 已实现与未实现

`app.evaluation.review_tasks` 与两组鉴权路由提供同一任务服务：项目 owner 明确将**某运行某序号的冻结 case**授予两个不同复核人和第三个不同仲裁人；owner 不能兼任任何角色。这是具体任务授权，不是项目成员或跨项目读取权限。

- 策略固定为 `independent-double-blind.v1`，不是可由客户端修改的表决规则。两个复核人互不可见对方身份、理由或投票；仲裁人只有在分歧/不确定升级后才能领取并按需打开两份已验证意见。
- 领取、释放、30 分钟租约、显式敏感件打开回执、追加决定、确定性结论、撤销和最多 10 轮重开；历史决定和结论不覆写。
- 同向 PASS/FAIL 得到逐条一致结论；分歧或任一 uncertain 升级仲裁。仲裁 uncertain 仍是 unresolved/escalated，不能当通过。缺输出/技术错误不能人工 PASS，仲裁也不例外。
- **不实现**人员目录、项目团队管理、自动分派/抽样、assessment 汇总重算、正式审批/发布、通知或新执行调用。现有 owner 自复核、已验证汇总、报告和复测的计算路径不变，独立结论尚未接入其分子或验收状态。

`scope=independent_review_only` / `case_resolution_only` 与 `approval=not_approved` 保留语义边界；逐条 pass 不是 run/project 正式批准。完整工作台仍按[设计](DevPilot_人工复核工作台设计.md)分期推进。

## 2. 授权、隐私与冻结对象

创建必须是已认证人类 owner，具有项目 read + write + review 权限，显式 `confirmed=true`、`share_reference=true`，并提供两个复核人及一个仲裁人的规范 UUID。服务器只按这三个精确 ID 检查账号存在且完成设置，不提供账号目录或邮箱查询；不存在/不独立的指派拒绝。内部 Agent 一律不能调用这些任务路由。

- 新任务绑定 task/owner/project/run/ordinal/case hash、固定策略和三名指定账号形成 definition/subject hash。此 hash 是结构绑定，不是独立签名或正式批准。
- 分配仅允许当前任务所需 Q、实际 A、参考答案、来源及技术观测的显式读取；不授予原项目/数据集/请求版本/其他运行的普通读取权限。原 owner-only 路由不放宽。创建前必须确保有权向这些人分享参考内容；不存在自动脱敏承诺。
- 元数据不含 Q/A/参考、决定理由或密文。复核人只看自己 assignment；owner 可看三人 assignment。盲审打开不查询 owner 决策表或任务决定/结论表，响应不夹带原 owner 意见；仲裁读取只在升级后放行。
- 复用显式 `DEVPILOT_REQUEST_ENCRYPTION_KEY` 和现有 envelope，增加隔离的 `task_decision` / `task_action` 类型；理由及重开原因加密，绑定原证据与 task/round/role/actor/subject/time。无 key 不生成、不降级明文。决定枚举/结论和技术审计是内部元数据，不能宣称全表均为密文。
- API 采用 `private, no-store`、通用校验/存储错误、32,000 字节 POST 上限与有界分页。敏感返回不得进入普通聊天/知识库或浏览器持久缓存；界面只用当前页面内存，不持久缓存敏感内容。

## 3. 状态与并发契约

| 操作            | 必须条件及结果                                                                                                                    |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| create          | owner 的已冻结且可复核 case；每 run 至多 10,000 tasks；客户端 32 位小写十六进制 task ID；同 ID 同定义返回既有元数据，变更定义拒绝 |
| claim / release | 本轮指定人类、当前 revision、显式确认；租约 30 分钟，过期不得打开/提交；无后台续租/清扫器                                         |
| open case       | 当前有效领取及允许阶段；先离事件循环验真，再 run 锁内复读并原子审计/记录 viewed revision                                          |
| submit decision | 已打开当前 revision、subject hash 匹配、有效租约；非空 UTF-8 理由；同角色同轮只能追加一次，决定/结论/状态/审计同事务              |
| result          | 仅 owner 的显式敏感读取，验证历史决定和确定性结论；可选择历史轮次，不用当前意见改写旧轮次                                         |
| cancel          | owner + write/review + 当前 revision；撤销后被指派人不得继续打开 case 或提交；owner 仍可按权限读取已有历史结论                    |
| reopen          | owner 对 resolved/escalated 明确说明原因；创建下一轮并沿用原三名指定人；不删旧投票、不替换冻结 case；cancelled 不直接重开         |

领取/释放/投票等状态变化增加全局 task revision，因此另一复核人操作后旧 viewed receipt 会失效，必须显式刷新并重新打开。并发提交通过已有 DB run 锁及最终快照重检串行化；不会覆盖旧决定。撤销或源证据在离线程验真期间变化均拒绝继续。敏感打开可写审计和 viewed receipt，虽为 GET 也不是零数据库写入。

创建/决定等写入若超时或提交状态不明，**仅按相同 task ID GET 核对**，不得自动重发、生成新 ID 或自动重试。GET 元数据不是打开敏感结论；需要 owner result 时仍须相应权限。503 不表示写入一定未发生，409 需要人工刷新复核。

## 4. HTTP 入口

项目路由 `/api/evaluation/projects/{project_id}/review-tasks` 提供 owner 列表；其 `/{task_id}` POST 创建任务。普通项目归属检查先于精确账号检查。

`/api/evaluation/review-tasks` 提供当前 owner/被指派人的有界队列；`/{task_id}` GET 为元数据。子路由：`claim` / `release` POST、`case` GET、`decisions` POST、`result?round_number=...` GET、`cancel` / `reopen` POST。

- 元数据要求项目 read 权限；claim/release/case/decisions 另需 review，但被指派复核人不需要项目 write，也不会因此成为项目 owner。
- create/cancel/reopen 需要 read + write + review 且服务层再次检查 owner；result 需要 read + review 且 owner-only。匿名、内部 Agent、未被指派第三人不获得数据。
- 不新增请求明文读取、目标执行、上传证据或模型调用入口。没有全量目录、原始请求 secret、自动送审或人工批准接口。

## 5. 迁移与验证

`eval_0010` 只追加 task/assignment/decision/resolution/audit 五表及两个索引，不编辑已部署迁移，也不改 Harness ledger。升级真实部署前须另行授权、一致性备份、账号/数据/配置保留和独立核验；本轮没有迁移生产数据库。降级测试只在专用合成库执行，不能据此擅自降级真实已填充复核表。

验证入口：`backend/tests/test_review_tasks.py`、`test_review_tasks_router.py`、`test_review_tasks_migrations.py` 以及现有 schema parity。定向 **67 passed**，包括 SQLite 历史旧表内容不变、幂等/降级回升，以及专用 PostgreSQL UUID 临时数据库的 schema 对照；临时库测试不迁移共享传入库。

变更前首次正确隔离全量出现 1 项派发顺序回归在 Worker finish 时 `JournalWriteUnconfirmed`；随后该文件 25 项与完整基线 12,125 项通过。根因尚未确认，失败日志保留，不能宣称修复了一个已定位的生产故障。更早 launchers 指向共享 venv 的收集失败，以及开发中红测试/fixture 错误均留存；没有为测试放松运行时契约。变更后全量结果和资源收尾见[当前矩阵](DevPilot_Delivery_Status.md)及[隔离环境记录](DevPilot_CI修复与隔离开发环境.md)。

最终完整变更后回归 **12,191 passed / 19 skipped / 11 deselected / 40 warnings**，纯领域 15 / 58 分别通过；Ruff check/format 1,227 文件通过。第一次变更后完整回归的旧库表枚举测试失败经测试修正后重新全量验证，原日志保留。定向与全量重叠，不相加。

以上计数属于后端切片；当时没有前端源码改动或新增页面。后续界面验证另列，不能将历史证据冒称本轮重跑。没有提交、远端 CI、生产部署、真实认证浏览器验收或真实模型/目标效果验收。

English: this candidate provides explicitly assigned two-human blind case review and third-person arbitration through a shared backend service and human-only APIs. Narrow immutable grants do not confer project membership. Decisions, rounds, deterministic resolutions and audit are separate; missing/technical evidence cannot PASS. The later workspace candidate adds a shared review-center and inline UI. Assessment/summary/report integration, formal approval, deployment and permission to make real model/target calls are still excluded.

## 6. 共享复核中心与内联界面候选（2026-11-09）

- 稳定侧栏入口 `/workspace/reviews`：明确加载任务元数据、有界分页（每页 50）、本页角色/状态筛选或精确 task ID 查找。没有自动轮询/通知、人员目录或跨项目普通数据权限。
- owner 在项目结果复核明确打开 case 后，输入三名不同账号的规范 UUID，分别确认参考答案分享和任务创建。前端不枚举账号，也不替代后端 owner/身份/权限校验。
- 中心与内联回执共用 `ReviewTaskDetail`。领取/释放/撤销/重开另行确认；有效租约及允许阶段才能明确打开 Q/A/参考/来源。内容按字面文本呈现，无自动外链/HTML 执行；有界滚动内容可键盘聚焦。盲审不显示 owner/同伴意见，仅仲裁阶段打开两份盲审决定。
- 默认 uncertain，理由必填；改动撤销确认，缺输出或技术失败不能 PASS。租约到期关闭敏感内容，迟到读取也须再次检查有效租约，不能重新展示；无自动续租。owner 只能明确打开指定历史轮次，不以当前结果改写旧决定。
- 写 ref 锁、卸载 epoch、元数据刷新关闭敏感内容；未知写入先刷新同一 task ID，不能自动重发。创建前把 ID 与定义写入 datasets 页内存，跨项目切换保留待核对 ID，404 也不证明延迟写入绝未发生。离开整页/刷新前须自行记录 ID；没有 localStorage/sessionStorage/服务端待办恢复。
- 没有新增依赖、额外迁移、模型/目标调用、自动执行或通知。现有 owner 自复核/已验证汇总/报告/复测仍按原语义计算，不消费这些独立结论；逐条 pass 不等于正式验收。

### 前端候选验证（2026-11-09）

- Docker Node 22.23.4 / pnpm 10.26.2 隔离快照，复用已有依赖与 Chromium，无依赖安装或新镜像。全量前端单测 **144 文件 / 1,125 passed**（17.9s），其中本切片四文件 **31 项**，不与全量相加；lint/typecheck、生产构建已通过。最后另执行完整 frontend Prettier 门禁（含指南），结果见隔离验证记录。
- Chromium 模拟 API 的完整工作区浏览器 **206 passed**（3.9m，含本切片 5 项），独立登录/设置恢复 **2 passed**（1.6s）；均 `--retries=0`。覆盖 1440/390px、键盘、逐次明确同意、字面文本/无外链加载、双盲/仲裁、unknown create 跨项目 GET 核对和不可变历史轮次。
- 初次定向 23 passed / 4 failed（测试 hook 与假计时器错误）已修正；第一次全量快照漏带两个公开 contracts 文件导致两个测试文件收集失败，补齐隔离快照后全量重跑。首轮浏览器 **3 passed / 1 failed** 发现移动端长按钮溢出，修复换行/fieldset 最小宽度后五项定向及全量通过，保留原失败上下文，没有隐藏溢出或删除断言。补充租约过期后的迟到响应回归，防止重新展示敏感内容。
- 不支持的 Rstest `--run` / Playwright screenshot CLI 参数失败留存，后续用受支持命令重跑；不把未执行命令算测试结果。最终类型导入告警已修正。
- 没有本轮后端测试重跑、真实认证多账号互通、连接实际后端的 UI 验收、真实模型/目标效果验收、远端 CI、提交/推送、生产迁移或部署。先前后端 12,191 项属于独立历史切片；最终用户验收和正式批准仍未完成。
