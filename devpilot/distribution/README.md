# Offline local QA software distribution / 离线本地 QA 软件分发

This archive is **software only**, not a platform-authorized data export, signed release, execution authorization or approval. The declared source revision and file hashes are integrity metadata, not authenticated provenance. Obtain the archive SHA256 through a separately trusted channel and compare it **before extraction**. An attacker can replace both an archive and its internal manifest. Use only trusted filesystems/parents and privately controlled output directories; this is not a hostile-file sandbox.

分发范围仅为软件：Python **3.12**、十三个锁定 wheel（第一方和十二个运行依赖）、全量第一方 wheel 源码成员 hash、requirements、原仓库 MIT 许可和纯合成示例。第三方 wheel 保留各自的完整许可文件；不剥离或重打包。不是平台导出、来源认证、密钥管理或批准；不得加入真实请求、输入、gold、账号配置、凭据、评审或数据库。不要复制旧机器的环境。

## Install explicitly / 显式安装

Check the trusted external SHA256 first (PowerShell: Get-FileHash; POSIX: sha256sum). Then extract the trusted archive to a **new** directory. Do not execute files from an untrusted archive. From the extracted directory, create a fresh Python 3.12 environment **without system-site-packages**:

```sh
python3.12 -m venv .venv
.venv/bin/python -I -m pip --isolated install --no-index --find-links wheels --require-hashes --only-binary=:all: -r requirements.lock
.venv/bin/python -I -m pip --isolated check
.venv/bin/python -I -m devpilot.local_qa_cli --manifest examples/manifest.json --values examples/values.json --inputs examples/inputs.json
```

Windows: use the explicitly selected Python 3.12 executable to create the venv; substitute .venv/Scripts/python.exe for .venv/bin/python. No activation script or execution-policy change is needed. The v2 software format declares a native platform (cryptography/cffi wheels); use only the matching CPython 3.12 archive. Linux verification is **not Windows acceptance**. No guarantee is made for Python 3.13+ or another platform.

最后一条命令默认仅 OFFLINE preflight，不发送网络。example.test 与所有输入/凭据都是合成占位值，不是可用目标。此分发不提供实发快捷脚本。真实使用必须另行获得目标、数据、host policy 和独立输出模式授权，显式配置输入和新结果目录；不能以此示例或 manifest hash 代替同意。Fingerprint 仅绑定结构，不认证输入/凭据值。

## Results are not approval / 结果不是批准

Existing commands retain shared bounded collection, dispatch-before-wire, ALL frozen denominators and no retry/resend/resume. Before dispatch, the explicit run writes a metadata-only run-receipt.json; read its original run_id, then explicitly reconcile only that original journal and ID:

```sh
.venv/bin/python -I -m devpilot.local_qa_reconcile --journal ORIGINAL_PRIVATE_DIRECTORY/journal.sqlite --run-id ORIGINAL_CANONICAL_UUID
```

No latest discovery, sensitive-output opening, repair, continuation, platform import or independent acceptance is added. Missing/invalid receipt is not proof that no send occurred. Uncertain delivery stays uncertain. Local outputs remain external_unverified_technical_only / NOT_EVALUATED. Explicit operator-key encrypted output requires --output-key-file, --output-retention-seconds and --confirm-encrypted-output; legacy private plaintext requires --confirm-plaintext-output. Neither mode is implicit. Encrypted inspect/open/expired purge always requires original IDs, separate consent and the controlled local-output workflow. Expiry is not secure erasure; plaintext copies and incomplete/crashed outputs need separately authorized retention governance. A collected state does not prove output fsync, successful target delivery, platform provenance or approval.

## Build boundary / 构建边界

The repository builder reads the tracked backend uv.lock, validates the exact Python 3.12 runtime closure and official wheel archive SHA256/size, and checks **every** first-party source/metadata/RECORD member against the explicitly selected trusted source. It never downloads, installs, executes a wheel, reads App configuration or exports platform data. Extra, missing, modified or non-regular files fail closed. Output is exclusive; preserve partial output on uncertain I/O, never overwrite/retry automatically. Fixed ZIP member metadata and sorted files make identical inputs reproducible under the same builder/compression runtime; no cross-version compressor or parent-directory/power-loss durability guarantee.
