# QA 关闭重复取消排空 / QA shutdown drain under repeated cancellation

> 2026-11-10：关闭生命周期候选修复；合成/离线回归，不启用执行，不部署，不回收丢失 Worker 配额。

## 已确认问题

`qa_execution_runtime` 原先取消 Worker 后直接 await `asyncio.gather(task, return_exceptions=True)`。当 Gateway 关闭协程再次被取消，gather 会向同一个 Worker 再次传递取消。Worker 可能正在自己的 finally 内等待网络任务/数据库私有操作排空，第二次取消会提前中断清理并让生命周期返回；原本的 `evaluation_execution_repo = None` 也可能被跳过。这不是远端已停止、可重发或可强制释放的证明。

先在未修改运行代码的 `6142029b921319e33c8819713f750ebbc3a497f9` 上添加事件屏障测试：**7 failed / 4 passed，6.75s**。六个 normal/cancelled/error body × 一次/三次再次取消均观测到 Worker `cancelling() == 2` 而非唯一初始取消；真实 Worker 用例观测到清理屏障未释放，生命周期却已结束，并留下未取回的 gather CancelledError。失败日志完整保留，未通过加超时/重试、删除断言、改 SQLite 设置或测试串行化掩盖。

## 实现合同

`backend/app/evaluation/execution_lifecycle.py` 增加内部 `_stop_and_drain_worker`：

1. 只对原 Worker 调用一次 `cancel()`；不启动替代 Worker，不重跑 coroutine，不创建新 claim/派发或重试。
2. 只创建一个 `gather(..., return_exceptions=True)` 等待器，循环 shield **同一个** 等待器；重复外层取消只被记住，不传播到排空中的 Worker。
3. 原 Worker 的网络/数据库清理完成后，才向外重新抛出收到的 `CancelledError`。正常关闭不因 Worker 自身取消抛错；原 body 的异常没有新外层取消时仍保持原异常，不泄露 Worker 清理异常详情。
4. `evaluation_execution_repo` 在最终 finally 中清除，时间点位于排空之后；数据库资源不会因重复关闭取消而提前获准销毁。
5. 不增加任意排空超时或后台 orphan 任务。原 Worker 的 `_drained_database`、dispatch-before-send、取消/证据/finish 与 reservation 规则不改。真正硬崩溃/丢失 Worker 仍保留不确定配额，deadline 仍不是死亡证明。

这修复**有序本地关闭**，不提供分布式进程死亡证明、出站永久 fencing、远端处理取消或管理员释放权限；不能由此宣称安全自动恢复完成。

## 回归范围

`backend/tests/test_qa_execution_lifecycle.py` 保留默认禁用/单次关闭/无效策略三项，新增 **8 项**：

- 六项事件屏障：normal、已取消、已抛错的 body，各在 drain 中再次取消一/三次；要求 Worker 仅收到初始一次取消、生命周期/repository 不提前退出、真实迁移临时 DB 仍可读、最终取消向外传播、状态清理与数据库 teardown 顺序严格成立。
- 原 body failure + Worker cleanup failure：必须先排空，保留原 body 异常，不泄露/替换为 Worker 异常。
- 真实 `QAExecutionWorker` + 迁移临时 SQLite + 两个合成 collector：屏障未释放前配额保持占用；多次关闭取消不截断 collector；两个原本任务都排空后 finish/interrupted/配额释放，不能再次 claim，不新建请求或重发。

只替换合成 collector，不连接真实目标或模型；临时测试密钥与授权由既有 fixture 明确建立。policy enabled 仅存在于合成测试，不改运营配置。实际门禁结果见下节；未运行项不算通过。

## 实际验证与环境修正

