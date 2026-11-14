# 本地 QA 输出加密与保留 / Local QA protected output and retention

> 2026-11-11 候选模块。开发、回归、提交、推送与精确 SHA 的 Actions 是独立门禁；本模块不部署、不启用执行、不调用真实模型或目标，也不代表平台完成。

## 1. 范围 / Scope

`devpilot.local_qa_output` 为同一条 `local_qa_cli → run_local_json_attempts → run_json_attempts → collect_json_attempt → PinnedHTTPTransport` 链增加显式 operator key 的加密输出。没有第二套 runner、App/Harness 反向导入、环境 key fallback、自动生成 key 或金标传入。原 manifest/journal/发送前身份 receipt 的 v1 合同保留，原 run ID 和 manifest fingerprint 用于所有后续操作。

旧 `--confirm-plaintext-output` 仅为显式兼容模式，不默认选中。加密模式必须独立提供 key、整数保留期限、`--confirm-encrypted-output`，并保留原 fingerprint、输入使用和目标 host 确认。两模式互斥；离线 preflight 不读取 key、不创建输出、不发送。保留期必须覆盖冻结 run duration。

## 2. 密钥和文件系统 / Keys and filesystem

密钥必须是 operator 预置的 **44 个 ASCII bytes、canonical URL-safe base64、32-byte Fernet key**，无 BOM、空白或换行。不复用 App 请求 key，不生成或猜测 key，不保存明文/key hash，repr 和 stdout 不输出 key/path。生产密钥、真实输出及原始材料不得进 Git 或模型上下文。

读取只接受有界 regular 文件，拒绝末级 symlink、hardlink 和额外 bytes。POSIX 校验当前用户及无 group/other 权限；新目录/文件为 0700/0600。使用 descriptor、NOFOLLOW/NONBLOCK（系统支持时）和不等待的文件锁。父目录、本用户、主机、ACL、文件系统和时钟必须可信；不是恶意同用户或 hostile filesystem 的安全沙箱。Windows 分支不声称 POSIX 权限或 race-free reparse 防护；Linux 验证不等于 Windows 验收。

## 3. 认证流 / Authenticated stream

固定文件为 `observations.encrypted.jsonl`。首行 `local-qa-encrypted-output.v1` 包含技术 binding 和 token；后续每行一个 Fernet token。认证 record `local-qa-protected-record.v1` 绑定 run ID、manifest fingerprint、创建/到期/保留期、ALL input/request counts、预算、连续 sequence、前一个 **ciphertext** SHA256、kind 与 payload。

完整验证 header、全部 attempt、final 和末尾；允许并发完成顺序，但 ordinal 唯一、sample index 按冻结输入循环，response reservation 是 max+1 的整数倍，完整 collected 必须覆盖 ALL 请求。错 key、错 ID/hash、删行、调序、拼接、篡改、缺 final、未来创建时间或超限一律拒绝。Fernet 证明持有 key 下的完整性，不证明平台来源；保留期是应用 gate，不是密码学撤销。

写入持有独占 descriptor，逐 record fsync，不重试。任何不确定 write/fsync 使 store 永久失败；不覆盖、修复、续跑或重发。加密与文件 I/O 在线程中执行，并复用现有重复取消排空逻辑；关闭 journal/output 前排空工作。journal 技术 collected 不代替输出完整性验证。

## 4. 显式操作 / Explicit operations

以下为占位参数，不产生授权。使用独立安装的 Python 3.12 venv；不要把真实输入/key 放进命令记录、源码或截图。

```sh
python -I -m devpilot.local_qa_cli --manifest MANIFEST --values VALUES --inputs INPUTS

python -I -m devpilot.local_qa_cli --manifest MANIFEST --values VALUES --inputs INPUTS \
  --execute --results NEW_PRIVATE_RESULTS --allow-host AUTHORIZED_HOST \
  --confirm-send VIEWED_MANIFEST_FINGERPRINT --confirm-input-use \
  --output-key-file OPERATOR_KEY_FILE --output-retention-seconds 86400 \
  --confirm-encrypted-output

python -I -m devpilot.local_qa_output inspect --directory ORIGINAL_RESULTS \
  --run-id ORIGINAL_RUN_UUID --manifest-fingerprint ORIGINAL_MANIFEST_HASH \
  --key-file OPERATOR_KEY_FILE

python -I -m devpilot.local_qa_output open --directory ORIGINAL_RESULTS \
  --run-id ORIGINAL_RUN_UUID --manifest-fingerprint ORIGINAL_MANIFEST_HASH \
  --key-file OPERATOR_KEY_FILE --destination NEW_PRIVATE_OPEN_DIRECTORY \
  --confirm-sensitive-open
```

`inspect` 认证完整 stream 后仅返回技术 metadata、ciphertext hash、ALL counts、final/expiry，不输出 Q/A。`open` 先认证全部记录，然后在 **同一个持锁 descriptor** 上第二遍读取，写入全新私有目录的 literal `observations.jsonl`；重新核对 hash、文件状态和期限，不渲染 Markdown/HTML。未知 I/O 可留下敏感 partial 文件，不覆盖或自动清理。明文副本 **不受源文件保留期管理**，需要独立受控处置。

