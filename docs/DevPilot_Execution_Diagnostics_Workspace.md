# 执行预留诊断工作区 / Execution reservation diagnostics workspace

日期：2026-11-10。候选只读前端；不部署、不启用执行，不解决失联 Worker 安全释放。

## 范围与操作

`/workspace/operations` 提供中英文人工管理员入口，复用[后端只读技术聚合](DevPilot_Execution_Reservation_Diagnostics.md)。侧栏入口只随登录身份/角色变化，不随当前路由插入创建行；直接输入 URL 也没有越权读取能力。

- 进入页面、修改语言、登录身份变化、路由重新进入均不请求诊断。只有明确点击“手动加载预留快照”才发出一次 GET。
- 显示全局持有运行数、并发/请求体/响应字节预留及达到截止时间的运行数；完整显示 queued/running/cancel_requested/collected/interrupted 五态，不移除中断占用。
- 独立显示响应进程的执行开关/策略上限，不相减推断可用配额，不把超过当前策略的真实占用截断为上限。
- 时间是查询前采集的 Unix 毫秒，不是心跳。达到 deadline 不证明 Worker 或远端处理已停止；策略也不是全局进程一致性回执。
- 没有释放、回收、过期、重试、发送、取消、配置或启用执行按钮。没有轮询、后台加载、自动重试、导出、持久化缓存或敏感证据读取。

## 严格读取与认证

`core/evaluation/execution-operations.ts` 只向固定 `/api/evaluation/operations/reservations` 使用已有 authenticated fetcher，GET + `cache: no-store` + AbortSignal，保留原有 cookie/401 行为，不新建认证通道。

响应必须为成功 JSON MIME，声明及实际流均不超过 **16,384 bytes**。流式严格 UTF-8 解码、JSON 和 strict schema 校验失败一律安全拒绝：固定 scope/policy_scope/liveness，四个 authority 必须 literal false；所有计数/时间必须是非负安全整数；策略范围等于后端；顶层/嵌套额外字段和缺失状态拒绝。以 BigInt 累加五态总数，精确核对全局 held/deadline，逐态 deadline 不大于 held；不运行浏览器阈值/授权引擎。

错误只展示通用文案，不读取/反射 HTTP 错误 body，不输出 raw JSON、异常、服务器细节或标识符。未授权身份在页面内无加载控件；UI 角色判断仅控制展示，**服务器 admin + `evaluation_operations:read` 和 internal-Agent 拒绝仍是安全边界**。

## 生命周期与并发

`ExecutionOperationsPanel` 把快照和请求锁隔离到账号 key 的子树。身份未确认、auth refresh、退出或失去 admin 时直接卸载子树，账号改变也直接重建；旧快照不能跨账号显示，重新进入/同 ID 重新登录也不会恢复旧数据。

每次显式读取先同步 ref 加锁并清除旧快照/错误，防同一 tick 重复点击。layout cleanup 立即撤销 mounted 标记并 abort GET；每次 await 后核对当前 request/controller、mounted 和 aborted，再接受结果/错误或解锁。旧账号的迟到成功、失败和 finally 都不能修改新账号子树。取消 GET 不是取消 Worker、释放配额或重新发送执行。

不改变 AuthProvider 的既有身份刷新策略。auth refresh 可以清空诊断，但不会自动重新加载；不新增账号目录、权限授予、密钥、请求定义或证据打开。

## 验证与证据边界

本模块使用本线程从 tracked source/lockfiles 重建的隔离 Node/Python 依赖缓存；不复制其他机器的私有配置、数据库或虚拟环境。所有测试为合成/offline；模拟浏览器以合成禁用认证模式运行，不能替代真实生产认证浏览器或部署验收。

- 定向严格读取/React HappyDOM：包含超策略占用、中断保留、完整五态、所有 literal authority、字段/计数/结构污染、MIME/声明及流上限、UTF-8/JSON/网络失败、无错误反射/重试、重复点击、账号/角色/auth refresh/退出/卸载和迟到成功/失败。
- 模拟 Chromium：桌面/390px 手机、键盘显式加载、稳定侧栏、重新进入不加载/不恢复、中文校验错误、无持久化快照、角色降级时 abort/fence，不允许释放/执行请求。
- 完整 frontend 单测、Prettier、ESLint、typecheck、生产 build、完整模拟浏览器与单独认证恢复；相关后端联合授权/诊断/执行主链、Blocking IO 和 Ruff。实际结果在交付矩阵记录；不把上轮全量后端成绩当成本轮重跑。