- 修复后联合主链 **82 passed，114.54s**（另一次 **113.83s**），包含本次 11 项 lifecycle 和执行/路由/API→Worker/独立及真实登录合成链；不把重跑或定向用例叠加到全量计数。
- 首次完整后端 **3 failed / 12,415 passed / 55 skipped / 11 deselected / 7 errors，731.98s**。逐项检查后确认 PostgreSQL 专用容器当时未启动，三项迁移失败和七项 PostgreSQL/去重 fixture 错误均为 `devpilot-word-postgres` 测试主机名解析失败；Redis 也未启动，导致额外跳过。保留原失败日志/退出码，启动原先停止的专用合成数据库容器并检查就绪，再重跑相同全量门禁，不改断言、超时或业务配置。
- 前端运行代码未变，仍重跑完整 **152 files / 1,293 passed，14.9s**，整个 `pnpm format` 与七份本模块 Markdown 格式检查均通过。未重跑本机前端 build/浏览器/资源预算，前一模块结果另列，不冒用为此修复的验证。
- 修正隔离依赖后的同一 `make test` **12,462 passed / 18 skipped / 11 deselected / 40 warnings，730.48s**，exit=0；11 个 live 模型用例被排除，18 个可选环境跳过不能记为通过。`make test-blocking-io` **72 passed，5.49s**；全目录 Ruff check/format **1,252 文件**通过，`uv lock --check --offline` 通过。没有通过自动执行启用、重发或弱化检查修绿。
- 实际 Python 快照 **1,362** 份、Node 前端/模块说明 **857** 份公开文件分别以逐项 SHA-256 核对，文本按 Git 统一行尾、二进制保留原字节；提交后再核对 Git archive。成功、旧代码红灯及首次全量环境失败的日志/退出码一并导出，archive 与每个成员 hash 在宿主核验后才清理会话临时文件、停止本模块启动的四个容器。源码与证据收据保存在下列 ignored 目录，不提交测试 DB、运行配置或依赖目录。
- 本模块仍须自己的独立提交/普通 push 与精确 SHA Actions 核验，不能借用 `6142029` 的五项成功；路径未触发的 E2E/Replay/Skill Review 不算本模块 CI 通过。

本机 ignored 证据 `.deer-flow/ci/20261110-shutdown-drain/`，不提交日志、私有配置、数据库或虚拟环境。测试结束、导出并核对 archive/member hash 后，仅停止本模块启动的四个专用 Python/Node/PostgreSQL/Redis CI 容器，不删镜像/卷/业务服务、不 prune。

## 兼容、回退与未完成

无 API/权限、依赖、lockfile、迁移、运营配置、执行启用或部署变更。候选 head 仍 `eval_0012`；历史部署 `eval_0009` 不因此更新。本模块回退仅涉及生命周期 helper/等待方式和对应测试/文档，不能改旧数据、claim、档案、分母、审批或未知结果同 ID GET-only 合同。

丢失 Worker 永久 fencing/人工对账与安全释放、冻结 QA 调度准入、统一版本化可执行导出、正式批准政策/生命周期、另行授权的保留数据升级及真实用户验收仍未完成。

## English summary

Repeated cancellation of Gateway shutdown used to cancel the original Worker again through an unshielded gather, interrupting its pending cleanup and allowing lifecycle exit before drain. Seven deterministic new cases fail against the unmodified baseline; an eighth preserves original body errors despite Worker cleanup failure. The fix cancels the original Worker once and shields one shared drain waiter through repeated outer cancellation, then re-raises cancellation only after that same Worker exits. Repository state clears in a final cleanup block after drain. The real Worker regression uses a migrated temporary SQLite database and two synthetic collectors to assert held quota before drain, terminalization/release only afterward and no second claim or resend. This is orderly local shutdown, not distributed death proof, remote cancellation, forced release, retry authority or automatic recovery. The final offline suite passes 12,462 tests (18 optional skips and 11 live deselections), with 72 Blocking IO and 1,293 frontend tests also passing. The first full run failed because isolated PostgreSQL/Redis dependencies were stopped; its original evidence is retained and the same suite passed after starting only those dedicated synthetic services. No API, permission, dependency, migration, operator configuration, deployment or real model/target call changes.