## 5. 保留和清理 / Retention and cleanup

允许整数期限 **300..2,592,000 秒**。到期后拒绝 `open`；持 key 仍可认证过期文件的技术 metadata。没有后台 daemon、key 销毁或 secure-erasure 保证。源文件仍存在不代表可以打开，key 丢失也不自动允许删除。

仅完整认证且已到期的输出可由 operator 确认原 ciphertext SHA256 后清理：

```sh
python -I -m devpilot.local_qa_output purge-expired --directory ORIGINAL_RESULTS \
  --run-id ORIGINAL_RUN_UUID --manifest-fingerprint ORIGINAL_MANIFEST_HASH \
  --key-file OPERATOR_KEY_FILE --confirm-ciphertext-sha256 VIEWED_CIPHERTEXT_SHA256

python -I -m devpilot.local_qa_output reconcile-purge --directory ORIGINAL_RESULTS \
  --run-id ORIGINAL_RUN_UUID --manifest-fingerprint ORIGINAL_MANIFEST_HASH
```

顺序为独占锁验证 → 独占写/fsync `output-purge-request.json` → 再核文件 identity → **一次精确 unlink** → directory fsync → 独占完成 receipt。无递归或 glob，不删 journal、身份 receipt、key、明文副本或其他文件。不确定删除仅对原 ID 只读对账，不能再写 intent、再删或修复。`reconcile-purge` 不需要 key，仅检查静态 receipt 与存在性；absent 不证明 secure erasure。

`devpilot.local_qa_retention` 现在提供一个独立的 receipt-first 基础模块：它在输出文件出现前持久化冻结身份，检查只返回未认证技术 metadata，到期后要求原 ID、receipt hash、ciphertext hash 和单独同意，并对 unlink/fsync/完成回执不确定结果提供同 ID 只读对账。它不读取或认证半写内容，不修复、不续跑、不重发，也不声明安全擦除。

该基础 API 只接受新目录和实际 `LocalRunManifest`；receipt/inspection 保留 ALL input/request counts、concurrency、timeout、duration 和三个字节预算。它使用已有锁文件的非等待锁；只读检查/对账绝不创建丢失的锁或 receipt。读取前拒绝 symlink、hardlink、FIFO 和超限文件，并核对同 descriptor/path identity。清理在两个有界 hash pass、durable intent、身份/时钟重检及一次 unlink 全程持有同一输出 descriptor 的独占锁；intent 短写、fsync、close 或目录同步不确定时保留状态，不能以新 disposal ID 重试。

receipt 是可信本地文件系统上的**未认证声明**，hash 不是签名或平台来源证明；一致伪造无法据此认证。该无 key API 不区分完整、半写或损坏 ciphertext，`content_status=not_inspected` 不证明输出未完成；明确同意只授权清理指定原文件，不授权内容访问。旧结果目录不补造 receipt。原先持 key 的完整认证 `purge-expired` 入口保持独立，不能由此模块推断 Windows 删除持锁文件已经验收。

2026-11-14：`EncryptedOutputStore`（含真实 CLI）现在先创建全新目录、同步父目录、持久化 retention 锁和 receipt，再创建 ciphertext；receipt 与认证 header 使用同一原 ID、创建时间和到期时间。运行期间持有同一 retention 独占 lease，输出 descriptor 关闭后才释放；已有 off-loop/drain 路径在重复取消后排空创建、加密和 journal 工作。回执短写、fsync、close 或目录同步不确定时不创建输出、journal 或派发，不修复或重试。输出 open/header/sync 失败保留可只读检查的原 receipt；真实子进程在 receipt、header 和首 attempt 后硬退出也只授予原 ID 检查，不授予续跑。保留期不从重启或首次检查重新计算。

该接入仅创建身份记录并排除活跃 writer 的处置，不自动删除任何文件，也不改变 plaintext 模式。新 run 的 `--confirm-encrypted-output` 仍只确认加密写入；处置必须另行确认原 ID/hash 和 `confirm_incomplete_output_disposal=True`。`run-receipt.json` 仍在 journal 创建后、任何 start/reserve/DNS/send 前写入，与输出前的 retention receipt 分别建模。旧目录不补造 receipt。

2026-11-14：[显式管理命令](DevPilot_Local_QA_Retention_Commands.md)提供 `python -I -m devpilot.local_qa_retention inspect / dispose-expired / reconcile-disposal`。处置须原 run/manifest/disposal IDs、receipt/ciphertext 两个 hash 和单独同意；没有默认操作、latest、自动 ID、key/时间覆盖、repair/resume 或后台删除。未知结果包括 stdout 丢失，只对原 disposal ID 只读核对，不重跑处置或换 ID。

