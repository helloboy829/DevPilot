# 第 90 次提交之后的代码审查

审查日期：2026-11-15。结论绑定 `5671f50e2a5912c3cb9d95256c93abfa5e81216d`，不代表运行环境、部署或远端 CI 验收。

## 结论

后续代码存在实际缺陷，审批前端尤其需要先收敛状态管理，再继续加功能。本轮确认 7 项问题，其中 4 项通过真实 React 组件的合成 DOM 测试复现，3 项通过抽取原始方法/路由体的最小探针验证。后端集成环境未就绪，因此后 3 项仍需在 Python 3.12 锁定环境补 HTTP/数据库回归。

不能据此断言“第 90 次后所有代码质量都下降”：依赖方向、共享 runner、离线默认和授权边界整体仍保留；指标纯核心的专项测试也通过。更明确的退化是：跨层协议未统一、前端状态处理反复局部修补、mock 测试没有覆盖关键组合，以及验收主线之外持续增加小功能。

## 范围与方法

- 当前主线从初始提交正序计数共 179 次，第 90 次为 `ce6ca15f97c410252100dea4c00a8949ed826a40`。审查区间为该提交之后的 89 次；若用户所指是另一种编号，应重新映射基线。
- 区间改动 92 个文件，增加 7,460 行、删除 169 行；提交类型为 feat 29、fix 10、test 13、docs 35、ci 1、chore 1。这是提交分类，不是质量评分。
- 对照根/前后端指南、交付状态、系统架构、正式批准合同和冲刺计划；审查全部生产代码差异，重点追踪审批、诊断、离线指标与 CLI。
- 本轮没有修改生产代码、提交或推送，没有部署、启动业务服务、访问业务数据库或调用真实模型/目标。

## 具体缺陷，按修复优先级排序

### 1. [P1] 未知审批写入后仍可再次 POST，违反只读对账合同

位置：`frontend/src/components/workspace/evaluation-approval-panel.tsx:337`、`:350`、`:778`。

`record()` 仅检查输入/确认和瞬时锁，没有拒绝已存在的 pending ID；提交按钮也没有 pending 条件。首次 POST 失败且列表没有找到该 ID 后，再次勾选确认、点击记录，会用同一个 ID 发出第二次 POST。若第一次没有提交，第二次就能产生新写入；若用户修改了决定/备注，原 ID 还可能对应不同载荷。

复现结果：期望 `create` 调用 1 次，实际 2 次。现有测试只检查首次失败后没有立即自动重试，没有执行下一次用户点击。

建议：pending 状态成为明确的只读状态；后续操作只调用原 ID 的 GET。不能仅靠复用 ID 代替“禁止重试”。现有 GET 单个批准端点可复用，列表最多 100 条，不适合作为精确对账的唯一入口。

引入：`c37e0af`；后续 `509834b` 等修补没有关闭该路径。

### 2. [P1] 切换 run 会使审批面板永久 busy

位置：`frontend/src/components/workspace/evaluation-approval-panel.tsx:84`、`:129`、`:165`。

请求开始时设置 `busy=true`；run/project 改变使 epoch 递增，但重置 effect 不清理 busy。旧请求结束时因为 epoch 不相等，finally 又跳过 `setBusy(false)`。输入/select 在 busy 时仍可编辑，因此正常用户操作即可触发；所有加载/记录按钮随后持续禁用。

复现：开始加载运行批准，立即把 run 改为另一合法 ID，再完成原请求。加载按钮仍为 disabled。

建议：按作用域拥有请求状态和取消控制；切换目标时释放旧读请求的 busy，写请求锁单独保留。简单删除 epoch 判断会引入旧响应覆盖，不能这样修复。

引入：`c37e0af`；跨目标清理在 `ffc1a9f` 后仍不完整。

### 3. [P1] 使用列表长度作为最新修订号，阻止正常批准/撤销

位置：`frontend/src/components/workspace/evaluation-approval-panel.tsx:357`；对应后端 `backend/app/evaluation/qa_approvals.py:184` 的列表上限 100。

写入的 `expected_previous_revision` 为 `runRows?.length ?? 0`。后端返回最新 100 条，支持最多 1000 个修订；当最新修订为 125 时前端提交 100，必然冲突。未加载运行列表时，即使预检返回最新 revision，也仍提交 0。同一面板从第 100 条开始继续追加一段时间可能暂时可用，但重新加载后即失效。

复现：返回 revision 125..26 的 100 条列表，实际 POST 的前置 revision 为 100，期望 125。