首次测试使用了当前 Rstest 不支持的 mock factory 参数，导致 DOM mock 初始化失败；修正为固定五态 + 专用加载 mock，保留失败日志，不改运行时行为/断言/超时或重试。随后全量 lint/typecheck 发现测试中不必要类型断言、缺少 `User.needs_setup` 和异构 headers 夹具类型；逐项修正夹具/类型写法，不关闭规则、不做类型逃逸，完整门禁重新运行。Playwright 原生 ESM 不接受无 import attribute 的 JSON 夹具导入，因此改用公开 TypeScript 共享合成 fixture，保持所有实际数值/断言不变；新增错误亦保留。首轮完整浏览器还发现新增定位器范围过宽，混入品牌首页链接、Next.js route announcer 和当前页 breadcrumb；改为精确工作台标签/诊断 region/工作区 navigation，保留原有断言目标与全部失败上下文，不删测试或改运行导航/授权。

本轮新增严格读取 44 项、React DOM 12 项；完整前端 **150 files / 1,262 passed**，格式/lint/typecheck/build 通过；完整 Chromium **230 passed**、认证恢复 **2 passed**，均零自动重试。后端相关联合 **82 passed**、Blocking IO **72 passed**、Ruff **1,252 文件**通过，没有重跑整个后端套件。

**性能预算仍失败**：同依赖/同容器/同脚本的模块前提交 `4f94b2c0a73a00a023fffafbcb06f01919c13b4c` 亦失败，六个现有基准路由 CSS 超额，docs/blog JS 超额。本模块 CSS 各增加 40 bytes，docs/blog JS 增加 7,754 bytes；这不是性能通过，也不借 Actions 中未运行的性能 job 宣称通过。原始两次 measurements/失败日志完整保留；独立性能模块须在不提高预算、不删除路由的前提下修复真实资源。对照过程仅暂存公开源码，退出时完整恢复本轮源码；最终 manifest 验证无缺失/不符。

本机证据 `.deer-flow/ci/20261110-execution-diagnostics-ui/` ignored，不提交。最终源码 manifest 与实际容器逐项核对，导出日志后再核对 archive/member hash；所有测试和导出完成后仅停止本轮启动的精确两个专用容器。保留业务服务、缓存、镜像和卷，不 prune。

## 兼容、回退与未完成

无依赖、迁移、运行配置或后端 API 行为变化；候选迁移 head 仍 `eval_0012`，历史部署收据 `eval_0009` 不因本模块改变。回退仅撤销本模块页面/组件/客户端/入口及测试，不编辑已部署迁移，不触碰旧运行/档案/hash。

配额安全释放/丢失 Worker fencing、调度执行准入、正式批准政策、授权保留数据升级及真实用户验收均未完成。诊断页面不是修复、授权或平台完成证明，不隐式部署或调用真实模型/目标。

## English summary

This candidate adds an explicit human-admin, read-only workspace for the existing aggregate GET. It never fetches on mount, role/account change or navigation. Strict bounded streamed JSON validation preserves every held state, checks exact totals, rejects unknown fields/unsafe counts/authority changes and does not clamp occupancy to the serving policy. Synchronous request locks and account-keyed state, layout cleanup/abort and post-await fences prevent duplicate sends or stale account results. Errors stay generic, snapshots stay in page memory, and the backend remains authoritative. Unit/lint/types/build and all 230 browser plus two auth-recovery cases pass, but the six-route asset-budget gate still fails against both the pre-module baseline and this candidate. The measured increase is retained for a separate performance fix, with no raised budgets or dropped routes. There is no release/reclaim/retry/dispatch control, dependency, migration, configuration change, deployment or real call. Deadline reached is not Worker death; policy is serving-process-only, and observations are not heartbeats. Safe release, scheduling admission, formal approval and authorized deployment/real-user acceptance remain unfinished.