**仍未完成：** 明文副本及更广泛崩溃产物治理、Windows 实际安装/持锁删除验收。备份、文件系统快照、SSD、swap/进程内存及已打开明文副本均不在安全擦除证明范围内。

## 6. 锁定软件分发 / Locked distribution

`cryptography` 现在是 devpilot 直接依赖，使用 backend 已锁定的 50.0.0 与 cffi 2.0.0/pycparser 3.0，无新解析升级。runtime 闭包为 **12**，allowlisted first-party sources 为 **37**（包括 retention 基础模块）；六项 hash-locked build tools 不变。native crypto 使新档案使用 **`local-qa-distribution.v2`** 和显式 platform；旧 pure-wheel v1 档案不改写，不冒充 native 兼容。

CPython 3.12 的 Linux glibc x86_64/aarch64、Windows amd64、macOS arm64 有明确 wheel profile；未知平台、PyPy、缺 wheel、marker/闭包漂移 fail closed，不取任意 wheel 或源码 fallback。profile 静态校验不等于各系统实际安装验收。原始官方 URL/hash/size、first-party metadata/RECORD 与全体源码逐 bytes 验证保持；不重打依赖包或绕过依赖安装。archive hash 是 integrity，不是 provenance 或授权。

## 7. 验证和剩余工作 / Verification and remaining work

专项测试使用实际 shared collector/run/journal；合成 DNS 和 MockTransport，真实 socket 发送 fail closed。覆盖分离同意、全分母、发前 receipt、篡改/错 key/错 ID、权限、锁、到期、未知写入/删除和重复取消排空。分发验证从六个锁定 build wheels 建全新环境，真实 sdist → wheel → v2 archive → 新 no-system-site venv 的 12 依赖完整离线安装，执行实际 installed plaintext/encrypted CLI 与受控打开/清理，并证明缺失/篡改依赖拒绝、同输入两次产物一致。普通 pytest 的 installed-export skip 不能替代实际带 artifact 的验收。最终全量和精确 SHA CI 收据另行记录。

### English summary

Explicit operator-key Fernet output reuses the one shared local execution chain. Separate consent, ALL frozen denominators, immutable v1 identities, bounded authenticated header/attempt/final chains, no-wait locks, fsync and repeated-cancellation draining are mandatory. No default key, implicit plaintext, retry, resume, resend, platform provenance or approval is added. Sensitive opening authenticates the complete stream before creating a new private literal copy and retains the same source lock across both passes. Expiry is an application read gate, not cryptographic revocation; copies and incomplete/crashed outputs still require separately authorized retention governance.

Expired, completely authenticated source files require original ID/hash confirmation and an exclusive intent-before-one-unlink sequence. Unknown deletion only reconciles the same IDs read-only; absence is not secure erasure. Encrypted runtime/CLI output creates its separate content-unverified retention receipt before ciphertext and holds its lease through close; explicit management commands require original IDs, two hashes and separate disposal consent. The platform-qualified v2 software archive contains 12 original hash-locked runtime wheels and 37 first-party sources; six build tools remain separate. Only actual tested platforms may claim installation acceptance. No deployment, real model/target call, business-data import or formal approval is implied.

## 本轮验证 / Verification (2026-11-11)

- 后端标准 `make test`：**13,394 passed / 19 skipped / 11 deselected / 40 warnings**（1310.96s）；同时运行纯领域 **15 / 58 passed**。专项 protected output + distribution **121 passed**（16.73s），Blocking IO **72 passed**（5.90s）。Ruff check 和完整 format check **1,282 files** 通过，两份 offline lock check 通过。
- 前端完整 **158 files / 1,360 passed**（14.6s），其中文件/hash 同步专项 **20 passed**。首轮完整回归曾有 **1 failed / 1,358 passed**：真实文件/hash Promise 的展示断言未完成；原失败和调用真实 WebCrypto 的诊断日志保留。测试改为在 React act 内显式排空真实读取/hash Promise、核对两份原始 hash，并追加任一文件未完成时禁止 inspection 的回归；没有替换 hash、放宽断言、提高 timeout 或改业务逻辑。
- 最终输入已完成新鲜 hash-locked build → sdist → wheel → 全依赖 offline install；实际已安装 plaintext/encrypted CLI 各 5 次 mock attempts、受控打开/到期删除/原 ID 对账、缺失/篡改依赖拒绝通过。API-export-installed **2 passed**（9.75s）。两次同输入 archive byte-identical，SHA256 为 `9d70a60db1fe5470e48021202f6a4960fcc1f6884463626f662d54341dba7008`；声明 source revision 是基线，不是 dirty 工作区的来源认证。ESLint/typecheck 和整个 frontend Prettier 通过；源码/证据核对、资源收尾及新提交精确 SHA 的远端 CI 仍独立核验。未重跑生产 frontend build/browser/performance，不冒用旧结果。

English: Final backend and frontend regressions passed after explicitly draining real file/hash promises in the test, without retries or weaker assertions. Original failures remain evidence. Final packaging/format/source/resource and exact-commit CI gates are separate; no deployment or real calls.
