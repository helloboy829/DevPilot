# 独立本地 QA run 耐久适配器 / One-shot local QA run journal

## 2026-11-10 后续修正 / Follow-up

[显式本地命令](DevPilot_Local_QA_Command.md)的联合回归暴露同路径只读 handle 未共享 owner lock 的并发失败。现以 canonical-path 进程内弱引用 lock registry 串行所有同路径读写，保留 idle WAL anchor、SQLite timeout=0、跨进程 fail-closed、原断言与未知不重发；新增三项确定性回归，无 retry/更长超时或恢复权限。原模块的测试计数/Actions 是其历史证据，新修复门禁与 SHA 由后续模块单独闭环。

日期：2026-11-10。候选代码；不是已授权 exporter/CLI、平台证据、正式批准或部署。

## 目标与调用边界

`devpilot.local_json_run` 将私有本地 SQLite journal 实际接到既有 `run_json_attempts`，**没有复制 consumer/monitor/HTTP runner**。未来独立运行除共享解析/传输/循环之外，还必须有发送前耐久确认、未知交付不重发与取消排空；这个模块提供该适配，不提前开放导出/API/CLI。

调用者仍须独立提供请求/输入的使用与交付授权、动态出站 policy、单次 collector、敏感输出保存能力、时钟及当前有效性检查。callback 本身不是这些义务已履行的证明。没有默认客户端、凭据、网络访问、执行开关、后台恢复、全局资源配额或平台结果导入。

## 固定合同

- 一份文件只对应一个 run，schema 固定 `local-qa-json-journal.v1`。定义冻结 UUID、调用者声明的 source SHA-256、ALL 输入数、既有 run limits 与累计 body/response 预算。source hash **不证明平台来源、实际请求值相等或同冻结 benchmark**；不计算/保存请求、输入、输出或 gold 的明文 hash。
- 显式新建只使用 O_EXCL；已有文件（包括中断/损坏/空文件）不覆盖、不删除重建。创建/启动结果不确定时只有同文件只读核对，没有重新获取 claim、继续或重发入口。
- 只有首次创建返回的进程内随机 capability 可变更；文件只存 claim/ticket hash，capability 不出现在 repr/snapshot。读取不能取得写能力。私有目录与可信本地文件系统是前提：POSIX 新文件 0600；Windows 依赖目录 ACL。不能防止文件所有者恶意篡改/复制/回滚，也不承诺网络文件系统或坏存储的掉电耐久。
- SQLite WAL 与 FULL synchronous；每个写事务 BEGIN IMMEDIATE，**commit 确认后才返回 ticket**。WAL 支持只读核对与写提交并存；同 owner 的读写在线程锁内串行，其他 writer 锁冲突立即通用失败。无 DB retry、增长 timeout 或凭超时推断旧进程死亡。
- 原始 owner 仅保留一个无事务 idle WAL anchor，防止最后一个连接关闭时 SQLite 清理 WAL 与外部只读 connect/query 竞争。它不跨网络持有事务/数据库写锁；显式 close/context manager 不可逆撤销进程内 claim，异步适配在所有任务、DB 和 finish 排空后 close，不允许遗漏关闭后继续派发。
- ordinal 限于冻结 request_count，每个最多一次；并发 render 可乱序完成，不能额外要求按完成顺序递增。sample_index 永远由 ordinal 与 ALL input_count 推导。并发、absolute deadline、每次 body 上限与累计字节在事务内重查；response 每次保守预留 max+1，任何观测/失败/结束都不循环回收额度。
- 顺序是共享核心 input-only render → 本地 durable dispatch ACK → 一次 collector → 技术记录提交 → 显式敏感输出 callback。未知交付先由共享核心停止新发送；journal 同时中断新派发，但允许已发送的其他 ticket 排空记录。已有 ACK 不等于远端 exactly-once。
- 只存 ordinal/sample_index、字节、技术分类/status/elapsed、状态和声明定义；无 endpoint/header/body/Q/A/gold/原始输出/ciphertext。ALL 分母来自冻结定义；未派发不被删出分母。输出 callback 不成功则整个适配调用失败，不输出完整证据或质量结论。
- collected 仅代表所有冻结 ordinal 技术记录及显式输出 callbacks 返回，HTTP error 等也可能 collected；**不是 PASS、完整平台证据或批准**。取消/失败后仍 dispatched 的 ordinal 保守转 delivery_unknown，保留累计额度。硬进程退出可能停在 running/dispatched；重开只读、不回收，不以 deadline 授予继续/重发。