建议：独立保存服务端最新 revision，或从已验证列表取最高 revision；没有观察过当前 revision 时不允许写。不要从条数推导版本。

引入：`c37e0af`。

### 4. [P2] 修改审批人后，迟到的旧预检结果重新显示“可批准”

位置：`frontend/src/components/workspace/evaluation-approval-panel.tsx:313`、`:324`、`:708`；评估 ID/hash 编辑和拟议签核人数也有类似请求失效问题。

编辑输入虽然清空 `preflight`、撤销确认，却没有让正在进行的预检失效。旧请求返回时 epoch 未变化，仍写回旧结果，界面将旧审批人的资格展示在新审批人旁。后端仍会重新校验，因此本项不证明可以绕过后端批准条件，但会误导用户。

复现：请求审批人 A 的预检，在返回前改为 B，随后 A 的 eligible=true 返回，面板重新显示 Eligible。

建议：响应绑定 project/run/assessment ID/hash/approver 的完整请求键；输入修改时取消或使其失效。对输入已改、请求未返回的情况补测试，不能只测结果已显示后再编辑。

相关修复：`ffc1a9f`、`0420ef9` 只完成了部分清理。

### 5. [P2] 最新“并发冲突转 409”修复分支实际无法捕获目标异常

位置：`backend/app/evaluation/qa_approvals.py:397`；`backend/app/evaluation/dispatch_journal.py:89`。

`set_signoff_policy()` 在 `_transaction()` 外捕获 `IntegrityError`。继承的 `_transaction()` 已先捕获所有 `DBAPIError` 并转换为 `JournalWriteUnconfirmed`；SQLAlchemy 的 `IntegrityError` 继承自 `DatabaseError → DBAPIError`。因此插入重复 revision 时，外部 except 分支收不到 `IntegrityError`，路由将返回 503，达不到提交声称的 409。

最小探针保留原方法和事务包装器，注入具有相同继承关系的合成插入异常：实际为 `JournalWriteUnconfirmed`，并非 `Conflict`。这不是数据库并发集成验收。

建议：在错误被通用事务层转换之前处理已明确回滚的唯一约束冲突；其他数据库/提交不确定异常继续保持 unknown。增加两个调用者竞争同一 revision 的真实 DB 回归。

引入功能：`4b184e0`；无效修复：当前 HEAD `5671f50`，该提交没有新增回归测试。

### 6. [P2] 11 名合法审批人导致签核查询 422

位置：`devpilot/src/devpilot/qa_signoff_policy.py:30`；`backend/app/evaluation/qa_approvals.py:328`；`backend/app/gateway/routers/evaluation_projects.py:631`。

核心将“要求人数上限 10”同时用于“已观测批准人数上限 10”。但批准仓库没有限制不同审批人的总数，一个 run 可以有 11 名不同审批人的合法批准。此时即使只要求 2 人，签核进度调用核心也会 ValueError，路由映射为 422。保存项目政策后，不带参数的查询同样可能触发。

最小探针：11 条不同审批人 approved 记录聚合为 11；调用 `required=2` 得到 ValueError。真实 DB/HTTP 仍须补回归。

建议：将 policy 上限与 observation 上限分离，后者与仓库可生成的最大合法计数对齐；不得截断实际计数。

引入：`15677b8` + `c684588`；`4b184e0` 扩大了自动附加 requirement 的场景。

### 7. [P2] 创建审批新增的归属检查漏过 HTTP 错误转换

位置：`backend/app/gateway/routers/evaluation_projects.py:675`。

新增账号查询前的 `_project()` 直接 await，没有通过 `_result()`。对未知项目/他人项目，仓库抛出 `NotFound`；路由包装器只捕获存储保护/SQL/unknown 写入异常，没有捕获该异常，也未发现全局 NotFound handler，因此会成为未处理异常/500，而不是合同要求的 404。当前跨 owner 测试覆盖 GET，没有覆盖 POST 新增的检查路径。

原路由体的最小探针确认 `NotFound` 直接逃逸；本轮未做真实 ASGI HTTP 集成。

建议：通过既有 `_result()` 转换，补未知项目/跨 owner POST 404 和账号查询未执行的断言。

引入：`8bb0bed`。

## 架构与整体方向

### 后续修复状态（截至 `6e7c5080e5a3626bb1bab166a5dbf254470c6eb4`）

