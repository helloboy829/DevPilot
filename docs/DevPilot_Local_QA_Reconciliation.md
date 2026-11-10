# 本地 QA 只读对账命令 / Read-only local QA reconciliation

> 候选代码，2026-11-10。只读技术快照，不是平台证据、真实交付证明、重试/续跑许可或正式批准。无新依赖、App/API、迁移、配置、部署或执行启用。

## 1. 解决的问题与显式操作

[本地执行命令](DevPilot_Local_QA_Command.md)在中断、落盘失败或硬进程退出后保留原目录。新命令提供实际可用的原 ID 技术对账，不要求打开明文输出或编写 Python，不新增第二个 runner。

该命令只有离线读取模式，没有 execute、repair、resume、force、latest、目录扫描、轮询、网络、结果导入或任何自动重发入口：

```bash
python -m devpilot.local_qa_reconcile \
  --journal ./private-run/journal.sqlite \
  --run-id 00000000-0000-0000-0000-000000000001
```

使用 Python 3.12+ 和原安装中的锁定依赖。路径必须指向原可信 journal，ID 必须为显式的原规范小写 UUID；不会替换为目录中另一个 run。ID 从运行时保存的技术收据/原目录记录人工取得；不自动选择 latest，不从 plaintext output 读取。文件缺失/损坏、ID 不符、锁冲突、schema 或技术字段不一致均通用失败，不创建、重建、迁移或重试。

## 2. 只读合同与分母

实际重用 `LocalJSONJournal.open → snapshot` 的单事务一致性读，所有同路径进程内 handle 共用 canonical-path lock。SQLite `mode=ro` / `query_only=ON` / timeout=0；不取得 claim、不调用 start/reserve/record/finish，不撤销仍活跃的 owner claim。进程间冲突立即失败关闭，不放大超时，不轮询。读取和最终 close 完成后才返回。

JSON `local-qa-reconciliation.v1` 保持 `external_unverified_technical_only` / `NOT_EVALUATED`。固定字段包括：

- 原 run ID、声明的 source SHA、原技术状态；source hash 不是签名、请求/输入值绑定或平台来源认证。
- ALL 冻结 input/request 分母、已 reservation 数、快照中未 reservation 数、覆盖 input 数。
- dispatched / observed / delivery_unknown 计数，以及固定七类 observation 的计数；不泄露每条输入、输出、凭据、claim 或任意数据库自由文本。
- 累计 request/response reservation；响应按每次 max+1 不回收，即使 HTTP error 或 policy rejection 也是原 reservation。
- output_content_verified / platform_provenance_verified / resend_permitted / resume_permitted 恒为 false。

核对每条 ordinal 的范围、排序/唯一、循环 sample index、请求字节、状态/kind/HTTP/大小/时长一致性，以及整个快照累计预算和 collected 完整性。原 journal 允许乱序不同 ordinal reservation，因此不擅加连续 ordinal 条件；也不把部分/成功子集当分母。observed 不等于 output_collected；HTTP error 等技术终结不等于 PASS。

## 3. 未知、活跃与文件边界

硬退出后原状态可能仍是 running / dispatched；此命令**不把它改写为 interrupted、未发送或已死亡**。interrupted 也可能有仍在排空的 dispatched。finalization 已把派发标为 delivery_unknown 但缺完整 observation 时保持未知。没有 reservation 只表示该可信本地快照无对应行，不能证明目标未收到、文件未被回滚或允许发送。

collected 只证明 journal 中所有技术观察已记录；不能证明 observations.jsonl 的最后 fsync、输出完整性或真实目标 exactly-once。输出文件即使被截断/移除也不会在此读出或认证，不允许因此清空原目录、new-ID 重发、resume 或向平台导入成可信 evidence。

只接受显式可信本地路径，预检主文件及现有 -wal/-shm/-journal 为有界普通文件（各至多 16 MiB），拒绝最终 symlink/FIFO/directory；主文件读前后身份不同拒绝。**这不是 hostile SQLite 上传解析沙箱或无竞争文件系统安全保证**。可信父目录、Windows ACL、文件所有者和运行环境由操作者保护；不支持网络文件系统、恶意同用户替换、回滚或任意损坏文件资源隔离。SQLite 只读事务可能维护 WAL/SHM bookkeeping，所以不承诺目录零物理写入或所有 sidecar bytes 不变；业务 run/attempt 行不修改。没有打开 manifest/values/inputs、gold、observations.jsonl 或平台 DB。

成功退出码 0 仅说明指定 ID 的技术读取成功，**不是 run 成功/批准**；拒绝码 1，Ctrl-C 130。失败只显示固定通用错误，不打印 path、ID、数据库异常或 traceback。保留原文件用于人工调查，不自动恢复/重发。

## 4. 验证与交付边界

合成测试使用真实 SQLite WAL、真实本地 journal 和实际 module entry；断开业务 imports、DNS/socket。覆盖 ready/running/collected/interrupted、七类观察、未知 observation 缺失、故障数据、全分母/累计 reservation、只读 SQL 与原 owner 继续持权、跨进程锁失败、不创建/修复文件、非普通/超大文件、主文件身份变化、同路径锁、硬退出 WAL、实际执行 CLI mock wire → 独立对账 CLI。真实 wheel 的实际命令也作为包装门禁。

门禁结果、精确提交与实际触发的 Actions、源码/证据 hash 和专用 CI 资源收尾分别核验，不把 push 成功当 CI 成功。首次 Ruff import/format 失败证据保留，正常修正，不弱化检查。没有真实目标/模型调用，也不改平台授权/出站或既有执行命令。

## 5. 未完成与回退

平台授权 exporter/来源 manifest/数据交付 tiers、完整锁定依赖分发、输出加密/保留治理、外部结果隔离导入、冻结 QA 独立调度、Lost Worker fencing/对账、正式批准与另行授权升级/真实用户验收继续独立开发。本模块不把自建本地运行升级为平台 evidence。

回退仅移除新命令/测试/文档入口，不回滚数据库、不改 journal schema、不删除结果或撤销原 owner；未知仍不重发。既有 CLI 默认离线与明文同意合同完全不变。

本模块最终本地门禁：新增 **64 passed**（4.00s），联合 **786 passed**（157.99s）；标准 `make test` **12,982 passed / 18 skipped / 11 deselected / 40 warnings**（756.47s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.60s）；Ruff **1,260 files**、新领域模块独立 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（13.0s），完整 Prettier 与八份模块文档格式核验。真实 sdist→wheel 十三个公开成员逐 bytes 相等，隔离 `-I` 实际 wheel 的执行 CLI mock sends → 对账 CLI 成功，并显式确认模块 import origin 位于 wheel；真实 DNS/socket 和业务层 imports 禁止。源码/证据/专用资源与新 SHA 实际 Actions 独立闭环。未本地重跑 frontend build/browser/performance；无部署/执行启用/真实调用。
