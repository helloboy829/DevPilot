# 本地 QA 发送前身份回执 / Pre-dispatch local QA identity receipt

> 2026-11-10。此模块只补齐失败后原 ID 的安全获取，不是平台授权导出、运行恢复或正式批准。

## 1. 缺口 / Gap

既有本地命令在结束后输出 run ID，但异常/硬退出可能没有最终 stdout。过去原 ID 同时出现在敏感的 observations.jsonl，用户不应为技术对账而打开问题/输出。现在每个新执行目录增加独立的 run-receipt.json；离线预检不创建它。

The receipt separates original run identity from sensitive observations. Final stdout remains one JSON document; the receipt is not a second result stream.

## 2. 顺序与失败关闭 / Ordering and fail-closed behavior

执行仍需全部既有显式 send/input/private-plaintext consent、精确 host policy 和全输入预检。顺序固定为：

1. 独占创建私有结果目录与输出文件，创建原 one-shot SQLite journal。
2. 在同一个被排空的创建工作中，独占新建 run-receipt.json（O_EXCL；支持时 O_NOFOLLOW；POSIX 0600）。
3. 仅一次 os.write，验证完整长度，再完成文件 fsync 和 close。
4. 只有创建工作成功返回，才进入既有共享 run 的 start、reserve、DNS 和发送。

短写、零写、open/write/fsync/close 失败均中止，不补写、重试、覆盖、删除、重建或继续发送。已有文件、目录、符号链接和 FIFO 都拒绝；整个结果目录也仍禁止复用。原 receipt 不在运行结束时更新。

Receipt creation consumes the original run duration; no deadline extension is added. Repeated cancellation drains the ongoing creation/fsync before closing journal and output handles, then propagates cancellation. A creation-phase cancelled run is not started; no permission to resume is issued.

## 3. 固定元数据 / Fixed technical metadata

Schema: local-qa-run-receipt.v1. 固定字段仅包括：

- scope = external_unverified_technical_only；verdict = NOT_EVALUATED。
- receipt_kind = pre_dispatch_identity_only。
- 原 canonical run_id、声明的 manifest_fingerprint、冻结 input/request 数量。
- platform_provenance_verified、resend_permitted、resume_permitted 均为 false。

无 URL、host、header、凭据、输入、金标、输出、错误文本、路径、时间或敏感内容 hash。实际构造的 JSON 有界，测试要求小于 1 KiB。结构指纹不绑定 secret/input values，也不是平台签名。没有 state 字段，不能把启动前的静态身份文件当成当前状态或成功快照。

The file is local, editable and unauthenticated. It is neither a capability nor proof of who produced the run. Never import it as trusted platform evidence.

## 4. 原 ID 操作 / Original-ID workflow

保留用户显式指定的原结果目录。在可信本地文件系统中，单独读取该目录的 run-receipt.json，取得原 run_id；不打开 observations.jsonl。然后显式执行：

```bash
python -m devpilot.local_qa_reconcile \
  --journal ./private-run/journal.sqlite \
  --run-id ORIGINAL_CANONICAL_UUID
```

只读命令仍自行验证原 journal、ID、ALL 冻结分母和预算；**不自动读取 receipt、不扫描目录、不选 latest、不调用目标、不修复、不续跑、不重发**。技术读取成功不等于执行成功。错误/取消提示只提固定文件名，不回显用户文件内容、路径或 traceback。

No receipt (including older runs), an invalid receipt, or an unreadable journal is **not proof of no delivery** and never authorizes a new run. A valid receipt does not prove any send happened either. After a hard process exit, ready/running/dispatched remain the actual journal states; age or process absence does not grant recovery.

## 5. 文件系统与证据边界 / Filesystem and evidence limits

必须由操作者保障父目录/文件的 ownership、ACL 和可信性。POSIX mode 不是 Windows ACL 配置，也不是恶意文件系统沙箱。文件 fsync 的成功仅是该调用获确认；这里没有新增跨平台目录 fsync、存储硬件断电保证、不可变/签名文件或平台 provenance。

部分写入和未知 ACK 留在原处供人工处理。不得根据 receipt 存在、缺失或声明字段推断真实网络交付、exactly-once 或输出已最终落盘。即使 journal 是 collected，最后输出写入仍可失败；对账的 output_content_verified 保持 false。所有冻结样本仍是分母，未运行、未知与失败不被隐藏。

## 6. 验证 / Verification

backend/tests/test_local_qa_run_receipt.py 覆盖真实 SQLite 与共享 collector/run/pinned mock transport：

- 完整 write → fsync → close 在 start/reserve/wire 之前；并发 1/2 与最终单一 stdout 不变。
- 六类 receipt I/O 故障、四类文件冲突、未同意/离线/错误 host/旧目录、journal 创建失败。
- 重复取消阻塞中的 fsync，排空后撤销 claim、关闭两个资源，保持取消。
- 未知交付后只读原 ID，无敏感 output 读取或第二次发送。
- fsync 阶段和 dispatch 后真实子进程硬退出；独立解释器只读对账保持原状态、ID 和不恢复。
- collected 后最终输出写入失败仍没有成功/证据结论；隔离实际模块入口拒绝业务 imports 与真实 DNS/socket。

最终数量、完整门禁、真实 wheel、源码/证据哈希、专用容器收尾及新 SHA 的实际 Actions 在本模块交付记录闭环。初轮硬退出夹具默认并发 2 却断言恰好一项 reservation；改为显式并发 1，保留严格断言和失败日志，未改变运行并发语义或加入重试。

## 7. 未完成 / Not delivered here

不增加 App/API、journal schema、迁移、依赖、配置或默认执行权限；不部署、不调用真实模型/目标。平台授权 exporter、data tiers/provenance、完整锁定分发、敏感输出加密/保留、隔离导入、冻结 QA 调度、Lost Worker fencing、正式批准及授权升级/真实用户验收仍需独立实现与验收。整个平台没有因本模块完成。

## 8. 最终本地门禁 / Final local gates

本模块最终本地门禁：新增 **26 passed**（3.85s），执行/对账/共享核心/平台主链联合 **812 passed**（150.88s）；标准 `make test` **13,008 passed / 18 skipped / 11 deselected / 40 warnings**（758.55s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.62s）；Ruff **1,261 files**、变更领域源独立 lint/format 和 offline lock 通过。前端完整 **152 files / 1,293 passed**（11.2s），完整 Prettier 与九份模块说明核验。真实 sdist→wheel 十三个公开成员逐 bytes 相等，隔离 `-I` 实际 wheel 每次 mock wire 均先验证回执，再由实际 wheel 原 ID 对账，显式检查两个入口的 wheel import origin；真实 DNS/socket 与业务 imports 禁止。未重跑本地 frontend build/browser/performance，不把 wheel 当完整锁定发行。源码/证据/专用资源与新 SHA 的实际 Actions 分别闭环；无部署、执行启用或真实调用。