原报告的七项可复现问题已在后续提交中处理：审批写入 pending ID 只读对账及目标状态隔离、列表上限下的 revision 来源、异步预检失效、签核策略并发冲突映射、观测人数上界、审批账号存在性及项目归属错误映射。主要修复集中在 `a5c6958`，包括在通用事务错误转换之前捕获策略插入冲突；`5671f50` 是原报告确认无效的外层捕获尝试。相关专项验证包括当前源码审批/安全/预检 **115 passed**、sign-off 与 metrics domain **22 passed**、Blocking IO **72 passed**、Local QA CLI **83 passed**，以及失败簇重跑 **454 passed**。

截至该 SHA 的失败簇验证不能替代完整套件或精确 SHA CI；后续有效全量结果见下方续查。架构结论仍是：依赖方向和共享 QA 核心边界保持，主要偏差在交付优先级和面板状态复杂度；签核人数仍是咨询性历史聚合，尚未定义为撤销后的有效签名集合，不得用于授权或强制判断。

### 2026-11-16 续查：两个额外缺陷

1. **对账成功仍显示写入前状态。** 显式原 ID 元数据对账清除 pending 后，旧预检、确认勾选与项目索引仍保留。`e7e9998` 已清除这些状态，真实 DOM 新回归先失败后通过，浏览器合成流程保持仅一次 POST；前端完整 **1,436 passed**，九项 Chromium 回归通过，该 SHA 前端/Lint/Replay/E2E Actions 成功。
2. **咨询政策表重复唯一声明导致 PostgreSQL schema drift。** `4b184e0` 在 `eval_0016`/元数据中同时声明 `(project_id, revision)` 主键及相同 UNIQUE。`cab5346` 的 CI 失败摘要定位三项 PostgreSQL parity 用例；在独占 PostgreSQL 17 中复现均为同一 `add_constraint` 差异。修复只移除重复 UNIQUE，主键和人数/revision check 保持。相关 PostgreSQL/SQLite、历史保留与恢复矩阵 **17 passed**。最终标准 `make test` 在冻结环境下得到领域 **64 + 58 passed**、后端 **13,580 passed / 63 skipped / 11 deselected**（1045.06s，exit 0），三项 PostgreSQL 原失败及新增数据库约束回归均通过；Blocking IO **72 passed**，Ruff **1,296 文件**通过。修复 SHA CI 仍须独立核验，Linux 不替代 Windows 或真实用户验收。

首轮 Windows 只读源码挂载全量保留 **4 failed / 13,561 passed / 77 skipped / 11 deselected**：缺少 `uv` 的配置升级和三个本地 QA 子进程场景。后者在 Linux 文件系统公开源码中联合六项参数化场景通过；可写冻结 venv 与独占 PostgreSQL 环境另行验证，不把原失败改写为通过。

### 保持住的边界

- 此区间没有修改 Harness 生产代码；扫描没有发现新增 `Harness → app` 或 `devpilot → app` 依赖。
- 新的指标逻辑位于纯 devpilot，App 通过正向依赖调用；没有新增第二套 QA 执行 runner。
- SQLAlchemy 表/迁移仍归 App；审批固定 assessment revision/hash，批准/撤销追加保存；技术指标没有自动提升为 PASS/批准。
- 执行诊断与调度准入仍只读，不因 deadline 释放占用或重发未知请求。保留这些限制符合现有合同。

### 已出现的设计债务

1. **审批面板形成状态集中点。** 单文件 791 行，约 20 组 state，9 类异步操作共用 busy/epoch；每增加一种读取都复制 catch/finally 与失效规则。后续多次修复 stale/pending/consent，仍能复现上述组合缺陷。应拆分请求状态、写入状态和目标绑定逻辑，优先提取 reducer/hook/纯策略，而不是只按 JSX 外观拆组件。
2. **跨层协议没有唯一可执行来源。** 前端将 metadata list 声明为完整 `ApprovalView[]`，实际列表不含 assessment 嵌套、counts、note 等字段；DOM fixtures 却大量使用完整批准文档。不同核心还存在 100 列表上限、1000 修订、10 观测人数的冲突。这些不是类型检查可以发现的，需要准确的列表 DTO、schema/合同测试和边界计数用例。
3. **签核聚合还不是当前有效签名模型。** `distinct_approved_approvers` 统计整个 run 历史上曾 approved 的人，未按具体 assessment 版本或撤销后的有效签名计算。现有合同明确它只是 advisory，所以本报告不把它判为违反已交付合同；但将其升级为强制签核前必须重新定义目标、撤销和签名有效性，不能直接将现有 `satisfied` 用作授权条件。
4. **审批规则已进入路由编排。** 账号可用性在 router，assessment/separation 在仓库，咨询 requirement 在 devpilot；内部仓库调用不会自动获得路由中的账号规则。当前合同允许 owner-scoped 路由暴露，但未来 CLI/Worker/其他入口容易遗漏，应由明确的 App 服务统一业务前提。
5. **完整性计算的 event-loop 预算需要补验。** 新项目链校验对最多 5000 条批准执行同步 JSON fingerprint；已有单条读取和批准目标验证使用 `asyncio.to_thread`。没有本轮负载测量，暂不单列性能 bug；建议在拆服务时统一 off-loop 验证并补 Blocking IO/响应预算证据。

