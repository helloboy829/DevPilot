# DevPilot 交付历史 / Delivery history

逐轮原始记录；日期、SHA、候选/部署和通过数均保留原语境，不代表当前状态。当前能力、运行与缺口见[当前交付状态](DevPilot_Delivery_Status.md)。

## 本地完整套件运行（2026-11-15）

在隔离 Python 3.12 容器内以 `git archive HEAD`（对应 `abbdde7` 工作树）重建完整源码副本，使用锁文件 dev 环境运行完整后端离线套件：**13,495 passed / 2 failed / 77 skipped / 11 deselected / 40 warnings**（1923.14s）。首次以 `tar` 手工复制时遗漏 `scripts` 等目录，出现 7 个 collection 错误（含 `support_bundle`），该次结果作废，改用 `git archive` 后重新运行。

两个失败均属临时容器环境，不是本轮改动：`test_config_version` 的 `config-upgrade.sh` 需要 PATH 上的 `uv`，容器未安装导致 127，安装后单独复跑 **1 passed**；`test_local_qa_cli` 的隔离源码子进程在本轮容器内报 `JSONRunStopped`，该测试未被本轮修改，且在同一 SHA 的 CI Unit 中通过。两条均保留为环境观察，不归因于当前源码；精确 SHA CI 仍是权威门禁。

English: a full offline suite on a `git archive` copy reported 13,495 passed with two container-environment failures (missing `uv`, isolated-source `JSONRunStopped`); the same tests pass in the exact-SHA CI. The earlier incomplete tar copy was discarded.

## 执行诊断聚合安全状态（2026-11-15）

[运维诊断](DevPilot_Execution_Reservation_Diagnostics.md)的 `reservation_snapshot` 在同一聚合 SELECT 中新增 `safety.states`：按[执行安全合同](DevPilot_Execution_Safety_Contract.md)的固定状态码统计持锁行（queued_ready、queued_deadline_reached、running_within_deadline、running_deadline_reached、cancel_requested_pending、interrupted_terminal）。仍不选择执行/run/owner ID、claim/证据列，不取锁、不初始化 guard、不写审计；`worker_liveness=not_established`，释放/回收/重试/调度仍为 false。

测试先红后绿：先加断言得到 `ImportError: SAFETY_STATES`（collection 失败），实现后诊断 **14 passed**；路由与执行安全联合 **40 passed**，Ruff check/format 通过。无迁移、执行/调度/配额/计时变更，无部署或真实调用。

**精确 SHA CI**：`052a62474f919b0bf7404f545d81c36f74d84246` 的 Lint、Blocking IO、Frontend、Unit 共 **4 workflows 全部成功**（Unit `43620477352`，14m23s）；结果只属于该 SHA。

English: aggregate held-reservation counts keyed by the fixed safety codes are exposed in the same single diagnostic SELECT, without identities, claim/evidence columns or any release/retry/dispatch authority.

## 候选验收包（2026-11-15）

[候选验收包](DevPilot_Acceptance_Package.md)整理同一 SHA 的源码验收路径：登录/RBAC、数据与冻结计划、默认关闭的执行、两名盲审＋仲裁、全样本评估、正式批准与撤销、报告/复测/导出、未知写对账、备份与回退边界，以及由验收人填写的签收表。它明确不授权部署、数据外发、真实模型/目标调用、生产 key 或正式批准；Linux/容器证据不替代 Windows 与真实用户验收。本地门禁：文档相对链接核对通过；无代码、迁移或运行时变更。

English: the acceptance package documents the synthetic checklist, rollback limits and sign-off record without authorizing deployment, external data transfer, real calls or approval.

## Lost Worker 执行安全合同（2026-11-15）

[执行安全合同](DevPilot_Execution_Safety_Contract.md)新增纯同步 `app.evaluation.execution_safety.classify_held_reservation`：对单行占用输出固定技术投影（七种状态、到期标记、配额、固定阻塞码），恒返回 `release/reclaim/requeue/retry/resend/dispatch` 未授权，`worker_liveness=not_established`；未知状态、类型伪装、非一致 held/state 与非正时钟全部 `ValueError` 失败关闭。边界回归以 AST 锁定：调度器与正式批准模块不得导入执行仓库或调用 `admit`，运维路由只有 `GET /reservations`。

未修改执行/调度/配额/取消/计时行为，无 API、迁移、UI、后台清理器、部署或真实调用。测试先红后绿：首版路由断言用子串匹配，把 docstring 的 `release/reclaim` 误判为路径（**1 failed**），改为 AST 精确断言路由方法与路径后 **30 passed**；未改运行时、未放宽断言。后续加入真实 admit/claim/expire 集成回归（**2 passed**）：queued 过期释放配额并分类为 `interrupted_terminal`，running 过期保留配额且仍不授权，`interrupted` 持锁行增加显式 quota blocker；专项合计 **32 passed**（20.80s），关联执行/调度回归 **66 passed**（54.49s），批准/迁移/执行安全/恢复矩阵组合 **60 passed**（137.47s），锁定 Ruff 0.15.12 check/format 通过。

**精确 SHA CI**：`ce6ca15f97c410252100dea4c00a8949ed826a40` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43615345199)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43615345236)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43615345167)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43615345169) 共 **4 workflows 全部成功**；Unit 的 `make test` 覆盖本模块与既有执行/调度回归。该结果只属于此 SHA，不能移用于后续提交或部署。

后续集成回归与候选验收包提交 `fa54cbbb522247c6f1ba0a6eb34245623a93f687` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43617913181)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43617913189)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43617913176)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43617913214) 共 **4 workflows 全部成功**。中间提交 `7ab6478` 的 Unit 在 16:52 被该新推送取代而 **cancelled**（其余 Lint/Blocking IO/Frontend 成功），不记为通过；这不改变原门禁，也不能把 `fa54cbb` 的结果移用于其他 SHA。

English: a pure synchronous classifier projects one held execution row without ever authorizing release, reclaim, requeue, retry, resend or dispatch; malformed/unknown/incoherent rows fail closed. AST regressions pin that the scheduler and formal approval cannot bypass or trigger QA execution and that operations expose only an aggregate GET. No runtime, API, migration, UI or deployment change.

## 正式批准首切片（2026-11-15，候选 `eval_0015`）

[正式批准首切片](DevPilot_Formal_Approval.md)在不可变独立评估之上增加 append-only、可修订的具名人类批准：`evaluation_run_approvals` 与 `evaluation_approval_audit` 两表，`down_revision = eval_0014`。批准固定 assessment id/revision/`assessment_hash`/`summary_hash` 与 ALL 分母；要求 run 与评估文档均为 `recording_finished`、`review_complete` 且无 blockers、冻结阈值（若定义）`met`、显式 `confirmed=true`；审批人必须是 canonical 账号且不得等于 owner 或该 run 任一已验签任务中的 reviewer_1/reviewer_2/arbitrator。撤销追加 revision 且必须有理由；同 ID 相同载荷幂等、不同载荷或旧 revision 冲突；并发首发只有一个成功；审计按 run 原子递增。owner 是记录人（`recorded_by`），审计 `actor` 记录实际写入者，`approver_id` 记录具名决策人。文档 hash 链被篡改时读取失败关闭；列表只返回技术元数据。路由为 owner-scoped `GET/POST /review-runs/{run}/approvals[/{id}]`（read+review；写入再加 write），人类专用、`no-store`、验证错误不回显客户端值。

测试先红后绿：新增仓库级 `tests/test_qa_approvals.py` 与 API 级 `tests/test_qa_approvals_router.py`，覆盖未完成复核拒绝、阈值 `not_met` 拒绝、owner/盲审/仲裁职责分离、显式决定、撤销理由、同 ID/旧 revision/并发、篡改、跨 owner、未知写原 ID 对账与错误脱敏。候选恢复矩阵扩展为 39 → 44 → 45 → 47 → 49 → 51 → **53** 张表并固定新增 14 张表；14 个既有测试文件的迁移头断言与旧 revision 表集合派生同步更新（`eval_0015`）。

本地离线门禁（隔离 Python 3.12.16 容器，仅挂载公开源码，锁文件 dev 组）：批准专项 **20 passed**（32.94s）；迁移矩阵 **13 passed / 5 skipped**（146.36s，skip 为原 PostgreSQL 独占服务器门禁）；更新头断言的九个文件 **285 passed**（286.45s）；领域 **15 / 58 passed**；Blocking IO **72 passed / 2 warnings**（41.70s）；锁定 Ruff 0.15.12 check 通过、**1,286 files** format 通过。完整后端离线套件结果见下方本轮补充；专项与全量重叠，不相加。未部署、未启用执行、未生成生产 key、未调用真实模型/目标，未读取或复制业务数据库；本轮测试容器仅挂载公开源码，结束后按完整 ID 停止并删除。