## 取消与异常

所有运行中的 SQLite 读写（包括 monitor reads、初始 snapshot、start 与 finish）使用线程 offload + shield 排空。外层重复取消只取消内层 run 一次，等待原 shared core 的 consumers/monitor、网络与 DB 回调结束，再 finish。取消始终向上传播；不以重试/超时跳过排空。start 未确认没有派发/收尾权限；finish 结果不确定不重新执行。如果业务异常与 finish 异常同时发生，保留原异常及 cause，不隐藏持久化失败。

取消无法杀死已开始的同步 render/parser/output 线程或证明远端业务已停止。崩溃后的文件只是保守技术记录，不能拿来恢复旧发送、释放平台 reservation 或认证外部结果。

## 验证 / Verification

新增回归覆盖：严格定义/时钟、独占文件、读不能 claim、乱序 ordinal/CAS、并发和累计不回收预算、票据与七类技术观测、真实 commit 后 ACK 丢失、WAL 读写并存、重复取消的 reserve/record/monitor/start/finish 排空、真实子进程硬退出、所有 frozen ordinals、真实共享核心/collector 的 MockTransport 请求及无 business imports 的隔离源运行。真实 sdist→wheel 及实际 wheel 完整 mock run 单独核验，不将 callback/源码 import 冒充授权 exporter。

首轮发现默认 rollback journal 下外部只读核对会阻止提交，以及并行 render 完成顺序不保证 ordinal 顺序；运行实现改为 WAL 和每 ordinal 一次 CAS，未加入重试或加长锁超时。后续 uncertainty 测试最初只按一个 dispatch 计算，而并发二可在未知 ACK 前各提交一次；用 commit barrier 固定两项已提交，再分别断言全部不发送、全额保留，不削弱原单并发断言。保留失败日志与最终重跑。首次联合回归另出现 633 passed / 1 failed：WAL 模式本身仍不能阻止最后连接清理与外部只读重连的锁竞争；通过无事务 idle anchor 和最终 drained close 修正连接生命周期，新增 close/claim 撤销与 100 次并发读写回归，未重试或放宽 timeout/assertions。

本模块最终本地验证：新增 **79 passed**（最终源码复核 5.58s）；联合 **636 passed**（130.45s）；标准 `make test` **12,832 passed / 18 skipped / 11 deselected / 40 warnings**（756.54s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.57s）；Ruff **1,258 files**、新领域模块单独 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（11.4s），完整 Prettier 与七份模块文档格式独立核验。真实 sdist→wheel 的十个公开成员逐 bytes 相等，实际 wheel 在 `-I` 解释器中使用锁定 HTTPX 完整 mock run，禁止 business imports、真实 DNS/socket；不是无 site packages/零依赖或授权 exporter。联合开始后的最后源码编辑仅纠正文档字符串；最终新增回归、wheel 和完整后端均覆盖该最终源码。

源/提交/evidence hashes、资源收尾与本次精确 SHA Actions 分别记录；首次通过不替代最终源码检查。无 frontend runtime 变更；本模块不重跑本地 build/browser/performance，不借用历史验收结果。

## 后续与回退

下一步才实现来源/数据交付合同、依赖 pin、独立 CLI 的显式 outbound/TLS/DNS/budget/实发确认、敏感输出治理与 external/unverified 结果隔离；当前 source hash 和 collector callback 都不能替代它们。正式批准、冻结 QA 独立调度、lost Worker fencing/对账和另行授权的保留数据升级/真实用户验收仍独立未完成。

没有 App API/权限/迁移/新依赖，也不切换 App Worker 到本地 journal。候选 head 仍 eval_0012，历史部署 eval_0009 未复核或升级。回退移除新适配模块、测试与文档引用；不删除本地历史 journal、不改平台 ledger，不触碰业务配置/账户/数据/执行开关。

## English summary

The one-shot local adapter genuinely reuses the complete shared JSON run core. Exclusive private SQLite creation, in-memory capabilities, WAL/FULL commits, per-ordinal CAS and non-recycled budgets precede every collect callback. Unknown commits never grant a send ticket; reopening only reads and cannot resume or retry. All database reads/writes and the original task group drain before finalization, including repeated cancellation. Metadata is external/unverified; declared hashes are not platform provenance, collected is not PASS, and output persistence/admission remain explicit caller obligations. No API, migration, new dependency, default client, deployment or execution enablement is added.
