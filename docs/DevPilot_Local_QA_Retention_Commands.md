# 本地输出保留管理命令 / Local retention commands

2026-11-14。命令复用[输出保护与保留 API](DevPilot_Local_QA_Protected_Output.md)，只处理明确指定的新格式结果目录。它不运行 QA、不读取 key、不解密或显示 Q/A，不发现 latest、不创建旧目录回执、不修复、续跑或重发。所有 metadata 都是本地未认证技术声明，保持 `NOT_EVALUATED`；hash 不证明来源，文件缺失不证明安全擦除。

## 1. 显式只读检查

从独立安装的 Python 3.12 venv 执行；以下均为占位参数。原 `run_id` 可从该目录的 `retention-receipt.json` 获取，不能用新 ID 或其他目录的回执替代。CLI 不自动读取环境变量、key、业务配置或其他结果目录。

```sh
python -I -m devpilot.local_qa_retention inspect \
  --directory ORIGINAL_RESULTS --run-id ORIGINAL_RUN_UUID \
  --manifest-fingerprint ORIGINAL_MANIFEST_HASH
```

返回一行 JSON：原身份、保留期、ALL 输入/请求分母、并发/timeout/duration、三个字节预算、receipt SHA256、ciphertext SHA256、存在性及到期状态。只作有界字节 hash，不认证或解释输出；即使文件实际完整，`content_status=not_inspected` 和 `output_integrity_verified=false` 也不能被当成“证明未完成”。仅有 receipt 而无输出时返回 `output_present=false`、ciphertext hash 为 null，不创建或修复文件。

活跃运行持有的独占 retention lease 会使检查/处置立即失败，不等待、不重试。父目录、账号、时钟、权限和文件系统必须可信；这不是恶意同用户或 hostile-filesystem 沙箱。

## 2. 单独同意到期处置

先查看原目录的检查结果，保留原 receipt/ciphertext 两个 hash。由 operator **显式提供一个 canonical disposal UUID**，并在调用前自行保留；命令不生成 ID、不自动选择文件、不提供时间覆盖参数。先前加密输出同意不授予删除权。

```sh
python -I -m devpilot.local_qa_retention dispose-expired \
  --directory ORIGINAL_RESULTS --run-id ORIGINAL_RUN_UUID \
  --manifest-fingerprint ORIGINAL_MANIFEST_HASH \
  --disposal-id ORIGINAL_DISPOSAL_UUID \
  --confirm-retention-receipt-sha256 VIEWED_RECEIPT_SHA256 \
  --confirm-ciphertext-sha256 VIEWED_CIPHERTEXT_SHA256 \
  --confirm-incomplete-output-disposal
```

缺少任一 ID、hash 或单独同意均拒绝；不接受选项缩写、key/时间/repair/resume 参数。复用真实 API：原身份/到期重检 → 同 descriptor 独占锁及两遍有界 hash → durable intent → 一次精确 unlink → directory fsync → 完成回执。不递归、不删 journal、身份回执、key、明文副本或其他文件，不建立后台清理器。

该命令按原 ID/hash 同意删除**未认证的指定 ciphertext**，不证明内容未完成或损坏。完整输出的持 key 认证清理仍由原 `devpilot.local_qa_output purge-expired` 独立提供。到期和删除不是安全擦除；Windows 持锁删除尚未实际验收。

## 3. 未知结果只按原处置 ID 对账

任何写入、删除、同步、关闭、进程中断或 stdout 丢失的不确定结果，都保留原目录及调用前提供的 IDs。不能重跑处置、换新 ID、补写 intent 或修复残留文件，只执行：

```sh
python -I -m devpilot.local_qa_retention reconcile-disposal \
  --directory ORIGINAL_RESULTS --run-id ORIGINAL_RUN_UUID \
  --manifest-fingerprint ORIGINAL_MANIFEST_HASH \
  --disposal-id ORIGINAL_DISPOSAL_UUID
```

返回原 intent 的技术声明、完成回执存在性和当前输出存在性；不读取 key 或输出内容。没有 intent、损坏 intent、ID 不匹配或丢失锁时拒绝，不重建；无法确认的状态仍未确认。即使当前输出已不存在，也不能由此授予重试、续跑、平台证据、PASS 或批准。

成功的 metadata 操作返回 **0** 和一行 JSON；参数/文件/未知操作失败返回 **1**，捕获键盘中断返回 **130**。失败只在 stderr 输出固定通用消息，不输出路径、输入参数、异常详情或输出内容。退出码 0 只表示该技术操作完成，不代表 QA 通过；对账的 `completion_receipt_present=false` 不会被转成“已完成处置”。

## 4. 验证与剩余边界

离线回归使用真实 receipt、锁和文件 API，覆盖独立同意、原 ID/hash、未到期、无输出、缺失元数据、未知 unlink/fsync/完成回执、中断和 stdout 丢失。真实独立 module 进程拒绝业务/执行模块导入、DNS/socket 和 Fernet 解密；软件分发验证另在新 no-system-site venv 完整离线安装 12 个锁定运行依赖，执行实际已安装的三条命令并检查缺同意/重复处置拒绝。

不新增依赖、迁移、平台 API、部署或真实请求。plaintext 副本、更广泛崩溃产物、Windows 实际安装/持锁删除和正式批准仍独立待验收；Linux 结果不能替代它们。逐轮结果见[交付状态](DevPilot_Delivery_Status.md)与[历史](DevPilot_Delivery_History.md)。

English: Explicit inspect, separately consented expired disposal and original-ID read-only reconciliation reuse the existing bounded retention API. No key, decryption, execution, retry, repair, new-ID replacement or secure-erasure/provenance/approval claim is added. Unknown results retain the original IDs and files; installed-software and platform acceptance are separate gates.