**精确 SHA CI**：提交 `18101f9c08f8fbb32d8fbfdde72200aefef26738` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43612739708)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43612739812)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43612739625)、[Replay E2E](https://github.com/helloboy829/DevPilot/actions/runs/43612739710)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43612739705) 共 **5 workflows 全部成功**；Unit 的 `make test` 覆盖新增批准模块与扩展后的 `eval_0009 → eval_0015` 恢复矩阵。该结果只属于此 SHA；不能移用于后续提交或部署。

后续补充专属迁移回归 `tests/test_formal_approval_migrations.py`（本地 **2 passed**，29.05s）：在真实评估/复核/批准行存在时 downgrade 到 `eval_0014`，确认只移除批准两表、其余历史行逐表不变；再 upgrade 到 head，确认空表重建、`devpilot_alembic_version=eval_0015` 与 `compare_metadata` parity；并以真实行验证 `(run_id, revision)` 唯一、decision/action/revision 检查、assessment/run 外键失败关闭。首版测试暴露夹具缺少 `users` 表与 SQLite 未启用外键（**2 failed**），按外部迁移测试既有做法显式建 Harness 表并在连接时启用 `PRAGMA foreign_keys=ON`，未削弱断言；Ruff 通过。该补充随 `fa54cbb` 的 4 workflows 全绿通过精确 SHA CI。

再补充只读审计列表 `GET .../review-runs/{run}/approvals/audit`：按 `sequence` 返回 `approval_id`、`revision`、`action`、`actor`、`subject_hash`、`at_ms`（最多 1000 条），不返回 note/document/counts 或证据，沿用 read+review 人类权限与 `no-store`。批准/撤销、迁移与审计联合随后扩展到 **26 passed**（53.00s）：新增“当前复核被重开后，历史批准仍可撤销、rev1 保持不变”与“API 级撤销追加 revision 2、审计顺序 1→2”的回归；该审计列表随 `abbdde7` 的 5 workflows 全绿通过精确 SHA CI（Unit `43623795524`），撤销回归随 `aa86eb9` 的 4 workflows 全绿通过精确 SHA CI（Unit `43629110238`）。

再补充只读预检 `GET .../assessments/{assessment_id}/approval-preflight?approver_id=...`：返回 `eligible`、固定 blockers（collection/technical/review/criteria/separation）、`readiness`、`criteria.status` 与两个分离布尔，`approval=not_recorded`；不写批准或审计行，非法 approver 返回 422、未知评估 404、响应 `no-store`。首版实现把 `await asyncio.to_thread(...)[...]` 写成先索引协程（**4 failed**，`coroutine was never awaited`），修正为先 await 再取字段，未削弱断言；另在冻结阈值用例中加入预检断言（`met` 可批准、`not_met` 不可批准且含 `criteria_not_met`）。联合 **30 passed**（72.07s），Ruff 通过。预检随后随 `66fa258` 的 5 workflows 全绿通过精确 SHA CI（Unit `43632309247`）；项目级索引与冻结阈值预检的 CI 见后续提交。

再补充项目级索引 `GET /api/evaluation/projects/{project}/approvals`：返回每个 run 的最新批准 revision 元数据（run_id/id/revision/decision/assessment_id/assessment_hash/created_at_ms，最多 200 条），不含 document/note/counts，未知项目 404。联合 **32 passed**（75.17s），Ruff 通过；项目索引与冻结阈值预检随 `18bd782` 的 5 workflows 全绿通过精确 SHA CI（Unit `43633593145`）。

English: `eval_0015` adds an append-only, revisioned formal-approval ledger that pins an immutable independent assessment and requires finished collection, complete independent review, a met frozen threshold when defined, an explicit decision, and an approver distinct from the owner and every blind reviewer/arbitrator of that run. Revocation appends a revision with a required reason and audit. Focused, migration, cross-module and Blocking IO gates passed locally in an isolated source-mounted container; exact-SHA CI and Windows acceptance remain separate.

## 测试环境隔离与配置 None 修复（2026-11-14）

上一基线 `a3e0deb` 的四项 Actions 已核验成功。本轮提交 `6c67ab58819d5871603a7f21547bec184db55e16` 共三个修复提交（`8f4678b`、`5dd7b3a`、`6c67ab5`），只修改测试隔离与 `overlay_models` 的 None 处理：

- `test_default_config_is_memory` / `test_make_stream_bridge_defaults`：Docker 容器存在 `DEER_FLOW_STREAM_BRIDGE_REDIS_URL` 时默认推断为 Redis，与测试期望的 Memory 冲突；用 monkeypatch 清除环境变量，保留原推断逻辑与断言。
- `test_deploy_uv_extras` / `test_detect_uv_extras`：三个测试只清除 `UV_EXTRAS`，容器 Redis 环境变量仍被 `detect_from_runtime_env()` 计入；改为同时清除两个 Redis URL 变量。
- `overlay_models`：`models: None`（全部注释掉）时 `config_data.get("models", [])` 返回 None 导致 `TypeError`；改用 `or []`，符合该函数对空模型列表的既有语义。同一修复消除 `test_local_registration_gate` 六项 fixture 错误（读取 `config.example.yaml` 时触发同一路径）。

**精确 SHA CI**：`6c67ab5` 的 [Lint](https://github.com/helloboy829/DevPilot/actions/runs/43600357480)、[Blocking IO](https://github.com/helloboy829/DevPilot/actions/runs/43600357401)、[Frontend](https://github.com/helloboy829/DevPilot/actions/runs/43600357383)、[Unit](https://github.com/helloboy829/DevPilot/actions/runs/43600357353) **4 workflows 全部成功**；Unit 的 backend-unit-tests 执行原 `make test`（含本轮修复和候选 SQLite 恢复演练）通过，default-install-collection、local-qa-distribution、authorized-export-installed 亦成功。`5dd7b3a` 的 Unit Tests 已被后续推送取代而 cancelled，不记为通过。

容器内先行观察到的其余失败（授权路由权限 5 项、USER.md 路径、cancel interrupt 等）经本地源码核对属于容器旧镜像（`criteria-0fd689da83a4`）与当前源码不一致，不是当前源码缺陷；当前源码的同等套件由上述精确 SHA CI 覆盖。不以容器观察冒充当前失败或通过；Windows 验收仍独立。

English: Three test-isolation/None-handling fixes on exact SHA 6c67ab5 passed all four workflows, including the full backend suite and candidate SQLite recovery rehearsal. Container-only failures were old-image artifacts, not current-source defects; Windows acceptance remains separate.

## 边界测试编号与 CI 超时排查（2026-11-14）

恢复回归提交 `cd26960455fd1e74e4b698d1d81c5bc6c840ba11` 已推送且与远端 main 一致。其 Lint `43563204115`、Blocking IO `43563204134`、Frontend `43563204161` 成功；Unit `43563204085` 中默认安装 collection、软件分发和实际安装导出成功，但 backend-unit-tests 超过原 15 分钟 job 限制而取消。原始日志虽打印 **13,499 passed / 19 skipped / 11 deselected / 18 warnings，788.11s**，仍不是成功的 CI job。

原始日志 **3,994,360 bytes**；11 个超过 1,000 字符的测试行合计 **1,968,573 字符**，最长 **655,484 字符**。这些行直接包含大体积边界输入。六份测试文件仅给这 11 个参数增加简短固定 pytest ID；AST 去除 ID 包装后与原版完全一致，保留全部参数、测试函数、断言和原 CI 超时。缩短日志是明确修复；是否足以消除 job 超时须由新 SHA 验证，不能仅从测试汇总或日志时间间隔推断根因。

`blockbuster` 原本就在 dev 依赖及锁文件；保留测试 `backend/tests/test_local_qa_retention.py` 已受版本控制。本轮从公开源码及冻结锁在独立 Python 3.12 容器重建 dev 环境，没有重复添加依赖、复制私有配置/业务 DB 或启动旧业务服务。本机四个业务容器仍 stopped；daemon 正常、未标记 OOM，退出码本身不确定根因。镜像清单只有现用 DevPilot 版本；不因 stopped、无标签或 reclaimable 比例删除业务资源、卷、回退镜像或其他项目。

本轮独立 Python 3.12 冻结 dev 环境中 `blockbuster` 实际版本 **1.5.26**，没有缺模块错误。修复前完整基线 **13,441 passed / 77 skipped / 11 deselected / 40 warnings，1032.35s**；修复后原 `make test` **13,441 passed / 77 skipped / 11 deselected / 40 warnings，951.44s**，领域 **15 / 58 passed**。六文件专项 **384 passed / 1 warning**、Blocking IO **72 passed / 2 warnings**、完整 Ruff **1,282 files** 和两份文档 Prettier 通过。专项与全量有重叠，不相加；77 skips 包含默认安装缺少 PostgreSQL extra/独占服务器等原门禁，不是通过。

相同辅助入口的 collection 前后均 **13,524 items**，每个测试函数的用例数一致；原标准全量日志另记录 **11 deselected / 5 collection skips / 13,513 selected**。11 个超长编号替换后，最长编号从 **655,440** 降至 **615 字符**，总编号长度 **3,280,383 → 1,313,364 字符**；其他测试每次生成的随机 UUID 编号单独保留，不误当本轮改动。AST 比较保留所有原输入和断言，六份受测文件及两份依赖文件按字节 hash 与宿主一致；锁文件原始 CRLF/LF 差异已确认只是换行后统一测试副本。原失败日志、两轮完整结果和编号对照留在本地；精确提交/推送、Actions 与资源收尾另行核验。

English: The prior backend job timed out despite a passing pytest summary. Short IDs preserve every input and assertion; both full local runs passed with identical result counts, and the longest collected name fell from 655,440 to 615 characters. Exact-commit CI and resource cleanup remain separately recorded; no deployment, real calls or business-data cleanup is implied.

## 候选 SQLite 升级与备份恢复演练（2026-11-14）

基线 `7ba1484b098d7a29a0a737400ff321d0ccbc8001` 的四项实际 push Actions / 八个 jobs 重新核验全成功：Lint `43558000440`、Blocking `43558000459`、Frontend `43558000384`、Unit `43558000487`；工作区与远端 main 一致。

[合成恢复回归](DevPilot_Candidate_Upgrade_Recovery.md)复用真实 Harness bootstrap、App `eval_0009`、仓库/密码校验及 Word 渲染。全部 39 张旧表/行/schema 与双 ledger 纳入快照；逐级或直接到 `eval_0014`，合同固定新增 12 张表，完整性/外键、ALL 两样本/两历史 run、账号、密文、报告/复测/Word 均核对。WAL-only 的已提交账号变更使主文件复制反例确实失败；online backup 与新路径还原必须保留。注入实际提交 `eval_0011` 后结果丢失，不重试或 downgrade 该候选；独立恢复旧备份。恢复后不保留候选的新写，不能称无损回退。

最初 13 项恢复用例全部通过（113.37s）；这是纯验证新增，没有伪造运行时缺陷或宣称原迁移存在 bug。首轮 Ruff 报 E501，按项目 formatter 修正。后续增加固定新增表集合、逐级版本矩阵、空表/列变化和备份后新写丢失验证；七类行破坏仍分别在新副本中执行，共享合成种子以减少重复迁移。最终门禁、精确 SHA CI 和资源收尾另行记录。无运行时/依赖/迁移/API/业务配置变更，未复制业务 DB 或执行部署/真实调用。

新建 Python 3.12.16 默认 dev 环境，修改前完整基线 **13,433 passed / 77 skipped / 11 deselected / 40 warnings**（906.24s），领域 **15 / 58 passed**。最终版本矩阵专项 **8 passed**（59.15s），完整显示 39 → 44 → 45 → 47 → 49 → 51 张表；此前与五组已有迁移联合 **13 passed / 5 skipped**（80.45s），五个 PostgreSQL 专项因本地无独占服务/extra 跳过，不冒充通过。Blocking IO **72 passed / 2 warnings**（7.03s），完整后端 Ruff check/format **1,282 files** 通过。最终源码全量与新 SHA CI 单独记录，专项/全量重叠不相加。

最终完整离线回归 **13,441 passed / 77 skipped / 11 deselected / 40 warnings**（934.37s），领域 **15 / 58 passed**，最终 Ruff check/format **1,282 files** 通过。变更测试源码与宿主 hash 一致；最终专项/全量不相加。**13** 份合成日志逐项导出比较大小/SHA256，另从实际 stdout 提取两条版本矩阵；临时 SQLite/key 不导出。七份变更 Markdown 的 **206** 个本地链接有效。新提交的精确 SHA CI 仍须独立核验。

只移除本轮零挂载容器 `91ddbdedff7c` 和本轮 `source.tar`，删除前复核标签/精确 ID、全部测试终态及证据 hash。普通 `docker stop --timeout 10` 后 Exit137 / OOMKilled=false；停止前仅 PID 1/defunct 子进程，不宣称优雅退出。原十个容器仍保留且 stopped；没有镜像、卷或全局缓存清理，没有业务数据库/配置复制或部署。

## 显式本地保留管理命令（2026-11-14）

上一模块 `deb1935d246fac1a8ed25d89ff16fd5ccd40c607` 的四项实际 push Actions / 八个 jobs 重新核验全成功：Lint `43553100136`、Blocking `43553100133`、Frontend `43553100555`、Unit `43553100265`。本模块从当前锁文件在独立 Python 3.12.16 dev 环境建立修改前完整基线：**13,393 passed / 77 skipped / 11 deselected / 40 warnings**（899.12s），领域 **15 / 58 passed**。新命令最初 **38 failed**，证实缺少入口；新增 stdout 丢失和无输出目录场景后，管理命令与原 API 联合 **80 passed**。

[新命令](DevPilot_Local_QA_Retention_Commands.md)复用真实 retention API：显式 inspect、原 disposal UUID/两个 hash/单独同意的 dispose-expired 和同 ID reconcile-disposal。所有结果保持未认证 `NOT_EVALUATED`，不读 key/解密/业务配置，不运行 QA，不生成 ID、发现 latest、修复或重试。未知 unlink/sync/完成回执、键盘中断和 stdout 丢失后只读原 ID 对账；缺 intent/锁或绑定错误不修复。原运行时 shared runner、hash/ALL 分母和一次删除合同不改。

独立候选目录使用新鲜六工具 hash-locked build → sdist/wheel → 十二依赖完整离线安装；实际已安装进程执行三条管理命令，并拒绝业务/执行 imports、DNS/socket 和 Fernet 解密。缺同意、缺失/篡改 wheel 和重复处置拒绝；两次软件档案逐字节一致，SHA256 `27aeb3cdb8df596b63fd2b0d8569e824ea5a13d11c4f36a315b7d1eb48af697f`，声明基线 revision，不认证 dirty 工作区 provenance。带实际 artifact 的命令/API/分发/输出/receipt 联合 **241 passed**（31.00s），Blocking IO **72 passed / 2 warnings**（14.13s），完整后端 Ruff check/format **1,281 files** 及两个变更模块通过。全量、资源收尾和本模块精确 SHA CI 分别记录，不挪用上一模块结果。无依赖/迁移/平台 API/部署/真实调用；明文副本、广泛崩溃产物、Windows 和正式批准仍独立待完成。

最终完整离线回归 **13,433 passed / 77 skipped / 11 deselected / 40 warnings**（881.28s），领域 **15 / 58 passed**；默认 dev 安装无 PostgreSQL extra/独占服务，相关专项按原门禁跳过，不宣称已通过。专项、安装和全量重叠，不相加。受测三个变更源码与宿主 SHA256 相同，十份变更 Markdown 的 **208** 个本地链接有效。

测试结束后逐项导出并比较 **16** 份合成日志/软件的大小与 SHA256；只移除本轮无挂载容器 `c97c196792ef` 和本轮 `source.tar`。停止前已无测试/build 进程，只剩 PID 1 和测试留下的 defunct 子进程；普通 `docker stop --timeout 10` 记录 Exit137 / OOMKilled=false，不宣称优雅退出。原十个容器、镜像、缓存和卷均保留，无全局清理。新提交和精确 SHA CI 另行核验。

## 运行时保留身份接入（2026-11-14）

基线 `5fa993445400feae0420261231d4a6dd1e6d0bee` 的四项实际 push Actions / 八个 jobs 全成功：Lint `43549070559`、Blocking `43549070532`、Frontend `43549070615`、Unit `43549070550`。默认安装 collection 步骤 355s，完整后端/独立分发/实际安装导出均成功。前一 `0a88d11` 默认 collection 超过 10m 取消仍保留，不以本轮成功宣称其根因已修复；诊断不改 timeout/范围/重试。隔离默认安装实际收集 13,464 项；首次 git archive 副本缺 `.git` 时四项扫描器收集报错，建立独立空仓库后原命令通过，未修改扫描器或断言。

本模块将 retention 原身份创建接入 `EncryptedOutputStore` 与真实 CLI：先 durable receipt，再 ciphertext，原时间/ID/ALL counts 与预算保持；lease 排除活跃 writer 期间的检查/处置，到输出关闭后释放。原线程 drain 处理重复取消；未知写入不重试、无自动删除或恢复。receipt、header、首 attempt 三个真实子进程硬退出点保留原身份，只读检查及另行确认到期 API 处置；plaintext 与旧目录不补造记录。

新增回归先 **11 failed**；初步接入后加密输出/retention 联合 **100 passed**。实际全新 wheel 安装另暴露 `python -m` 的 `__main__`/规范模块 manifest 类身份不一致；入口改为调用规范模块 main，保留严格类型检查，硬退出回归也改走实际 module 入口。旧全量因该修复中断，不算通过；最终源码重新验证。最终 CLI/receipt/retention 联合 **210 passed**；新鲜六工具构建、12 依赖完整离线安装、真实加密/plaintext mock CLI、受控打开/到期清理和原 ID 核对通过，缺失/篡改 wheel 仍拒绝。软件档案 SHA256 `514aab7028e739441dc037cc016f7f78374f906bb4b18559a2af71e33c0a8ada` 只校验完整性，声明基线不认证 dirty 工作区来源。完整门禁及新 SHA CI 单独记录。

最终完整离线回归 **13,393 passed / 77 skipped / 11 deselected / 40 warnings**（791.25s），领域 **15 / 58 passed**；默认 dev 安装没有 PostgreSQL extra 或独占 PostgreSQL，相关门禁跳过，不冒充通过。带实际 artifact 的 API/分发/输出/receipt 联合 **284 passed**，真实 `make test-blocking-io` **72 passed / 2 warnings**（5.24s）。完整 Ruff check/format **1,280 files** 及三个变更模块通过。未新增依赖/迁移、未部署或真实调用。无 key retention 检查不认证完整性，处置仍需另行同意原 ID/hash；显式管理命令、明文副本治理和 Windows 实际验收未完成。

## 未完成本地输出保留治理基础模块（2026-11-14）

新增 `devpilot.local_qa_retention` 纯本地治理模块，为尚未完成或崩溃的本地 QA 输出建立先 receipt、后输出的固定身份记录，并提供不认证内容的只读检查、到期后一次性显式清理和同 ID 只读对账。未知 unlink/fsync/完成回执结果不会重试、再次删除、修复、续跑或重发；清理不是安全擦除证明，也不授予平台 provenance、PASS 或批准。

初版专项 14 passed 未覆盖关键边界；复核后修正只读建锁、未持续持有输出锁、FIFO 读取阻塞、宽松布尔校验及失真的删除故障夹具。最终专项 **40 passed**（包含在 receipt/distribution 联合 **112 passed** 中）；当前锁文件的新 Python 3.12.16 环境完成真实本地 QA/API-installed/Blocking IO 联合 **490 passed / 2 warnings**，领域 **15 / 58 passed**、完整后端 Ruff check/format **1,280 files** 通过。最终完整离线回归为 **13,383 passed / 75 skipped / 11 deselected / 40 warnings**（924.71s）；本地未启动独占 PostgreSQL，相关专项等按原门禁跳过，远端 CI 的数据库服务门禁独立核验。专项/联合与全量重叠，不相加。

真实六工具 hash-locked build → sdist/wheel → 12 依赖完整 offline install、新 no-system-site venv 下实际 encrypted/plaintext CLI、打开/删除/原 ID 对账，以及新 retention API 的实际安装验证均通过。档案 SHA256 为 `c0d6be72cc04e88a094f9e466f9ce3e19ba8562005ee4b9b5bd53cb5ffc23ffb`，声明基线 revision，不认证当前工作区来源。没有改依赖锁或部署。该模块仍是独立 API，CLI 未自动接入；Windows 验收、取消/硬退出后更广泛编排、平台批准与 QA 调度仍未完成。

`3f970c5` 的远端 Backend Unit Tests / default-install collection 成功，但 Lint 和 distribution job 失败；原因分别为测试格式和源码 allowlist 未排序。当前修复已通过本地相应门禁，新提交的精确 SHA Actions 仍须独立核验。旧前端完整/浏览器/部署记录不代表本轮重跑或当前本机运行状态。

本轮第一次完整回归为 **1 failed / 13,381 passed / 75 skipped / 11 deselected / 40 warnings**（862.60s）：`test_late_successful_renewal_still_fences_local_run` 的 50ms 真实 UTC 夹具在调度延迟后进入了“调用前已过期”的另一条正确运行时路径。显式 100ms 延迟复现同一断言失败；现以受控 UTC 保留真实 timeout/cancellation，新增无延迟/100ms 延迟两场景，归属 + RunManager 联合 **161 passed**。没有改 Worker 逻辑、延长 timeout 或放宽断言。修复后的完整套件另行通过，原失败仍保留。

English: `devpilot.local_qa_retention` adds receipt-first, content-unverified inspection, explicit one-shot expired disposal and same-ID read-only reconciliation for incomplete local output. Unknown filesystem outcomes never retry, delete again, repair, resume or resend. The primitive is tested but is not a platform evidence, PASS, approval or secure-erasure mechanism; broader runtime integration and exact-SHA CI remain separate gates.

## 本地 QA 加密输出与保留候选（2026-11-11）

上一模块 `e5af8fd44faa0e2726e87fae11d1e002dc33ef3f` 已推送，六项实际 Actions / 11 jobs 全部核验成功：Lint `42882229689`、Blocking `42882229556`、E2E `42882229676`、Unit `42882229441`、Replay `42882229263`、Frontend `42882229324`。这些结果只属于该 SHA，不代表当前未提交改动或部署。

[当前模块](DevPilot_Local_QA_Protected_Output.md)复用同一 shared run/collector/pinned transport，为本地输出增加独立 operator key、分离同意、有界认证链、保留期、同 descriptor 持锁受控打开、到期原 hash 确认的一次精确删除与原 ID 只读对账。旧 plaintext 只显式兼容；默认离线不读 key/不发送。未知写入/删除不修复、不重试、不重发。

crypto 是直接依赖，复用既有锁定版本；新分发 v2 明确 native platform，12 个运行依赖、36 个第一方源码成员和六项独立 build tools。已真实验证全新 hash-locked build → sdist → wheel → 完整 offline install、实际 plaintext/encrypted CLI、打开/到期清理与 API 导出消费；两次同输入 archive byte-identical。最终全量/格式/源码收尾、独立提交推送及新 SHA Actions 仍须分别核验。

取消/硬退出/半写输出的独立保留处置、敏感外部证据治理、QA 调度/lost Worker、正式批准和另行授权部署/真实用户验收仍未完成。候选 head 仍为 eval_0014，未部署、不启用执行、不生成生产 key、不调用真实模型/目标。旧 eval_0009 收据不是本机运行证明。

English: Explicit operator-key protected output reuses one execution chain. Unknown writes/deletes never retry or resend; expiry is an application gate, not secure erasure. Fresh locked software installation has been exercised; final module gates and exact-SHA CI remain separate, and incomplete-output governance/formal approval/deployment remain unfinished.

## 本轮验证 / Verification (2026-11-11)

- 后端标准 `make test`：**13,394 passed / 19 skipped / 11 deselected / 40 warnings**（1310.96s）；同时运行纯领域 **15 / 58 passed**。专项 protected output + distribution **121 passed**（16.73s），Blocking IO **72 passed**（5.90s）。Ruff check 和完整 format check **1,282 files** 通过，两份 offline lock check 通过。
- 前端完整 **158 files / 1,360 passed**（14.6s），其中文件/hash 同步专项 **20 passed**。首轮完整回归曾有 **1 failed / 1,358 passed**：真实文件/hash Promise 的展示断言未完成；原失败和调用真实 WebCrypto 的诊断日志保留。测试改为在 React act 内显式排空真实读取/hash Promise、核对两份原始 hash，并追加任一文件未完成时禁止 inspection 的回归；没有替换 hash、放宽断言、提高 timeout 或改业务逻辑。
- 最终输入已完成新鲜 hash-locked build → sdist → wheel → 全依赖 offline install；实际已安装 plaintext/encrypted CLI 各 5 次 mock attempts、受控打开/到期删除/原 ID 对账、缺失/篡改依赖拒绝通过。API-export-installed **2 passed**（9.75s）。两次同输入 archive byte-identical，SHA256 为 `9d70a60db1fe5470e48021202f6a4960fcc1f6884463626f662d54341dba7008`；声明 source revision 是基线，不是 dirty 工作区的来源认证。ESLint/typecheck 和整个 frontend Prettier 通过；源码/证据核对、资源收尾及新提交精确 SHA 的远端 CI 仍独立核验。未重跑生产 frontend build/browser/performance，不冒用旧结果。

English: Final backend and frontend regressions passed after explicitly draining real file/hash promises in the test, without retries or weaker assertions. Original failures remain evidence. Final packaging/format/source/resource and exact-commit CI gates are separate; no deployment or real calls.

## External QA quarantine workspace local verification (2026-11-11)

上一后端隔离接收提交 `179b944a2f47bd0eef011d395b17f2823a91991a` 的五项实际 push Actions 已逐项核验成功：Blocking `42864729700`、Unit `42864728140`、Frontend `42864727845`、Lint `42864727835`、Replay `42864727910`，共 10 个 jobs。不是本轮尚未提交 UI 的 CI。

[独立技术接收面板](DevPilot_External_QA_Quarantine_Workspace.md)已完成本轮本地验证。只存技术元数据、ALL 分母和预算、父页 metadata-only pending 与跨项目锁、未知写入仅原 ID GET、迟到文件/网络/hash fence 和字面审计保持。无新增依赖/迁移或后端运行时改动，无部署、执行启用、真实调用或正式批准。

最终本地门禁：专项前端 **47 passed**，完整 **158 files / 1,359 passed**，ESLint/typecheck/整个 frontend Prettier 通过；真实合成 API fixture **2 passed**，后端联合 **257 passed**，标准全量 **13,334 passed / 19 skipped / 11 deselected / 40 warnings，1391.03s**，领域 **15 / 58**、Blocking IO **72 passed**、Ruff **1,277 files** 和 offline lock 通过。生产构建、原六路由性能预算、零重试专项 Chromium **6 passed**、完整 Chromium **242 passed** 及独立 auth recovery **2 passed** 通过；专项/完整门禁重叠，不相加。

原始类型/import/格式诊断保留。首轮性能命令误用 auth-disabled 导致 login307，改正测试环境后原六路由与原预算全部通过；首轮浏览器因并发构建超过原 webServer120s 未启动场景，随后单独构建成功、独占回环服务和固定 build ID 完成零重试浏览器门禁，不提高超时或放宽断言。九份公开指南、受测源码、证据 hash、精确资源收尾、独立提交推送和新 SHA 实际 Actions 必须分别核验；不由本地成功或前轮 CI 推断交付。后续敏感外部输出/证据治理、本地加密保留、QA 调度/lost Worker、正式批准和授权升级/真实用户验收仍未完成。

## External QA technical quarantine local verification (2026-11-11)

上一导出工作台提交 `aed6e70b9ddb1e275af7744e20507a43df67f699` 的六项实际 push Actions 已逐项核验成功：Frontend `42849578268`、Blocking `42849578229`、Replay `42849578274`、Lint `42849578137`、E2E `42849578311`、Unit `42849578289`。这不是新模块的 CI。

[持久隔离接收](DevPilot_External_QA_Quarantine.md)新增单独 human/owner/create/read 授权的技术声明 API，显式绑定完整 baseline 历史导出和冻结 plan。ALL 总体/预算、canonical 与原始声明 SHA 区分、off-loop 重检、project/export/plan 锁与原子审计、不重发和重复取消排空均保持；一致伪造仍为 NOT_EVALUATED。候选 `eval_0014` 新增两表两索引，未部署。本轮最终专项 **68 passed**（含 foreign-keys ON SQLite/独占临时 PostgreSQL），联合 **317 passed / 1 warning**；标准后端 **13,332 passed / 19 skipped / 11 deselected / 40 warnings，863.98s**，领域 **15 / 58**、Blocking IO **72 passed**、Ruff **1,276 files** 和 offline lock 通过。前端运行时未变：完整 **155 files / 1,312 passed**、ESLint/typecheck/整个 frontend Prettier 通过，七份公开模块指南另行格式核验。本轮没有本地重跑 build/browser/性能，不冒用前轮结果。

原始 API404 红灯、首轮分母夹具失败及 `tables.py` 格式诊断保留；仅修正夹具 coherence 和格式，不放宽断言/总体。格式修正后重新同步、核对最终源码并运行完整门禁，**1,396 / 852** 份受测公开源码与宿主一致。证据复制/验 hash、精确四个专用 CI 资源收尾、独立提交/推送与新 SHA 实际 Actions 分别闭环；此时尚未提交，不以本地成功或前轮 CI 代表交付。无部署、执行启用、真实调用或正式批准。

## Authorized configuration export workspace local verification (2026-11-10)

[工作台合同 / Workspace contract](DevPilot_Authorized_QA_Export_Workspace.md)接通已交付 exporter：显式 policy/grant/冻结来源、三份创建确认、独立下载确认、原 ID GET-only 对账、跨项目 pending/锁和有界 ZIP pin 校验。新增 owner/human/read-only policy metadata，无敏感 SQL/key；候选仍为 eval_0013，无新增依赖/迁移/权限 action、部署或真实调用。本模块最终本地门禁已通过；资源、提交和新 SHA CI 分别核验，不由本地成功推断已交付。

上一模块精确 SHA `8b43028c8f1faa062ebd789e40241931a02bde76` 的五项实际 push Actions 已核验全成功：Unit `42834487025`、Frontend `42834486900`、Blocking `42834486912`、Lint `42834487249`、Replay `42834487162`。独立 installed-export/distribution/default-install jobs 亦成功；这是上一模块，不是本轮 UI 的 CI。

本轮最终本地结果：后端专项 **71 passed**，标准后端 **13,260 passed / 19 skipped / 11 deselected / 40 warnings**，领域 **15 / 58 passed**，Blocking IO **72 passed**；Ruff **1,271 files** 和离线锁通过。前端专项 **19 passed**、完整 **155 files / 1,312 passed**，lint/typecheck/整个 frontend Prettier、production build 及原六路由性能预算通过；真实合成 API ZIP 浏览器专项 **5 passed**、完整 Chromium **236 passed**、认证恢复 **2 passed**，浏览器零重试。原接口/expiry/schema/type/format 红灯保留，不弱化断言或跳过原门禁。1,391 / 852 份受测公开源码与宿主一致，初始 72 份证据导出验 hash；最终文档、专用资源、提交归档和 exact-SHA Actions 独立核验。不是 Windows、真实用户/目标、部署或正式批准验收。

## Authorized QA configuration export candidate (2026-11-10)

The [recipient/grant-bound exporter](DevPilot_Authorized_QA_Exports.md) adds default-disabled human/owner API creation, immutable encrypted configuration ZIPs and ordered audit. Existing CLI plus separately pinned software; skeleton or explicitly authorized ALL baseline inputs never include request values, acceptance/gold or historic outputs. ALL request values must be rebound. Candidate head is `eval_0013`; no UI, runtime deployment, execution permission, result import or approval.

Previous exact SHA `26d4592734bf8939175d7fa26499814eb556050c` has all four actual push Actions successful: Unit `42812024806`, Lint `42812024235`, Blocking `42812024532`, Frontend `42812024282`. Not this module CI. Focused 67 passed included SQLite/owned PostgreSQL and API export → fresh offline full install → installed CLI mock send/receipt/same-ID reconciliation. Template corruption regressions failed before the private validation fix. Joint testing then caught a pure-distribution CI isolation violation; fix separates installed API verification without weakening the existing check. Final full/source/evidence/resource and new exact-SHA Actions remain required. No deployment/real calls.

Final module-local verification: focused **88 passed / 1 warning** (including
actual fresh offline installed CLI and SQLite/owned PostgreSQL migrations), joint
**397 passed / 1 warning**; standard backend **13,254 passed / 19 skipped /
11 deselected / 40 warnings / 841.65s**, domain **15 / 58 passed**,
Blocking IO **72 passed**, Ruff **1,270 files** and offline lock passed.
Frontend runtime source is unchanged: full **152 files / 1,293 passed**, entire
frontend Prettier, ESLint and TypeScript passed in this module. No local build,
browser/Windows/real-user acceptance, deployment or real calls are claimed.

The first full run retained **5 failed / 13,242 passed**: its independent exact
permission inventories lacked the three new export actions. Explicit inventories
and ordered provider requests were extended, with six action/failure-mode cases;
no wildcard assertion, authorization policy change or failure suppression.
A separate red regression exposed expiry between grant checking and receipt time;
creation now fails privately without an archive/audit. Template-corruption and
pure-distribution isolation failures also remain in the retained diagnostics.
The second full run passed, but its following format check found a stale
container copy of `deps.py`; that file was synchronized and the exact final
source was fully retested. No source mismatch is waived by a green test count.
Successful local gates do not prove push or CI: final source/evidence/resource
receipts and the new exact-SHA Actions, including the separate installed-export
job, require independent verification. The whole platform remains incomplete.

## External technical metadata inspection candidate (2026-11-10)

The [App-owned strict parser](DevPilot_External_QA_Metadata_Inspection.md) adds original-ID pairing, bounded exact JSON schemas, caller-declared raw hash checks and ALL frozen denominator/aggregate coherence for existing local receipt/reconciliation documents. Output remains NOT_EVALUATED/unverified even for a coherent forged pair; no evidence/output/provenance/approval/dispatch authority is granted. No upload route, persistent quarantine, database mutation, migration, dependency, deployment or real calls. This is a prerequisite, not completed platform result import or authorized data export.

Previous module exact SHA `5484861e18d530b4dac83d96dff3f00342f28b40` has all four actual push Actions successful (Unit `42805147759`, Lint `42805147543`, Blocking `42805147771`, Frontend `42805147653`), including its distribution job. Those results are not the new module CI. Candidate App head stays `eval_0012`; prior runtime receipts are historical, not new-machine acceptance.

Module-local gates are now terminal: new **111 passed**, joint **984 passed**;
standard backend **13,180 passed / 18 skipped / 11 deselected / 40 warnings /
774.85s**, Blocking IO **72 passed**, Ruff **1,264 files** and offline lock.
Frontend **152 files / 1,293 passed** and entire Prettier passed; frontend
runtime source is unchanged. Final documentation/source/evidence/resource and
new exact-SHA Actions closure are separate receipts, not inherited CI. No new
browser/Windows/real-user acceptance, deployment or real target/model calls.

## 2026-11-10：独立本地 QA 锁定软件分发候选

前序发送前身份回执模块的精确远端 SHA 为 `9fe951fbb7e4f4c0a9af29436618379b13ef672b`，四项实际 push Actions 均 completed/success（attempt 1）：Unit Tests `42791646112`、Frontend Unit Tests `42791645774`、Backend Blocking IO `42791646131`、Lint Check `42791645950`。其源码/证据和四个专用容器已闭环，无部署。

新增[software-only 锁定分发](DevPilot_Local_QA_Distribution.md)：九项运行依赖按现有 backend lock 的原始 wheel hash/大小核验，六项构建工具独立 hash 锁定，第一方全部 35 个源码成员与 metadata/RECORD 检查，拒绝额外代码/entrypoints。独占 ZIP 只含软件/许可/合成示例；外部可信 archive hash 后在新无系统依赖 venv 离线完整安装，实际已安装入口默认离线、mock 执行和原 ID 对账。内部 hash/声明 SHA 不是签名或平台来源认证。

这是软件交付，不是平台授权数据导出/导入、输出加密保留、冻结 QA 调度、Lost Worker fencing、正式批准或部署验收；这些仍未完成。App/head 仍 eval_0012，旧 eval_0009 部署收据不能代表本机运行时。新模块完整测试、源码/证据、专用资源、提交 push 与 exact-SHA Actions 分别闭环；不提前宣称 CI 或平台完成。

Final module-local gates: new **61 passed / 9.85s**, joint **873 passed / 152.69s**; standard backend **13,069 passed / 18 skipped / 11 deselected / 40 warnings / 753.49s**, domain **15 / 58 passed**, Blocking IO **72 passed / 5.56s**, Ruff **1,262 files** and offline lock passed. Frontend runtime source is unchanged: full **152 files / 1,293 passed / 12.5s** and entire Prettier passed; final module documentation is checked separately. A fresh six-tool hash-locked build venv produced real sdist/wheel; a fresh nine-dependency offline runtime venv passed default-offline, five mock sends, every pre-dispatch receipt and original-ID reconciliation. Missing/tampered wheels were rejected and two same-input archives were byte-identical. Final archive SHA256: `2dd2964219f5ed8b1186b1a6fd2ded4921f81566b212045c011f9c7d0e27f21e` (declared baseline revision, not this commit's authenticated provenance). Intermediate and fixture/static-check diagnostics are retained; no retry, weaker assertion or longer timeout hides failures.

No local browser, frontend build/lint/typecheck, performance, Windows or real-user acceptance was rerun, and previous module results are not borrowed. The new commit's Actions run their existing gates independently. Public source/evidence hashes, exact resource shutdown, commit/push and exact-SHA Actions have separate module receipts; local success and push are not CI success.

## 2026-11-10：本地发送前身份回执候选

前序原 ID 只读对账模块已推送并独立核对为 `a60a6ee1de83d67ebf1c5a72432a05f6d1ea89a7`；该精确 SHA 四项实际 push Actions 均 completed/success：Unit Tests `42783637102`、Frontend Unit Tests `42783637233`、Backend Blocking IO `42783637338`、Lint Check `42783637573`。源码/证据/四个专用容器均已闭环，无部署。

新增[独立 run 身份回执](DevPilot_Local_QA_Run_Receipt.md)，避免异常后为取得原 ID 而打开敏感输出。独占 write/fsync/close 必须先于 start/reserve/DNS/send；未知即停、重复取消排空、原 ID 只读且不恢复。仅固定技术字段，不声明当前状态、provenance、成功或批准；缺失不能证明未发送。现有单一最终 stdout、ALL 冻结分母和不重发合同不变。候选 head 仍 eval_0012，历史部署收据 eval_0009 不代表本机验收。完整授权导出/锁定发行/输出治理/隔离导入/调度/Lost Worker/正式批准与授权升级仍未完成。

本模块最终本地门禁：新增 **26 passed**（3.85s），执行/对账/共享核心/平台主链联合 **812 passed**（150.88s）；标准 `make test` **13,008 passed / 18 skipped / 11 deselected / 40 warnings**（758.55s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.62s）；Ruff **1,261 files**、变更领域源独立 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（11.2s），完整 Prettier 与九份模块说明核验。真实 sdist→wheel 十三个公开成员逐 bytes 相等，隔离 `-I` 实际 wheel 每次 mock wire 均先验证回执，再由实际 wheel 原 ID 对账，显式检查两个入口的 wheel import origin；真实 DNS/socket 与业务 imports 禁止。未重跑本地 frontend build/browser/performance，不把 wheel 当完整锁定发行。源码/证据/专用资源与新 SHA 的实际 Actions 分别闭环；无部署、执行启用或真实调用。

## 2026-11-10：显式独立本地 QA 命令候选

前序本地 journal 模块已在远端 main 独立核对为 `95ddbbacb3c051db471d877b8ec6227e47ef10b6`；该精确 SHA 的四项实际 push Actions 全部 completed/success：Unit Tests `42765155874`、Frontend Unit Tests `42765155959`、Backend Blocking IO `42765156239`、Lint Check `42765155889`。先前未执行的 push 权限超时不作为成功证据；本次以远端状态与实际 Actions 关闭上模块交付，不推断是谁完成推送。无部署。

新增[独立本地命令](DevPilot_Local_QA_Command.md)：默认离线预检，分离结构 manifest、显式敏感 bindings、input-only 数据；三重实发/输入/私有明文输出确认、精确 host 与 ALL-answer DNS/TLS、独占目录、共享完整 run/collector 和 one-shot journal。输出为 external_unverified_technical_only / NOT_EVALUATED，失败/取消保留原目录、未知不重发；不是加密平台证据、批准、平台授权 exporter 或完整依赖发行。无 App/API/迁移/依赖/配置/部署变更。本模块门禁、源/证据核验、资源收尾及新 SHA Actions 单独记录。

本模块最终本地门禁：CLI 新增 **83 passed**，journal 专项 **82 passed**（含新增三项确定性锁回归），联合 **722 passed**（141.92s）；标准 `make test` **12,918 passed / 18 skipped / 11 deselected / 40 warnings**（761.90s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.72s）；Ruff **1,259 files**、两份领域源独立 lint/format、offline lock 全通过。前端完整 **152 files / 1,293 passed**（13.3s），完整 Prettier 与八份模块文档格式独立核验。实际 sdist→wheel 十二个公开成员逐 bytes 相等，`-I` 实际模块离线/完整 mock run 均通过，真实 DNS/socket 与 business imports 禁止。最终源码、证据、提交归档、专用资源收尾与新 SHA 的实际 Actions 另行闭环；未重跑本地 frontend build/browser/performance，无部署/执行启用/真实调用。

候选迁移仍 `eval_0012`；历史部署收据 `eval_0009` 不代表本机已重新核验。完整授权导出/数据交付合同、外部结果隔离/导入、冻结 QA 独立调度、Lost Worker 对账、正式批准和另行授权的升级/真实用户验收仍未完成。

## 2026-11-10：独立本地 QA run 耐久适配候选

共享完整 run 模块已推送 `f8cd909db191949a69e3fb04d0339a6bea6aae96`，该 SHA 四项 push Actions 实际 completed/success：Unit Tests `42756807606`、Frontend Unit Tests `42756807999`、Backend Blocking IO `42756807779`、Lint Check `42756807505`。47 份证据与 1,372 Python/858 Node/文档源和提交归档核验通过，四个专用 CI 容器已停止；E2E/Replay/Skill Review 未触发，未部署。

[本地耐久适配器](DevPilot_Local_QA_Run_Journal.md)实际复用共享完整 run，不复制 runner；增加私有 SQLite WAL/FULL、独占新建、每 ordinal 一次与累计预算、未知不重发、重开只读和完整读写取消排空。源 hash 不证明来源/值相等，collected 仅外部未核验技术状态；无 App API/迁移/依赖/部署/执行启用。授权 exporter/CLI、输出治理和结果隔离仍须后续闭环，不能把本模块当作整个平台完成。本模块最终门禁与精确新 SHA Actions 另行核验。

本模块最终本地验证：新增 **79 passed**（最终源码复核 5.58s）；联合 **636 passed**（130.45s）；标准 `make test` **12,832 passed / 18 skipped / 11 deselected / 40 warnings**（756.54s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.57s）；Ruff **1,258 files**、新领域模块单独 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（11.4s），完整 Prettier 与七份模块文档格式独立核验。真实 sdist→wheel 的十个公开成员逐 bytes 相等，实际 wheel 在 `-I` 解释器中使用锁定 HTTPX 完整 mock run，禁止 business imports、真实 DNS/socket；不是无 site packages/零依赖或授权 exporter。联合开始后的最后源码编辑仅纠正文档字符串；最终新增回归、wheel 和完整后端均覆盖该最终源码。

首轮 rollback journal、ordinal 完成顺序和后续 WAL 最后连接清理竞争的失败均保留；修正 WAL/逐 ordinal CAS/无事务 idle anchor，并以 drained close 撤销 claim，不加入重试或放宽断言。最终源文件/提交、证据 hash 与专用资源收尾分别核验；无本地 frontend build/browser/performance 重跑、部署或真实模型/目标调用。

> 核对日期：2026-11-10。此页区分**代码已实现、运行已部署、测试证据与未完成范围**，不以功能数量估算完成百分比，也不替代最终用户验收。各切片文档记录当时边界；旧文中的“未部署 / Worker pending / report pending”不是此后的当前状态。

## 2026-11-10：共享完整有界 QA JSON run 候选

共享单次采集模块已推送 `5d070b3f4d000c09366bf0ac628c76a2fa6973ae`，该 SHA 四项 push Actions 实际 completed/success：Unit Tests `42750837938`、Frontend Unit Tests `42750837894`、Backend Blocking IO `42750837936`、Lint Check `42750837889`。E2E/Replay/Skill Review 未触发；46 份导出证据、1,370 Python/858 Node/文档源与提交归档核对通过，四个专用 CI 容器已停止，未部署。

[本模块完整 run 核心](DevPilot_Shared_QA_JSON_Run_Core.md)共享真实 Worker 的 consumer/monitor/group，而非再复制 runner。显式 clock/reserve/collect/record/check-active，App 保留授权、全局和整 run 配额、动态出站、加密证据及所有 DB 读写排空，finish 在核心返回后执行。dispatch ACK 先于发送、未知结果先停发再记录、deadline/取消和全量分母不变；无默认客户端/凭据、迁移/依赖/新 API、部署或执行启用。

本模块本地最终门禁：新增 **62 passed**；最终联合 **549 passed**；完整后端 **12,753 passed / 18 skipped / 11 deselected / 40 warnings**，领域 **15 / 58 passed**，Blocking IO **72 passed**；后端 Ruff **1,257 files**、共享 run/attempt lint/format 与离线锁通过。前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。28 组旧/新真实 Worker 数据库/HTTP 行为逐字段对照及实际 wheel 完整 mock run 通过；静态 AST 另证原 DB-drain/serve、consumer/timeout/cleanup 保留。最终源码/提交归档、证据 hash、专用资源收尾及新 SHA Actions 分别核验。未重跑本地 frontend build/browser/performance，无部署、执行启用或真实模型/目标调用。其余授权导出/CLI/结果隔离、失联 Worker fencing/对账、冻结 QA 调度、正式批准及经授权的部署/真实用户验收仍未完成。新提交仍独立核对实际精确 SHA Actions，不借用上一轮成功。

## 2026-11-10：共享固定目的地 HTTP 传输候选

[共享传输](DevPilot_Shared_Pinned_HTTP_Core.md)提取现有 origin/Host/SNI/TLS/零重试实际机制，原 App 接口委托且每次按动态 operator policy 审核 ALL DNS answers；callback 结果必须是 literal 无 scope IP。保留原 client、准入/预算/dispatch/no-resend/取消关闭语义。首次原出站/调试/调度/采集联合 139 passed，最终完整门禁和新提交实际 Actions 独立核验；无依赖/迁移/部署/真实调用，不是完整独立 runner/exporter。

## 2026-11-10：共享 QA JSON 请求准备核心候选

请求准备核心已推送 `ec9c37b262666a80e2083f472ae41b626d510ee1`，四项 push Actions 实际 completed/success：Unit Tests `42737409116`、Frontend Unit Tests `42737409596`、Backend Blocking IO `42737409159`、Lint Check `42737409240`。E2E/Replay/Skill Review 未触发。38 份证据及 1,366 后端/领域与 858 前端/模块说明源码和提交归档核验通过，四个专用 CI 容器已停止，未部署。

[固定纯请求投影](DevPilot_Shared_QA_JSON_Request_Core.md)将已渲染 FrozenRequest 的原样 URL/method/body/headers、条件 identity 准备提到纯版本 `qa-json-request.v1`，App 已实际共用。保留原 64 headers 派生 65 边界、显式编码及原 deadline 内 content 编码；不增执行/导出/批准权限，不改历史 hash，无依赖/迁移/部署/真实调用。新增 58 项回归；349 项联合主链、119 个旧/新实际请求与响应对照、隔离源码/实际 wheel 自检通过。完整后端 **12,610 passed / 18 skipped / 11 deselected / 40 warnings**，领域 **15/58**、Blocking IO **72**、Ruff **1,254 files** 和离线锁通过；完整前端 **152 files / 1,293 passed**、完整格式通过。未重跑本地 build/浏览器/性能；源码/证据与实际新 SHA Actions 单独核对。完整 runner/exporter、冻结 QA 调度与失联 Worker 安全运维仍未完成。

## 2026-11-10：共享 QA JSON 响应核心候选

响应核心已推送 `e32cb3d81b64ed8f79411f22a049a3f0669c37e2`，该 SHA 四项 push Actions 均 completed/success：Unit Tests `42731902942`、Frontend Unit Tests `42731902497`、Backend Blocking IO `42731902510`、Lint Check `42731902918`。E2E/Replay/Skill Review 未触发；59 份证据及 1,364 后端/领域和 858 前端/模块文档源码与提交归档核验通过，四个专用测试容器已停止，未部署。

[纯响应核心](DevPilot_Shared_QA_JSON_Response_Core.md)固定单次 HTTP JSON 的头部优先级、max+1 缓冲和严格 binding 输出提取；App 改为共用这一实现，解码与提取一起 off-loop。正常 end-of-body 才 finalize，失败/取消不收集且不重发。无新依赖、迁移、API/权限、部署或执行启用；不更改历史计划/hash，不等于完整 runnable exporter 或正式批准。

本模块新增 90 项回归，联合定向 291 passed；最终后端 12,552 passed / 18 skipped / 11 deselected，分层 15 / 58、Blocking IO 72、前端 1,293 passed，Ruff/锁文件通过。旧版对比发现并修复状态 600 分类差异后，49 个合成场景全部等价，再完整重跑最终源码门禁，保留初次失败。实际 wheel/隔离解释器、公开源码与证据 hash、精确资源收尾和新 SHA Actions 另行核对；前端无运行时代码改动，不借用前一模块 build/browser/performance 成绩。完整共享执行导出、失联 Worker 安全运维、调度与正式批准仍未完成。

## 2026-11-10：QA 生命周期重复取消排空候选

该模块已推送 `d7f61efe8dc17fe13e5cb464303a084d3fd9ed92`，四项 **push** Actions 均 completed/success：Unit Tests `42723748642`、Frontend Unit Tests `42723748670`、Backend Blocking IO `42723748656`、Lint Check `42723748676`。同 SHA 的定时 Nightly Build `42725168993` 因仅上游仓库可运行而 skipped，另列且不算通过；E2E/Replay/Skill Review 未触发。37 份原始证据 archive/member hash 及源码/提交归档核验通过，四个专用 CI 容器已精确停止；没有部署或业务服务改动。

[关闭排空修复](DevPilot_QA_Shutdown_Drain.md)在有序 Gateway 关闭中仅取消原 Worker 一次，重复外层取消等待同一 shield waiter，排空后再传播取消并清除 repository。原 finish/配额/dispatch-before-send/未知结果不重发语义不变；不增加排空超时、重试、forced-release 或执行启用。

- 旧运行基线先复现 **7 failed / 4 passed，6.75s**，含原 Worker 的双 collector/临时迁移 DB；不是仅凭理论改实现。新增 **8 项**事件屏障/异常保留/真实 Worker 测试，修复后联合主链定向 **82 passed，114.54s**。
- 修正专用 PostgreSQL/Redis 未启动的环境问题后，同一完整后端 **12,462 passed / 18 skipped / 11 deselected / 40 warnings，730.48s**；原首轮 **3 failed / 7 errors** 及旧代码红灯日志均保留，不弱化断言。Blocking IO **72 passed，5.49s**、Ruff 全目录 **1,252 文件**及离线 lock 检查通过。
- 完整前端 **152 files / 1,293 passed，14.9s**、整个 `pnpm format` 与七份模块 Markdown 格式通过；本机不重跑 build/浏览器/性能预算，不借用前一模块结果。公开 Python **1,362**、Node/说明 **857** 份源码逐项核对；成功/失败证据导出验 hash 后按精确 ID 收尾本模块四个专用容器，不改业务服务/镜像/卷。
- 本地门禁不等于 push 或 CI；本模块需独立推送 SHA 和所有实际 Actions 收据，后续开发不得携带可归因的失败。
- 无 API/权限、依赖、迁移、运营配置或部署变更，候选 head 仍 `eval_0012`。本地有序关闭不是丢失 Worker 死亡证明、远端取消或强制释放授权；安全自动恢复仍未完成。

## 2026-11-10：原路由资源预算修复候选

预算模块已推送 `6142029b921319e33c8819713f750ebbc3a497f9`，五项实际 Actions 均 completed/success：E2E `42687421415`、Frontend Unit Tests `42687421466`、Unit Tests `42687421868`、Replay E2E `42687421198`、Lint Check `42687421271`。未触发的 Backend Blocking IO / Skill Review 不记为通过；全部 **856** 份前端/模块说明与实际容器、提交归档逐项核对无缺失/不符，**42** 份证据与 archive/member hash 核验后清理本模块精确临时文件并停止唯一 CI 容器，业务服务未操作。

新增[路由预算与加载边界](DevPilot_Route_Resource_Budgets.md)：精确构建期 page-map AST 投影避免 docs/blog 导入工作台运行页面；原有完整 raw HTML palette 移到真正 Markdown/memory 懒加载边界，完整 Streamdown chunks/runtime/public sources 保留。无新依赖、迁移、后端行为、配置或部署，不改预算/路由/测量。

- 原 `pnpm perf:check` 六条路由均通过：CSS login/root **164719**、chat/list **189391**、docs/blog **267689** bytes；docs/blog JS **4436096 → 1013381** bytes。chat CSS 仅 **609 bytes** 余量；指标是既有入口原始字节，不是全量 lazy assets/交互延迟或真实认证验收。
- 新 loader/config **28 项**及样式编译/完整历史 palette **3 项**通过；完整 frontend **152 files / 1293 passed**。完整格式、ESLint、typecheck、Webpack 和 Turbopack 实际生产 build 均通过；完整模拟 Chromium **231 passed / 2.5m**、独立认证恢复 **2 passed / 1.2m**，均明确 `retries=0`。本模块不改后端，未在本机重跑整个后端。
- 无效包导入优化与第一候选重复 CSS（thread **360187** bytes，失败）均保留；通过 source-free theme tokens 和进一步 Markdown lazy child 修复，不隐藏失败，不删断言/路由或提高预算。

本机 ignored 证据 `.deer-flow/ci/20261110-route-resource-budgets/`；源码/导出 hash、资源收尾和精确 SHA 的实际 Actions 单独核验。本模块不改后端，不借用历史全量成绩，不等于部署或整个平台完成。

## 2026-11-10：管理员执行诊断工作区候选

该工作区已推送 `833897a367ea8ef0a1a030f4e1e93dc098caec11`，五项实际 Actions completed/success：E2E `42678402551`、Frontend Unit Tests `42678402624`、Lint Check `42678402195`、Replay E2E `42678402254`、Unit Tests `42678402516`。Backend Blocking IO / Skill Review 未触发，不记为通过；下面保留该提交本地性能失败，后续预算模块的通过不改写其原始回执。

新增[执行诊断工作区](DevPilot_Execution_Diagnostics_Workspace.md)：显式管理员只读入口、16 KiB 严格流式 JSON、五态/全局合计校验、超策略占用不截断、同步锁与账号/角色/卸载迟到响应屏障。仅手动 GET，无轮询/重试、敏感读取、持久化缓存、释放/回收/执行控件。无后端运行行为、依赖、迁移、配置或部署变更；安全释放和平台其余能力不因此完成。

- 新增严格读取/真实 React HappyDOM **56 项**，完整前端 **150 files / 1,262 passed**，Prettier、ESLint、typecheck 和生产 build 通过；新页纳入生产路由，不新增依赖。
- 完整模拟 Chromium **230 passed，2.4m**；独立认证恢复 **2 passed，1.1m**，均明确 `retries=0`。桌面/手机/中文/角色切换为合成浏览器回归，不是真实用户部署验收。
- 后端仅复核相关授权/诊断/执行/真实登录主链：**82 passed / 1 warning，118.07s**；Blocking IO **72 passed / 2 warnings，11.52s**，Ruff check/format **1,252 文件**通过。本模块不改后端运行代码，不冒称本地再次运行整个后端单测；上轮全量 12,454 passed 另列。
- 编写阶段 mock API、夹具类型/ESM 导入以及四个浏览器定位器范围失败均保留；修正测试工程/精确 region 与 navigation，不删除用例、关闭类型/lint 规则、放宽断言、加超时或自动重试。

- **性能预算未通过，不能归入通过门禁**：`pnpm perf:check` 的六条现有路由 CSS 超额，docs/blog JS 也超额。同容器、相同依赖、相同脚本对照模块前 `4f94b2c0a73a00a023fffafbcb06f01919c13b4c` 也失败；本次各路由 CSS 增加 40 bytes，docs/blog JS 从 4,428,342 增至 4,436,096 bytes（预算 4,200,000）。不抬高预算、不删除基准路由，既有超额及小幅增长均交下一独立性能模块修复；不是“全部前端门禁通过”。对照后本轮源码完整恢复并核对。
- 实际容器源码：前端 **841 文件**、后端/领域 **1,313 文件**和六份模块 Markdown 逐项核对，缺失/不符均为 **0**。本轮前端计数包含全部 tracked Markdown，与前轮仅格式快照的 827 口径不同。日志 archive/member hash 导出复核后，只停止本轮启动的两个专用 CI 容器；不删缓存/镜像/卷，不操作其他服务。

本模块本地通过项、已知性能失败与精确 SHA 的实际 Actions 分别记录；不借用上一提交的成功，也不把没有性能 job 的 Actions 成功当成本地预算成功。证据目录 `.deer-flow/ci/20261110-execution-diagnostics-ui/` ignored。

## 2026-11-10：执行占用只读诊断候选

后端诊断已实际推送 `4f94b2c0a73a00a023fffafbcb06f01919c13b4c`，五项实际 Actions 均 **completed / success**：Unit Tests `42667511672`、Frontend Unit Tests `42667511178`、Backend Blocking IO `42667511516`、Lint Check `42667511640`、Replay E2E `42667511283`。E2E/Skill Review 未触发，不记为通过；此回执不是部署验收。

新增[只读运维诊断](DevPilot_Execution_Reservation_Diagnostics.md)：人类管理员 + 独立 `evaluation_operations:read`，一条 SELECT 聚合仍占用的配额/状态/deadline，显式不证明 Worker 死亡、不是可用槽位或全局策略一致性。不读 IDs/claim/敏感证据，不写 guard/审计/运行、不释放/回收/重发或执行；无迁移/依赖/前端运行变更。安全释放、调度准入和正式批准仍未完成。

- 新模块 **22 项**，连同既有授权清单/执行/真实登录主链联合定向 **82 passed / 1 warning，98.00s**。标准 `make test` **12,454 passed / 18 skipped / 11 deselected / 40 warnings，681.81s**；含纯领域 **15 / 58 passed**，不与定向重复叠加。
- `make test-blocking-io` **72 passed / 2 warnings，5.60s**；`make lint` Ruff check/format **1,252 文件**、`uv lock --check --offline`、完整 frontend Prettier 和七份模块 Markdown 检查通过。**1,313** 份后端/领域实际源码及 **827** 份前端格式快照逐项核对，缺失/不符均为 **0**。
- 专用 PostgreSQL 会话 TEMP 表通过空集/跨 owner 合计/deadline 相等/interrupted 保留/已释放排除/无敏感投影六项检查；无持久 DDL/数据变更，不冒称生产 PostgreSQL 验收。首次夹具缓存断言和全量固定权限清单失败日志均保留；同步新权限的精确列表及逐项 provider 请求断言，不改运行授权、不放宽断言、不增加超时或重试。

没有前端运行变更，本模块不冒称再次运行前端单测/typecheck/build/浏览器；新提交的精确 SHA 与实际 Actions 单独核实，不能借用前一提交的成功。本机 ignored 证据目录 `.deer-flow/ci/20261110-execution-diagnostics/`；所有进程结束和导出逐项 hash 核实后，仅停止本模块启动的四个专用 CI 容器，保留业务服务、缓存和卷。

## 2026-11-10：真实登录的合成多账号 QA 回归候选

真实认证回归已实际推送 `55cf3a80d3026f15b0e80399ab8fb9b52f032cc6`，四项实际 Actions 均 **completed / success**：Unit Tests `42659502653`、Frontend Unit Tests `42659502573`、Backend Blocking IO `42659502602`、Lint Check `42659502551`。该测试/文档提交未触发 E2E/Replay/Skill Review，不将未触发当成功；不是部署或真实用户验收。

新增[真实认证离线主链回归](DevPilot_Authenticated_QA_Regression.md)：临时 DB 五个独立合成账号，真实密码登录、JWT/数据库/token-version、CSRF 和启用的 fail-closed RBAC，接通双盲/仲裁、历史评估/报告/复测及 Word/PDF。不挂载旧合成身份中间件，不改运行权限/依赖/迁移。真实账号/浏览器/部署验收与正式批准仍未完成。

- 新模块 **18 项**与既有主链/任务/PDF 路由联合定向 **63 passed，132.04s**。标准 `make test` **12,432 passed / 18 skipped / 11 deselected / 40 warnings，676.37s**；含纯领域 **15 / 58 passed**，与定向不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.61s**；`make lint` Ruff check/format **1,248 文件**与 `uv lock --check --offline` 通过。实际测试的 **1,309** 份后端/领域公开源码逐项核对，缺失/不符均为 **0**。
- 完整 frontend Prettier 与六份变更 Markdown 格式检查通过；本模块不改前端源码，不冒称再次运行前端单测/类型检查/构建/浏览器，也不借用上一提交的 Actions。编写阶段 cookie/路由夹具错误与最终日志均保留，未改运行 cookie、放宽断言、增超时或重试。

本模块仅新增测试/说明，不改运行权限、配置、依赖、迁移或默认禁用执行；候选 head `eval_0012`、历史部署收据 `eval_0009` 不变。本模块上列精确 SHA 的四项实际 Actions 已核实成功，不能冒用为后续提交的 CI。ignored 本机证据在 `.deer-flow/ci/20261110-authenticated-qa/`，测试全部结束、日志导出验 hash 后仅停止本轮启动的四个专用 CI 容器，保留依赖缓存/业务服务/卷，无部署、真实调用或正式批准。

## 2026-11-09 开发 / 2026-11-10 收尾：独立历史报告/重测 PDF 候选

PDF 候选已实际推送 `56c641637d3561f0fa4b5247da01c1549fc2d1d5`，精确 SHA 实际触发七项 Actions **全部 completed / success**：Unit Tests `42651605785`、Frontend Unit Tests `42651606003`、Backend Blocking IO `42651605741`、Lint Check `42651605792`、E2E Tests `42651605830`、Replay E2E `42651605934`、Skill Review CI `42651605943`。这是候选源码 CI，不是本机部署或正式批准。

新增 [独立历史 PDF 草稿](DevPilot_Independent_PDF_Drafts.md)：`independent-qa-pdf-v1` / `independent-retest-pdf-v1` 只读取既有固定 Word-v1 renderer 的内部历史公开投影，分别保持存储 Markdown/历史收据与无 Markdown 的重测公开比较事实。人类 owner + read/review、已查看 hash、off-loop 完整性/渲染、ALL 冻结总体、精确 namespace、显式下载/ref 锁/迟到响应屏障和不重试均保持。旧 Word、档案、模板和 hash 不变。

固定 A4 文字/表格布局，逐页草稿标记、嵌入可重现 OFL 衍生字体、引擎版本/字体 SHA 检查、整文页数/字节上限；不支持的 glyph/组合字符/复杂方向整体拒绝，不静默替换/裁掉样本。无 HTML、外部资源、系统字体回退、链接动作、附件、签章或批准。字体两次独立构建 SHA 一致；PDFMiner/PDFium 独立读取/实际栅格检查不等于人工视觉验收、PDF/A 或 PDF/UA。

- 新旧 renderer/路由、独立档案与 API→真实离线 Worker 定向回归 **178 passed / 1 warning，121.46s**。标准 `make test` **12,414 passed / 18 skipped / 11 deselected / 40 warnings，702.64s**；纯领域 **15 / 58 passed**。定向/领域与全量不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.68s**；`make lint` Ruff check/format **1,247 文件**通过；字体构建脚本单独 Ruff check/format 通过。
- 前端完整单测 **1,206 passed / 148 文件**（最终测试文件复核 14.7s）；完整 Prettier、ESLint、typecheck、生产构建通过。完整模拟 Chromium **226 passed，2.5m**、认证恢复 **2 passed，1.3m**，均零自动重试；桌面/手机 PDF 使用真实合成二进制 fixture，不是真实多账号或模型/目标验收。
- 唯一新增运行依赖 `reportlab==4.4.10`。Dockerfile 固定的 uv **0.7.20** 真实解析锁，且 uv **0.13.7** 检查兼容；两者 offline lock check 均通过。原 249 个包版本全部不变，仅增加一个包；Tenki 可选源只绑定原官方 0.4.0 wheel/同 SHA，应对索引 404，不删 extra、不换 SDK、不启用调用。字体构建工具只用于隔离构建。
- 实际测试源码与待提交文件按文本 LF/二进制原 bytes 核对：后端/领域 **1,308**、前端 **827** 个文件，缺失/不符均为 **0**。初始读取器/夹具失败和最终日志分别保留，未用重试、扩大超时或弱化完整总体断言掩盖错误。

候选 App head 仍为 `eval_0012`，历史部署收据仍为 `eval_0009`；无迁移、部署、生产配置/key、执行启用或真实模型/目标调用。正式批准政策/角色/生命周期、经授权保留数据升级、真实多账号与最终用户验收仍未完成。上列精确推送 SHA 的七项实际 Actions 已核实，不能将这些结果冒用为后续新提交的 CI；本机合成日志/hash/CI 回执只存 ignored `.deer-flow/ci/20261109-independent-pdf/`。

## 2026-11-09：独立历史重测 Word 候选

独立历史重测 Word 已在 GitHub 远端核实 `a3fb0db9de885a03e9883743216b5aca6c93665f`，六项 Actions 均 completed/success：Unit `42634173580`、Frontend Unit `42634173600`、Blocking IO `42634174621`、Lint `42634173290`、E2E `42634173439`、Replay `42634173556`。此前待推送回执由本次远端核验替代，不推断部署。

新增 [独立历史重测 Word](DevPilot_Independent_Retest_Word_Drafts.md)，以单独 `independent-retest-docx-v1` GET 导出显式打开的历史档案。重测没有存档 Markdown/报告 revision：此处固定双语白名单投影存档公开比较事实，保留全部冻结样本和两侧历史 assessment/任务承诺；不是重新渲染报告或重新计算指标/阈值。人类 owner + read/review、已查看 hash、off-loop 完整性/渲染、大小上限、文字安全、ref 锁/迟到响应屏障和错误不重试均保持。旧 owner/独立报告 Word、档案与 hash 不变，无依赖或迁移。

- 新旧 renderer/路由、独立档案与 API→Worker 定向回归 **148 passed / 1 warning，140.88s**；标准 `make test` **12,384 passed / 18 skipped / 11 deselected / 40 warnings，669.14s**，纯领域 **15 / 58 passed**。定向/领域与全量不叠加计数。
- `make test-blocking-io` **72 passed / 2 warnings，5.89s**；`make lint` Ruff check/format **1,244 文件**通过。MarkItDown 独立读取器输出会转义 Markdown 下划线；保留原始 OOXML 精确断言，并按读取器契约精确验证转义内容，不削弱样本总体/收据检查。
- 前端全量 **148 files / 1,182 passed**，完整 Prettier、ESLint、typecheck、生产 build 及本轮 Markdown 格式检查通过。完整模拟 Chromium **220 passed，2.4m**，单独认证恢复 **2 passed，1.6m**；均 retries=0。新导出包含桌面 1440px/手机 390px、键盘下载、真实生成 OOXML fixture、409 不重试与无敏感请求检查。
- Python 测试相关 **1,367 个**、Node 前端 **823 个**公开文件逐项 SHA-256 与工作区一致（共享 fixture 重叠，不相加宣称唯一文件数）；初始失败和最终日志导出到 ignored `.deer-flow/ci/20261109-independent-retest-word/`，包复制后验 hash，不提交私有数据或本地证据。
- 只使用本线程重建的隔离 Python/Node/PostgreSQL/Redis 缓存容器，无业务挂载/发布端口；全部测试退出、证据导出/核对和文档检查后只停止本轮启动的四个精确 ID，保留依赖缓存/业务服务/卷。精确源码 SHA 的实际 Actions 另行核对，成功 push 不等于 CI 成功。

候选 head 仍为 `eval_0012`，历史部署收据仍为 `eval_0009`；本模块没有部署、启用执行、生产 key 或真实模型/目标调用。该 Word 切片当时不含 PDF，后续 PDF 候选见本页首节；正式批准政策、经授权的保留数据升级、真实多账号和最终用户验收仍未完成。

## 2026-11-09：独立主链合成回归候选

新增 [独立主链离线集成回归](DevPilot_Independent_Workflow_Regression.md)，以 HTTP 创建的三个冻结样本、v2 计划和真实有界 Worker 串起独立双盲任务/第三人仲裁、评估修订、历史报告/同基准复测及固定 Word。并发 1/2、六种采集故障、四类写入提交前/后响应丢失，共 16 个参数化用例。无运行时代码、迁移、依赖或前端行为变化；不部署、启用运行、生成生产 key 或调用真实模型/目标。本地门禁完成，已提交并实际推送 `b1fe355c1c924b0a0073f154b7c25ee65f491e64`。精确 SHA 实际触发四项 Actions 均 completed/success：Unit Tests `42625066294`、Frontend Unit Tests `42625066349`、Backend Blocking IO `42625066311`、Lint Check `42625066514`。路径过滤未触发 E2E/Replay，不计为本模块浏览器 CI 通过。

- 新增集成用例 **16 passed，44.11s**；标准 `make test` **12,339 passed / 18 skipped / 11 deselected / 40 warnings，606.06s**，纯领域 evaluation/toolkit **15 / 58 passed**，均 exit=0。定向用例已包含在全量中，不叠加计数。
- `make test-blocking-io` **72 passed，5.50s**；`make lint` 全目录 Ruff check/format **1,241 文件**通过；整个前端 `pnpm format` 与本轮 Markdown 格式检查通过。没有前端运行时变更，本模块没有本地重跑前端单测/build/浏览器，上一模块结果另列而不冒用。
- 实际 Python CI 快照的 **2,178 个**公开源码/测试/静态文件逐项 SHA-256 一致；二进制原始字节和文本统一行尾分别处理。测试编写阶段失败日志和最终结果一起导出，本机 ignored 证据不提交。
- 仅复用本线程重建的专用 Python/Node/PostgreSQL/Redis 容器，internal 网络且没有业务挂载/发布端口。最终收尾在测试进程退出、日志导出/验 hash 和文档格式验证后进行；不停止预存服务，不删容器、卷或镜像，不全局 prune。

上一 Word 模块已实际推送 `86c13930cd688b55722020da2b68b74bb61d25c7`，精确 SHA 的六项 Actions **全部 completed / success**：E2E Tests `42620344093`、Unit Tests `42620343936`、Frontend Unit Tests `42620343965`、Backend Blocking IO `42620343994`、Replay E2E `42620343903`、Lint Check `42620343976`。这只是该候选提交的 CI，不是 `eval_0012` 部署或真实身份/目标验收。

## 2026-11-09：开发接续与独立历史报告 Word 候选

本轮接手时工作区干净，本地及实际远端 `main` 为 `8890bd061f3407b8c187ceaf388dff28aa463b4e`。该完整 SHA 实际触发四项 Actions，均成功：Unit Tests `42573792483`、Frontend Unit Tests `42573792602`、Backend Blocking IO `42573792621`、Lint Check `42573792762`；未触发 E2E，不外推其结果。较早章节保留历史状态，不是本轮运行收据。

首个模块新增单独的 `independent-qa-docx-v1`：人类 owner + read/review，显式历史档案 ID/已查看 hash，复用 off-loop 存档完整性验证并 off-loop 渲染。输出只有冻结 Markdown 与公开历史 assessment 收据；不重开证据/当前任务/模板、不重算指标、不替换 owner 票，旧 `qa-docx-v1` 和历史哈希不变。前端独立下载保持大小/MIME/renderer 校验、ref 锁和迟到响应围栏，无重试或写入重发。合同见[独立 Word](DevPilot_Independent_Word_Drafts.md)；整体缺口和接续顺序见[开发计划](DevPilot_Development_Plan.md)。

所有依赖从跟踪源码和锁文件重建到本轮专用 Linux Python 3.12/Node 22 容器；PostgreSQL/Redis 只含合成测试数据、无业务挂载或发布端口。依赖安装后容器仅 internal 网络；不复制本机私有配置、数据库、venv 或 node_modules。本机业务容器只读健康元数据，不据此宣称新版部署。

- 未修改源码基线：后端 `make test` **12,294 passed / 18 skipped / 11 deselected，681.24s**；纯领域 **15 / 58 passed**。前端 **148 files / 1,164 passed**。
- 本模块新旧 Word/独立档案定向回归 **61 passed，39.60s**；独立 Blocking IO **72 passed，28.37s**；Ruff 全目录 check/format **1,240 文件**通过。定向回归与全量有重叠，不叠加计数。
- 修改后前端全量 **148 files / 1,173 passed**；完整 Prettier、ESLint、typecheck 和生产 build 通过。合成 Word 桌面 1440px/手机 390px、键盘下载、真实生成 fixture、409 不重试：**3 passed，4.7s**，retries=0。
- 修改后标准 `make test` **12,323 passed / 18 skipped / 11 deselected / 40 warnings，807.32s**；纯领域 **15 / 58 passed**。完整工作区 Chromium **217 passed，2.4m**；独立认证恢复配置重建并测试 **2 passed，2.1m**，均 retries=0、exit=0。浏览器使用合成 API，不是部署或真实多账号验收。
- 两个实际 CI 容器各 **2,177 个**公开运行/测试文件与工作区逐项 SHA-256 一致（按 Git 统一文本行尾）；失败日志与最终结果一起保留在 ignored 本机会话证据目录。
- 首次基线收集缺少 Git 根标记、一次定向命令文件名错误，以及新增测试的格式/import/空函数 lint 失败均保留原日志；修正环境/命令/代码，不删除或弱化断言、不增加超时或重试。构建的无 Git 历史时间戳警告不是功能验收。

候选 migration head 仍为 `eval_0012`；无新迁移、依赖、生产配置、key、执行启用或真实模型/目标调用。该报告切片当时不含独立复测 Word（后续候选见本页首节）；PDF、正式批准、真实多账号联调、保留数据升级与最终用户验收仍未完成。本模块本地门禁及独立提交/push 已完成，精确 SHA 与六项成功 Actions 见上节；这不替代后续模块自身的 CI。收尾在确认测试进程全部退出、56 份成功/失败日志与退出码导出且六份主要日志验 hash 一致后，只按四个精确 ID 停止本轮专用 CI 容器；保留依赖缓存，没有停止预存服务、删卷、删镜像或全局 prune。

English: the continuation baseline and its four successful runs are explicitly pinned. The new independent historical report Word draft is a separate, bounded, read-only renderer; legacy exports and approval/execution boundaries remain unchanged. New local gates are recorded separately from previous CI and historical deployment; unfinished checks are not success claims.

## 2026-11-09：新电脑 CI 排查与 Worker 取消修复

本地与实际远端 `main` 已核对为 `c7ddbdc1417a589bbb544effb2e65630601823e8`。该 SHA 的六项 Actions 不是全绿：Frontend Unit Tests `42543077302`、Replay E2E `42543077373`、Lint Check `42543077333`、E2E Tests `42543077345`、Backend Blocking IO `42543077363` 成功；Unit Tests `42543077340` 失败，其默认安装收集 job 成功，后端 job `128922108984` 为 `1 failed / 12,291 passed / 18 skipped / 11 deselected`。原始 job 日志已下载并保留，失败是合成并发 Worker 收尾 `JournalWriteUnconfirmed`，不能归咎于换电脑。

新电脑初始仅见四个停止的旧 `deer-flow-dev` 容器；前电脑 `0fd689...` / `eval_0009` 的部署收据仍是历史验证，不宣称此机已有同一部署。未启动旧服务或读取其配置、账号库和日志。宿主默认 Python 3.11、不可执行旧 venv、pnpm 11 与 PowerShell 脚本限制均单独记录，不更改全局策略或降低仓库版本要求。

本轮独立 Linux Python 3.12、冻结依赖、PostgreSQL 17/Redis 7、internal 网络复现失败，临时观测确认 monitor SELECT 被取消后留住 SQLite 锁，最终 commit 失败。修复仅将 monitor DB 读取纳入现有排空保护；取消、无重试、未知结果不重发和配额保留语义不变，无迁移、依赖、运营开关或部署改动。

- 最终标准 `make test`：**12,294 passed / 18 skipped / 11 deselected / 40 warnings，596.69s**，exit=0；其中包含新事件屏障取消和重复取消回归。纯领域 evaluation/toolkit 由标准入口分别 **15 / 58 passed**，不与 pytest 数相加。
- 执行、真实 Worker 合成链及附件定向：**63 passed，22.38s**，与全量有重叠，不相加。旧 monitor 的确定性红测试先因提前 finish 失败，修复后通过，不靠增加超时、修改 WAL 或串行化请求。
- 原合成工作流全文件连续三轮各 **8 passed**；独立 Blocking IO **72 passed，6.55s**。这是重复稳定性和独立门禁验证，不与全量叠加计数。
- Ruff 全目录 check/format **1,237 文件**通过；整个 frontend Prettier 和本轮 Markdown 指南检查通过。前端运行源码没有改动，本轮不冒称重跑前端单测、浏览器或构建；Windows 全套也未重跑。
- 初始 slim 容器缺系统 MIME 数据库/Node，首次完整回归为 **3 failed / 12,282 passed / 25 skipped / 11 deselected**；补齐 CI 工具后原 XHTML 附件测试通过，业务 MIME 代码未改。原失败、收集命令引号失败及诊断日志均保留在 ignored 证据目录。

源码收尾核验 **1,360 个**受跟踪非 Markdown 运行/测试文件与实际回归容器逐项 SHA-256 一致，**15 份**日志导出并验 hash。确认测试进程已全部退出后，仅停止本轮三个 CI 容器、移除从未启动的精确 Node 工具来源容器及本轮 internal 网络；四个旧业务容器保持原停止状态，未删卷、镜像或共享缓存。测试证据/资源 ID 只在 ignored 目录保存，不计为部署证据。

当前修复完成后必须按新推送 SHA 单独核对 Actions；本节本地通过不是新 SHA 的远端成功。候选 head 仍为 `eval_0012`，没有业务数据迁移、真实模型/目标调用、正式批准或用户验收。[复现环境](DevPilot_CI修复与隔离开发环境.md)与[执行合同](DevPilot_Admitted_QA_Execution.md)记录细节。

## 1. 版本与运行边界

- 本轮起点：`main`，源码提交 `d2a58a390971`。后续工作区修改不属于该提交的 CI 证据。
- 最近独立核验的本地运行版本：`0fd689da83a4ac7646250447fb6d044599a823c5`，App migration head `eval_0009`。升级前在线一致性备份，保留原账号、配置、数据、挂载与 Harness ledger；详见[部署记录](DevPilot_Local_Recovery_and_Upgrade.md)。这是历史核验收据，不是每次打开本文就重新完成部署。
- 六项触发 Actions 成功仅属于上述完整运行 SHA；不得外推为当前 HEAD 或工作区 CI 通过。Windows 完整回归仍有独立失败，定向复验不能替代全量。
- 按最近部署记录，模型与请求加密 key 未配置，QA 执行保持默认关闭。不得为“完成度演示”自动生成 key、修改策略、调用真实模型/目标或导入客户原件。
- 本轮复用既有 Docker Python 3.12 / Node 22 隔离依赖；只导出 Git 源码与显式变更，不复制私有配置/数据库。测试结束停止本次启动的 CI 容器，缓存不等于过期垃圾。
- 本轮工作区新增 PostgreSQL `sslmode` → asyncpg `ssl` 兼容修复及回归；保留原 TLS 模式和同步 DSN，冲突/无效参数明确拒绝。当前运行部署不包含这项修改；没有改依赖、迁移、生产配置或调用真实目标。

当前工作区新增独立逐条复核后端/API、`/workspace/reviews` 中心及项目内联分配/详情，以及独立全样本评估预览/不可变修订 API 候选，已交付源码的 App head 为 `eval_0013`（独立档案至 `eval_0012`，授权配置导出追加 `eval_0013`）；本轮外部技术隔离接收候选追加 `eval_0014`，本地最终门禁通过，独立提交及精确 SHA CI 仍须单独核验。没有升级历史 `eval_0009` 部署；旧运行收据不能证明本机当前运行状态。两名盲审人及独立仲裁只获具体冻结 case 的授权，共用同一任务服务；评估修订 UI 已有候选；报告/复测已有显式历史来源绑定后端/API 及独立选择 UI 候选，正式批准尚未交付。[合同与范围](DevPilot_Independent_Case_Review.md)。

## 2. 已实现的评测主链

| 环节                  | 当前代码能力                                                                   | 必须保留的边界                                                                                       |
| --------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| 项目与组件            | owner 隔离项目、现有组件关联、不可变提测清单                                   | `inventory_only` 不是可执行 RequestSpec 或批准                                                       |
| QA 与请求版本         | JSON/JSONL 导入、自复核冻结、分离金标读取；完整请求显式加密保存                | 自复核不是独立审批；普通元数据不含金标、请求明文或密文                                               |
| 冻结计划与标准        | 请求/QA 版本、严格 JSON 输入输出映射、预算与 v2 效果阈值冻结并绑定 hash        | v1 hash/历史模板不变；冻结本身不授权执行                                                             |
| 独立执行准入          | 人类单独确认、全局 DB 配额、一次 claim、有界 Worker、逐序号持久派发日志        | operator 默认关闭；未知写入/交付不重发，失联 Worker 不回收配额                                       |
| 执行预留诊断（候选）  | 管理员独立权限下的技术合计 GET、显式只读工作区、严格有界校验与账号隔离         | 观察时间不是心跳、deadline 不是死亡证明；不释放/回收/重试，不推断可用配额或全局策略一致性            |
| 输出与人工复核        | 加密提取输出、按需打开 Q/A/参考/来源、追加人工决策及修订                       | 采集成功不是 PASS；缺少证据不能 PASS；该路径仍是 owner 自复核                                        |
| 独立逐条复核（候选）  | 两名盲审、第三人仲裁；窄授权、租约/回执、追加结论与历史轮次；中心/内联共享服务 | `eval_0010` 任务切片未部署；不接入原汇总/报告，不是正式批准                                          |
| 独立评估修订（候选）  | 全冻结分母、独立决定验真、阻塞与整数阈值；显式不可变评估修订/CAS               | `eval_0011` 未部署；已有独立评估 UI，后续 `eval_0012` 显式历史来源 API，非正式批准                   |
| 独立报告/复测（候选） | 指定历史 assessment ID/修订/hash、独立固定模板、原子报告与同基准比较           | `eval_0012` 未部署；已有独立选择 UI、报告/复测 Word 与 PDF 候选；正式批准未交付，不切换旧 owner 档案 |
| 已验证汇总            | 逐条验证输出与最新人工决策，固定全量冻结样本分母，整数阈值比较                 | 未复核/不确定/技术缺失阻塞；完整或 `met` 都不是批准                                                  |
| 报告草稿              | 不可变多组件汇总、固定模板全文/版本、冻结 Markdown、历史 Word 草稿下载         | 手工/Agent 建议独立且未验证；无正式出具/审批或 PDF                                                   |
| 同基准复测            | 严格相同基准/预算/标准，两版完整复核运行的逐样本变化与不可变存档               | 非自动再执行/通知；当前复核修订不改写历史判断                                                        |

证据入口：[计划](DevPilot_Frozen_QA_Plans.md) · [阈值](DevPilot_Frozen_Effectiveness_Criteria.md) · [执行](DevPilot_Admitted_QA_Execution.md) · [复核](DevPilot_QA_Evidence_Review.md) · [独立复核](DevPilot_Independent_Case_Review.md) · [独立评估](DevPilot_Independent_Assessments.md) · [独立档案](DevPilot_Independent_Report_Retest_Archives.md) · [汇总](DevPilot_Verified_QA_Summaries.md) · [报告](DevPilot_Immutable_QA_Report_Archives.md) · [Word](DevPilot_QA_Word_Draft_Export.md) · [复测](DevPilot_Same_Benchmark_Retesting.md)。

## 3. 可用但不能混为新链路完成的能力

- 旧组件效果/性能原型及定时评测已有入口；并不等于冻结 QA 新链路的独立调度准入、持久队列恢复或正式验收。
- cURL 调试、手工/Agent 报告草稿、管理员模型管理、私有助手可用。配置助手不等于存在已配置模型，也不授予 Agent 人工确认/批准权限。
- 出站共享 DNS-pinned transport 已覆盖调试/手工/旧调度；共享 QA 核心、独立本地命令、软件分发与授权配置导出已有候选。所有遗留适配器及外部结果/输出保护闭环仍未统一交付，不能把软件分发当成平台结果导入。
- Docker 健康信号、只读诊断、账号页面 smoke 证明各自检查范围，不是质量效果、完整数据库验收、长期稳定性或真实目标调用授权。

## 4. 尚未完成与下一阶段门禁

| 优先级 | 工作                                  | 完成前必须证明                                                                                                                                       |
| ------ | ------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| P0     | 当前修复/独立复核候选的 CI 与部署闭环 | 前轮 Linux/前端门禁通过；新增 API→Worker 回归及独立复核后端/共享界面候选，但须按每次推送 SHA 单独核验远端 CI，尚未部署；部署前另备份、保留数据与回退 |
| 维护   | Docker 资源收尾（每轮持续执行）       | 两个旧验证容器及无引用旧镜像已精确退役；每轮测试完停止该轮启动的 CI 容器、精确清临时快照并复查业务健康；保留卷与缓存                                 |
| 维护   | 前端路由资源预算持续防回归            | `6142029` 的原六路由预算已通过且实际 Actions 成功；chat CSS 仅 609 bytes 余量，继续保留全部路由/阈值与真实测量，不冒用前轮结果证明新改动             |
| P1     | 独立档案的正式批准与验收              | 独立复核中心/内联 UI 及全量独立评估 API/修订 UI 已有候选；已有显式历史来源绑定后端/API，已有独立选择 UI；仍须版本化审批，不能把 case pass 当批准     |
| P1     | 失联 Worker 安全运维及 QA 调度准入    | 证明旧进程不再能发送后才考虑运维释放；不按超时盲目回收、不重发未知交付、不借用旧调度绕过准入                                                         |
| P1     | 统一执行适配器与可复现独立导出        | 共用版本化语义、授权/限额/出站边界，导出不泄漏 key/金标且不是模型自由生成 runner                                                                     |
| P2     | QA 治理、CV、流式性能与模型裁判       | 授权数据、跨集防泄漏、真实可观测 TTFT/TPS、显式模型同意与校准；无证据不填零或通过                                                                    |
| P2     | 整改工单/通知与知识闭环               | 明确权限、脱敏与人工晋升；复测档案不是自动整改系统或训练材料                                                                                         |

这些是待交付工作，不因本轮文档校准或测试完成而自动变为“整个项目已完成”。最终验收仍由用户执行。

## 5. 工程验证与运维记录

前一轮修复后 Docker 后端完整回归 **12,118 passed / 18 skipped / 11 deselected**；纯领域 evaluation 15、toolkit 58 分别通过，Ruff check/format 通过（1,220 文件）。前端 format、ESLint/TypeScript、生产构建通过，140 文件 / 1,094 单测、201 常规浏览器测试及 2 独立认证恢复测试分别通过。schema + Node 探针独立补测 26 passed，不能与完整套件相加。

前一轮 Docker 收尾已完成：退役 2 个过期验证容器和对应 2 个无引用旧镜像，停止 4 个 CI 容器，保留依赖缓存/所有数据卷/其他项目；最后业务服务全部 healthy。本轮没有升级生产、提交或推送，后续仍需独立 CI、保留数据部署与用户验收。

### 后续开发轮次：API → 实际 Worker 合成回归（2026-11-09）

新增 `backend/tests/test_qa_workflow_api.py`，**8 项定向通过**：API 创建三样本 QA、两个请求版本及冻结 v2 计划，接入实际 Worker/持久派发/加密证据/人工复核/汇总/报告与 Word/同基准复测。覆盖并发 1/2、发送前提交日志、旧版请求绑定、六类技术失败与未知交付不重发、全量分母/整数阈值、后续复核不改写历史档案和读取权限。

- 这是临时已迁移 SQLite、合成认证/数据/key、DNS/HTTP wire 替身与真实 socket 禁止的离线回归；不是部署 GUI、真实认证/目标效果验收，也不补足独立审批。没有新增生产能力、依赖或迁移。
- 隔离环境修复后，完整变更前 **12,117 passed / 19 skipped / 11 deselected / 40 warnings**；变更后完整回归 **12,125 passed / 19 skipped / 11 deselected / 40 warnings**（430.43s）通过。两组纯领域 **15 / 58** 分别通过；Ruff check/format **1,221 文件**通过。历史与本轮计数独立，跳过不算通过，不能拼接定向与全量。
- 未修改前端源码；前一轮前端全量证据未重跑。当前运行部署不变，尚无本工作区独立远端 CI 或保留数据部署证据。本轮三个本次启动的 CI 容器已停止，Node CI 保持停止；Docker/宿主临时快照、独立 venv、Node 与源码 tar 已精确清理，缓存/卷/其他项目保留，最后四个业务服务 healthy、诊断 ok。无新增镜像清理或业务升级，详见运维记录。

本轮实际运行及失败原因追加在[隔离环境记录](DevPilot_CI修复与隔离开发环境.md)，Docker 资源处理追加在[诊断与维护](DevPilot_Docker_Diagnostics.md)。不得把多个有重叠的测试组相加为完整套件；也不得用镜像显示大小推算实际宿主释放空间或 RAM。

### 后续只读资源复查（2026-11-09 02:14）

四个业务服务 healthy、restart=0、OOM=false，四个 CI 容器均 exited；没有无引用的 DevPilot 标签镜像。显式 dangling 复查发现一项仍被其他项目停止容器引用的镜像，予以保留；构建缓存未验证归属，不清理。本轮未启动/停止/删除资源、未构建或部署，零删除不重复计数为前轮清理。仅更新资源收据与维护约束，没有运行代码变更或测试重跑；上述全量测试仍属于此前工作区证据。

English: the bounded QA path now includes immutable plans/criteria, admitted collection, encrypted evidence, human review, verified summaries, draft archives and same-benchmark retests. Formal independent approval, safe lost-worker operations, new-path scheduling, unified runnable exports and advanced evaluation/governance are still incomplete. Code, deployment, test results and user acceptance are separate claims.

### 历史后端切片：独立逐条复核后端/API（2026-11-09，后续 UI 另列）

两个不同盲审人、第三名不同仲裁人及 owner 分离；明确分享一个冻结 case，不开放项目成员/普通数据权限。领取/释放、30 分钟租约、已看版本回执、原子追加决定/结论/审计、撤销及不覆盖历史的重开已实现。缺输出/技术失败不能 PASS。候选 `eval_0010` 仅追加五表两索引，部署仍为 `eval_0009`；**UI、assessment/汇总/报告接入及正式批准仍未完成**。[服务合同与隐私](DevPilot_Independent_Case_Review.md)。

最终完整变更后复验 **12,191 passed / 19 skipped / 11 deselected / 40 warnings，471.47s**；纯领域 evaluation/toolkit 分别 **15 / 58 passed**。Ruff 全量 check/format **1,227 文件**通过。定向 67、迁移关联复验 24 与完整套件有重叠，不相加；skipped/deselected 不算通过。 变更前首次正确隔离全量发生 1 项 Worker finish 派发回归失败，根因未确认；同文件和完整基线随后通过，原失败保留。第一次变更后完整回归暴露旧库测试错误枚举未来表，修正测试旧表清单后重跑全量，未跳过或削弱数据保留断言。完整历史见[隔离记录](DevPilot_CI修复与隔离开发环境.md)。

本轮没有前端源码/页面交付、远端 CI、提交、推送、生产升级或真实模型/目标调用，不将后端测试通过等同用户验收或整个平台完成。Docker 收尾另按[维护记录](DevPilot_Docker_Diagnostics.md)保存精确资源收据。

本轮资源收尾已核验：三个本次启动的 CI 容器停止、Node 未启动；独占 Docker 快照/venv/Node/辅助文件清理且共享缓存哈希不变；其他容器与镜像未变。无安全可删的过期 DevPilot 镜像，本轮零镜像删除。四业务服务 healthy、诊断 ok；所有失败/通过日志与收据保留，未启用后台自动删除。最终契约 91 项与全量重叠，不相加。

### 后续开发轮次：共享独立复核中心与内联 UI（2026-11-09）

`/workspace/reviews` 与项目 case 的明确分配入口复用同一任务服务；租约、已看版本、双盲/仲裁、owner 历史轮次、unknown write 同 ID 核对及跨项目页内待办 ID 保留已实现。候选 `eval_0010` 不新增其他迁移，尚未部署；assessment/汇总/报告接入及正式批准仍未完成。[当前范围与验证](DevPilot_Independent_Case_Review.md)。

全量前端单测 **1,125 passed / 144 文件**，生产构建通过；完整模拟浏览器 **206 passed**，登录/设置恢复 **2 passed**，均零自动重试。四文件 31 项与浏览器定向 5 项已经包含在对应全量中，不重复计数。最初测试工具/快照错误及移动端溢出失败已留存，修复后按原门禁重跑。没有真实多账号/后端连接 UI 验收、模型/目标调用、提交、推送或部署；本轮不冒称重新跑过后端全量。最终完整 frontend Prettier（含前端指南）、lint/typecheck 及 1,125 项单测再次通过；833 份隔离快照文件与宿主清单逐项 SHA-256 核对无差异。最终资源收尾及其后的纯文档追加另记录，不能据此声称重新运行后端或完成真实验收。

本 UI 轮资源收尾已完成：37 份日志/收据已导出并逐项校验；独占 Docker 快照、辅助文件及宿主 staging 精确清理，五个明确的共享缓存标识哈希未变。仅停止本轮 Node CI，其他三个 CI 保持停止；全部其他 13 容器及镜像引用清单未变。无可删的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除。最终业务四服务 healthy、诊断 ok；未改配置、迁移生产或启用模型/目标。详见[维护记录](DevPilot_Docker_Diagnostics.md)。这段是全量测试后的纯文档追加，不代表再次运行完整套件或候选已经部署。

### 后续开发轮次：全样本独立评估与不可变修订（2026-11-09）

候选 `eval_0011` 新增独立评估预览和显式追加的评估修订 API：全部冻结效果样本参与分母，全部当前轮次任务验真，不读取 owner 自复核决定；缺证据、待处理、撤销、分歧及技术失败阻塞完整性。整数阈值、off-loop 验真/锁内整快照复查、revision CAS、事务审计与不可变历史已实现。允许 provisional 归档，但一律非正式批准，不切换旧汇总/报告/复测。[合同](DevPilot_Independent_Assessments.md)。

最终 Docker 后端完整回归 **12,231 passed / 19 skipped / 11 deselected / 40 warnings，489.52s**；变更前基线 12,191 passed。纯领域 **15 / 58 passed**、Ruff check 与 format **1,232 文件**通过；104 项定向与完整套件重叠，不相加。2,472 份公开源码与测试快照逐项 SHA-256 一致。早期 fixture/迁移测试失败与修正完整留档，历史 Worker 偶发失败根因未确认。本轮没有前端源码变更或前端门禁重跑；资源收尾后的修改仅为文档和 ignored 证据。

本轮三个 CI 已停止，Node 保持停止；独占 Docker 快照/辅助文件、已导出并验真的证据副本和宿主 staging 精确收尾，共享缓存/全部卷保留。全部 14 容器最终 ID/镜像/状态/restart/OOM 与测试前一致，镜像清单不变；无可安全删除的过期 DevPilot 镜像，镜像/容器/卷零删除。业务四服务 healthy、诊断 ok。停止输出断言失败经独立只读检查确认最终状态，未重复破坏性操作；原记录保留。[资源边界](DevPilot_Docker_Diagnostics.md)。

当前候选未提交/推送/远端 CI/部署，运行 head 仍为 `eval_0009`；评估 UI、报告/复测显式绑定与正式批准待开发，真实多账号联调与最终用户验收仍待进行。测试通过不等于整个平台完成。

### 后续开发轮次：独立全样本评估 UI（2026-11-09）

`IndependentAssessmentPanel` 已接入项目工作区，独立于旧 owner 汇总：明确加载预览/历史、严格全量 DTO、provisional 非批准归档、hash + revision CAS、页内唯一待办 ID、未知写入同 ID GET-only、跨范围迟到响应隔离及固定历史打开。无报告/复测来源切换、正式审批、新迁移或依赖。[界面合同](DevPilot_Independent_Assessments.md#8-独立评估工作区-ui2026-11-09)。

完整 frontend Prettier、lint/typecheck、生产构建通过；**1,152 单测 / 146 文件、210 完整模拟浏览器、2 登录恢复**均通过，浏览器零自动重试。定向 27 / 4 项与全量重叠；本轮后端未重跑，早期开发/环境错误完整留档。不等于真实多账号联调、远端 CI、部署或用户验收；候选 `eval_0011` 未部署，独立报告/复测绑定与正式批准仍未交付。

本 UI 轮资源收尾已独立核验：30 份 Docker 日志/JSON 先导出并逐项验 SHA-256，834 份公开源码/测试/指南与测试快照一致；随后仅删除本轮独占快照、12 个辅助文件及已备份证据副本，宿主 staging 亦精确删除。仅停止本轮 Node CI，其余三个 CI 始终停止；最终全部 14 容器的 ID/镜像/运行或停止/restart/OOM 签名恢复测试前状态、9 行镜像标签清单不变。无可安全删除的无引用 DevPilot 镜像，本轮镜像/容器/卷零删除；业务四服务 healthy，诊断 ok。五个明确 Node 缓存标识哈希未变，不声称整个缓存树已审计。资源收尾后的追加仅为文档，不代表重跑完整套件或已部署。

### 当前开发中工作与 Docker 收尾（2026-11-09 06:51）

独立评估修订显式绑定报告/同基准复测已开始 TDD 和仓库扩展，但仍是 **WIP，不可作为已交付 API 使用**：新模块依赖的独立表、追加迁移及路由尚未完成，定向绿灯和变更后全量也未完成。没有新增 `eval_0012` 迁移，候选迁移 head 仍为 `eval_0011`，部署仍为 `eval_0009`。不回滚或删除工作区中的既有和开发中修改。

本次接手后确认基线测试自然结束：**12,224 passed / 37 skipped / 40 warnings，537.19s**，完整日志保留；这是变更前基线，不能覆盖之后两个报告/复测仓库文件的改动及新增未完成模块/测试，也不替代此前 UI 的验证或真实多账号验收。新模块缺失时的预期导入红灯亦保留，尚无本轮实现后通过结果。

本轮资源已独立核验收尾：四份日志/JSON 先导出验 hash，再清理本轮独占 Docker 快照/临时文件/已归档结果副本及宿主 staging；三个共享 editable 和 51 个 launcher 明确哈希不变。本轮启动的三个 CI 均已停止，Node 始终停止；14 容器最终签名及镜像清单恢复开始状态。无安全可删的闲置 DevPilot 镜像，唯一无标签镜像仍有容器引用；镜像/容器/卷零删除。业务四服务 healthy、诊断 ok，数据/配置/共享缓存与其他项目保留。[操作与证据边界](DevPilot_Docker_Diagnostics.md)。

下一开发门禁仍是完成独立历史评估来源的严格表/API/原子存档与回归，再推进显式 UI、正式批准、真实多账号联调、独立 CI 及保留数据的备份升级；并非整个项目已经完成。

### 2026-11-09：独立历史评估绑定报告/复测的后端门禁

本轮已实现独立命名空间的历史评估修订绑定后端/API，候选 App head 为 `eval_0012`，未部署，现有运行 head 仍为 `eval_0009`。来源显式固定 assessment ID / 修订 / hash，不追随任务重开或最新意见；保留 ALL 冻结样本分母、严格同基准/预算/标准、历史不可变及 `not_approved`。独立选择 UI、独立 Word/PDF、正式批准和真实多账号联调仍未交付。

- Docker Python 3.12 变更后完整离线回归：**12,284 passed / 26 skipped / 11 deselected / 40 warnings，593.12s**，exit=0。未运行项不计为通过；此前 12,224 项仅是变更前基线。
- 最终定向 **104 passed，86.21s**，覆盖新服务/API/SQLite 与独占 PostgreSQL 迁移、既有 owner 档案兼容；包含于全量，不与全量相加。两组纯领域测试另为 **15 / 58**，分别通过。Ruff 全目录 check 与 format **1,237 文件**通过。
- 整个 frontend Prettier 及本轮 root/backend/文档指南检查通过；没有前端运行源码改动，也没有重跑前端单测、浏览器或构建。此前前端证据保留为各自历史切片，不冒称本轮新结果。
- 运行/测试源码已逐项 SHA-256 核对，与实际回归快照一致；文档在回归后单独格式检查/同步。早期字段/严格类型/事件循环/迁移测试失败及后续修正日志均保留，不弱化断言或丢弃失败。

此结果属于未提交工作区的隔离后端候选，不是远端 CI、生产数据迁移、保留数据升级、真实模型/目标效果或用户最终验收。未知写入仍只能同 ID GET 对账，不能自动重发。合同见[独立档案范围](DevPilot_Independent_Report_Retest_Archives.md)，资源收尾另记在[Docker 运维](DevPilot_Docker_Diagnostics.md)。

本轮资源收尾已于 **2026-11-09 07:45（Asia/Shanghai）** 独立核验：19 份日志/JSON 导出并验 hash，2,484 份最终公开文件与快照一致后，精确清理本轮独占快照/四个辅助文件/已归档副本及宿主 staging；共享缓存和所有卷保留，三个本轮启动的 CI 已停止、Node 始终停止。全 14 容器的 ID/名称/镜像/状态/restart/OOM 签名恢复测试前状态，9 行镜像标签清单未变；无可安全删除的闲置 DevPilot 镜像，被引用的无标签镜像保留，镜像/容器/卷零删除。业务四服务 healthy、诊断 ok；不声称宿主 RAM 即时全部归还或 VHDX 已缩小。此后仅文档/ignored 证据更新，不算新一轮完整回归或部署。

### 2026-11-09：独立历史报告与复测选择 UI 门禁

Reports/Retests 新增独立区块：明确打开历史 assessment ID/修订/hash，complete 来源单独加入报告或 baseline/retest；不默认最新，不替换 owner 档案。同步页内待办 ID、写锁、迟到响应隔离及同 ID GET-only 对账涵盖未知写入与 404；固定历史纯文本、Markdown/JSON 下载，独立 Word/PDF 与正式批准仍未交付。

- 最终全量前端单测：**1,164 passed / 148 文件**。
- 生产构建、lint/typecheck 通过；完整模拟浏览器 **214 passed**，登录恢复 **2 passed**，均零自动重试。归档定向 12 / 4 项已包含在全量内，不叠加。
- 手机长按钮溢出修复后重新构建并全量复验；保留失败及通过日志。旧报告 capability GET 不等于 advisor POST，后者仍被禁止。
- 本轮后端未重跑；1,267 份 backend 非 Markdown 文件与前轮 12,284 passed 的源码 manifest 相同。候选 `eval_0012` 未部署；模拟浏览器不等于真实多账号/后端联调或最终验收。
- 按用户要求，完成模块并通过测试后提交/推送，按精确 SHA 核对 Actions；若仍运行，下一模块推送前先检查上轮并修复归因失败。成功推送不等于 CI 成功，不自动部署。

本轮 UI 资源收尾已于 **2026-11-09 08:50（Asia/Shanghai）** 独立核验：840 份公共源码/指南与快照逐项一致，34 份日志/JSON/artifact 先导出并验 hash，再精确清理本轮快照、八份临时辅助文件、结果副本及宿主 staging。只停止本轮启动的 Node CI，另三个 CI 全程停止；14 容器签名及9行镜像标签清单恢复原状，业务四服务 healthy、诊断 ok。共享缓存/卷/其他项目保留；镜像、容器、卷零删除，无安全可删的无引用 DevPilot 镜像。详情见[运维收据](DevPilot_Docker_Diagnostics.md)。收尾后仅文档更新和格式核验，不冒称重跑完整套件或已部署。

本模块本地最终门禁：新增 37 项；联合 443 / 后端全量 12,647 / 领域 15、58 / Blocking IO 72 / 前端 1,293 passed，Ruff 1,255 files、离线锁与完整格式通过。188 个实际旧/新传输对照和真实 wheel 隔离 mock-send 验证通过；源码/证据 hash、精确资源收尾和新 SHA 的 Actions 分别核验，不借用上一提交，也不宣称独立执行/导出或平台完成。

## 共享有界单次采集候选（2026-11-10）

共享 pinned HTTP 模块 `3b193d69007c097a71aad16135617775f09a6949` 的四项精确 SHA push Actions 均 completed/success：Unit `42743465228`、Frontend Unit `42743465248`、Blocking IO `42743465295`、Lint `42743465225`；源码/证据与四个专用资源收尾已核验。

接续[完整单次采集核心](DevPilot_Shared_QA_JSON_Attempt_Core.md)，共享现有 deadline/流生命周期/分类/观测与关闭，App 保留动态 client 政策、准入、耐久派发及预算。先前隔离审批超时/502 的两次命令未执行；后续经单独只读核验与显式启动审批恢复验证。已完成联合、全量后端/领域/前端和实际旧新对照/wheel 门禁；最终资源/提交/精确 SHA CI 另行核验，未借用上轮结果。不提前开放独立 runner/export；正式批准、lost-Worker 安全对账、冻结 QA 调度及授权升级仍未完成。

本模块本地最终门禁：新增 **44 passed**；联合 **487 passed**；后端全量 **12,691 passed / 18 skipped / 11 deselected / 40 warnings**；领域 **15 / 58 passed**；Blocking IO **72 passed**；后端 Ruff **1,256 files**、共享核心 lint/format 与离线锁通过；前端 **152 files / 1,293 passed**、完整 Prettier 和八份模块文档格式通过。399 个旧/新实际行为对照及实际 wheel 的隔离 mock-send 通过。最终源码/提交归档、证据 hash、精确资源收尾及新 SHA Actions 独立核验；本轮没有重跑本地前端 build/浏览器/性能，不借用历史结果，不部署/启用执行或调用真实模型/目标。

## 本地 QA 只读对账候选（2026-11-10）

前序本地命令已推送 `bdd3ba10b47f6473c59109f04736df7535f154de`；实际四项 push Actions 全部 completed/success：Unit `42776213688`、Frontend `42776213624`、Blocking `42776214029`、Lint `42776213627`，独立核对原 SHA，专用容器已停止。

新增[只读原 ID 对账命令](DevPilot_Local_QA_Reconciliation.md)，真实复用 journal snapshot，不读取敏感输出或更改 owner claim。全冻结分母、技术分类/预算一致性、hard-exit WAL 和实际 CLI → 对账链作为门禁。仍为 external/unverified / NOT_EVALUATED；不是输出完整性/平台 provenance、retry/resume/重发、平台导入或批准。无 App/API/依赖/迁移/部署/执行启用或真实调用。新 SHA 的 Actions/资源收尾另行核验，整个平台未完成。

本模块最终本地门禁：新增 **64 passed**（4.00s），联合 **786 passed**（157.99s）；标准 `make test` **12,982 passed / 18 skipped / 11 deselected / 40 warnings**（756.47s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.60s）；Ruff **1,260 files**、新领域模块独立 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（13.0s），完整 Prettier 与八份模块文档格式核验。真实 sdist→wheel 十三个公开成员逐 bytes 相等，隔离 `-I` 实际 wheel 的执行 CLI mock sends → 对账 CLI 成功，并显式确认模块 import origin 位于 wheel；真实 DNS/socket 和业务层 imports 禁止。源码/证据/专用资源与新 SHA 实际 Actions 独立闭环。未本地重跑 frontend build/browser/performance；无部署/执行启用/真实调用。