### 方向偏移的判断

`docs/DevPilot_Sprint_Plan.md` 已明确：优先形成可重复候选环境、迁移/恢复与真实用户验收；继续增加 CV/模型裁判入口的收益较低。后续却新增流式/裁判/CV 核心及 CLI、签核进度/政策、多个固定诊断入口，而当前状态仍说明未部署、浏览器/用户验收未完成。

这些小模块大多在目标架构允许的范围内，但不能替代主链验收。固定返回“尚未实现”的 capabilities/scheduling 诊断有解释价值，本身没有交付登录、强制签核或安全调度。这一阶段更明显的是**交付优先级偏移与功能面扩张**，尚不足以认定底层架构被彻底推翻。当前源码与运行版本的距离也不是第 90 次后才出现的问题。

文档更新有投入，但也存在互相矛盾：状态页最近记录已有 stored advisory policy，后面的优先级表还说“多级签核仅纯要求核心且未接入”；签核核心文档仍声称 App 不保存政策。不要用新增历史收据替代当前能力矩阵的同步。

## 验证事实与限制

- 真实前端组件与相关 API/诊断既有测试共 **104 项通过**。临时新增 4 个期望行为回归最终 **4 项均失败**，对应问题 1–4；第一次联合运行其中旧预检断言匹配过窄，修正匹配后复现，不涉及生产修改。
- 后端最小探针 **3 项**，对应问题 5–7。探针从当前源码 AST 抽取原始方法/路由体，使用合成 session/query/异常；证明方法控制流，不证明完整数据库、HTTP 或 Python 3.12 运行环境。
- 离线指标现有专项 **39 passed / 1 skipped**，使用宿主 Python 3.9，仅作辅助观察。Windows 的 symlink 用例跳过，不能声称已验证；加入 retention 后因 Python 3.9 不支持 `dataclass(slots=True)` 收集失败，没有将其归为产品 bug。
- 后端集成试跑未执行测试：宿主 Python 3.9 缺少 pytest_asyncio/alembic，现有 backend/.venv 是 Linux Python 3.12，无法直接用于 Windows；未安装依赖或修改锁文件。
- 前端测试 Worker 在沙箱内 `spawn EPERM`；获准在沙箱外运行本地离线测试后完成上述实际组件验证。最初命令误用 vitest/`--run` 已纠正为仓库 Rstest，经根脚本执行；该命令错误不作为项目缺陷。
- 没有重新查询远端 Actions；文档中的 CI 是历史证据，不作为当前 HEAD 成功证明。没有进行完整后端、生产构建、浏览器或真实用户验收。

## 修复顺序

1. 先关闭问题 1–4：pending 只读、请求生命周期、revision CAS、完整目标 fence；保留实际组件回归。
2. 在 Python 3.12 锁定环境补问题 5–7 的真实数据库/HTTP 失败回归，再最小修复。
3. 准确区分 ApprovalListItem 与 ApprovalDocument DTO，覆盖 0/1/100/101/1000 修订及 10/11 人等边界；将一次性的 mock 断言补成状态序列测试。
4. 收敛审批服务和面板状态后，冻结一个候选 SHA，完成环境、迁移、主链与用户验收；其间暂缓增加新的低优先级入口。

## 复现材料

同目录 `approval-review-audit.dom.test.tsx` 保留 4 个失败用例，置于 docs 以免进入日常测试发现范围。复现时复制到 `frontend/tests/unit/components/workspace/approval-review-audit.dom.test.tsx`，在仓库根运行：

```powershell
python scripts/pnpm.py test run tests/unit/components/workspace/approval-review-audit.dom.test.tsx
```

测试只 mock API，运行真实 React 组件；预期在被审查 SHA 上出现 4 个失败。验证后移走临时副本。

后端控制流探针：

```powershell
python docs/reviews/2026-11-15-post90/source_probe.py
```

输出分别为 `JournalWriteUnconfirmed`、11 人计数 `ValueError`、归属检查未处理 `NotFound`。不要将此探针用作正式集成测试替代品。
