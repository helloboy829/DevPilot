# 显式本地 QA 命令 / Explicit local QA command

## 2026-11-11 接续 / Protected output follow-up

[本地输出保护](DevPilot_Local_QA_Protected_Output.md)增加独立 key、分离加密同意和保留期；旧 `--confirm-plaintext-output` 只显式兼容，默认 preflight 不打开 key。加密命令仍走同一 shared run/journal/collector/pinned transport，没有重试、续跑或平台证据授权。以下 plaintext 说明保留其原历史模式边界，不代表新默认。

English: Explicit operator-key encryption is now available as a separately consented mode; legacy plaintext is opt-in only. Expiry/open/one-shot deletion are described in the linked contract, not a new runner or approval.

2026-11-14：加密输出在创建 ciphertext 前持久化 `retention-receipt.json`，与认证 header 使用同一原 ID、创建/到期时间和冻结预算；从创建到关闭持有 retention 独占锁。原 `_drained_database` 负责重复取消排空；回执不确定则无输出、journal 或派发，硬退出保留原身份供显式检查。无 key 检查不认证内容；到期处置单独同意，管理命令和明文副本治理仍未完成。详见[保护与保留合同](DevPilot_Local_QA_Protected_Output.md)。

> 2026-11-10。独立 execute-only 候选；默认离线，结果外部未核验。不是平台授权 exporter、正式批准或完整依赖发行包。历史部署收据不是本机运行验收。

## 1. 范围与依赖方向

新增 `devpilot.local_qa_cli`，以 `python -m devpilot.local_qa_cli` 提供实际命令入口，复用现有 `run_local_json_attempts → run_json_attempts → collect_json_attempt → PinnedHTTPTransport`；不生成另一套 runner。持久化仍使用[one-shot journal](DevPilot_Local_QA_Run_Journal.md)，平台 App 的授权、全局预算、加密证据、真实 Worker、迁移与 APIs 均不改。

使用当前锁定环境中的 HTTPX 和 Python 3.12；本模块没有新增依赖或锁文件改变。源码/wheel 可在无 App/Harness/business imports 的隔离解释器运行，**不等于无 site packages/零依赖**。运行者必须自行提供可信环境、目标调用许可、输入使用许可和私有结果目录。当前没有平台授权 manifest 生成/下载、依赖 lock 打包、目标数据传输授权证明或 App 结果导入入口。

## 2. 三个独立显式文件

| 文件     | 固定 schema / 限制                   | 内容与边界                                                                                                                                    |
| -------- | ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| manifest | `local-qa-json-manifest.v1` / 32 KiB | execute_only、external_unverified_technical_only，结构 RequestTemplate/QAJSONBinding、输入数量与全部 run/字节限额；严格版本及结构 fingerprint |
| values   | `local-qa-values.v1` / 512 KiB       | `bindings` 精确覆盖 template 的 URL/body/header refs；不从 env、App、密钥服务或默认配置读取                                                   |
| inputs   | `local-qa-inputs.v1` / 4 MiB         | 精确 `inputs: string[]`，数量必须等于 manifest；不接受 gold、case 对象或额外字段                                                              |

仅显式 bounded regular files；拒绝末级 symlink、目录/FIFO、重复 JSON key、NaN/Infinity、无效 UTF-8、深度超过 32 或节点超过 20,000。POSIX 使用 NOFOLLOW/NONBLOCK；Windows 不声称提供 POSIX 权限或 race-free reparse 防护。父目录、运行环境及 ACL 必须可信；不是对抗恶意同用户进程/主机的沙箱。JSON 的先行解析仍受文件大小/解释器边界，不声称硬 CPU deadline。

manifest 固定 request.v1、qa-json-binding.v1、qa-json-run.v1、qa-json-attempt.v1、pinned-http.v1、local-qa-json-journal.v1。不能 silently 接受新版本。结构 fingerprint 绑定结构和限额，**不绑定敏感请求值/inputs，不是签名、平台来源或与平台原请求等价的证明**。不持久化敏感 plaintext hashes。

离线 preflight 将所有输入逐个实际 render，验证 binding、每 body ≤256 KiB、循环 ordinal 的 ALL 请求预算和每次 max_response_bytes+1 的不回收响应预留；不是只检第一个输入或成功子集。请求预算只计渲染 body 的 UTF-8 bytes，响应预算是 max+1 yielded-body 预留，不代表 headers/TLS/wire/read-ahead 流量或费用上限。冻结输入 1..500，全部至少覆盖一次；request_count 1..10,000、并发 1..64、单次 100..300,000ms、总时长 1,000..3,600,000ms 等沿用核心/本地 definition 门禁。时长是协作 deadline，不是杀死同步任务/解析线程的硬期限。

## 3. 离线合成示例 / Offline synthetic example

以下仅写合成文件和预检，不会发送。不要把客户输入、密钥、真实内部地址放入 Git/模型上下文。本例 `example.test` 是合成占位，不是授权目标。

```python
import json
from pathlib import Path
from devpilot.local_qa_cli import LocalRunManifest
from devpilot.qa_json_binding import QAJSONBinding
from devpilot.request_templates import RequestTemplate

manifest = LocalRunManifest(
    RequestTemplate("POST", "https://example.test:443", ("Authorization",)),
    QAJSONBinding("/q", "/a"),
    input_count=2,
    request_count=5,
    concurrency=1,
    timeout_ms=1000,
    duration_ms=10000,
    max_response_bytes=128,
    max_total_request_bytes=4096,
    max_total_response_bytes=645,
)
files = {
    "manifest.json": manifest.to_dict(),
    "values.json": {
        "schema": "local-qa-values.v1",
        "bindings": {
            "DEVPILOT_REQUEST_URL": "https://example.test/qa",
            "DEVPILOT_REQUEST_BODY": '{"q":""}',
            "DEVPILOT_REQUEST_HEADER_1": "Bearer SYNTHETIC_ONLY",
        },
    },
    "inputs.json": {"schema": "local-qa-inputs.v1", "inputs": ["first", "second"]},
}
for name, payload in files.items():
    Path(name).write_text(json.dumps(payload), encoding="utf-8")
```

```text
python -m devpilot.local_qa_cli --manifest manifest.json --values values.json --inputs inputs.json
```

返回仅结构 fingerprint、计数、无网络声明和 NOT_EVALUATED 等安全元数据，不回显路径、URL、headers/body/inputs。缺省不创建结果目录，不发 DNS。上例普通文件创建未设置操作系统 ACL；真实 values/inputs 应先在受控私有目录下安全创建，示例不是凭据保护工具。

## 4. 显式实发合同

在**另行取得目标与数据使用授权**、本地审查三个文件和输出目录 ACL 后，运行者才可手动传入：

- `--execute --results NEW_PRIVATE_DIRECTORY`：必须是不存在的目录；不自动修复/覆盖/恢复。
- `--allow-host EXACT_LOWERCASE_HOST`：1..32 个精确 host，无通配符、userinfo、path、port 或 scoped IP；端口由已审核 request/template 决定，HTTPS 必须，不隐式 allow-all。
- `--confirm-send MANIFEST_FINGERPRINT`：只确认结构，不证明值/来源；不是平台授权 token。
- `--confirm-input-use`：明确允许输入进入指定目标。
- `--confirm-plaintext-output`：明确接受**本地私有明文**保存，绝不宣称加密。
- 如确有单独私网许可，另外显式 `--allow-private-addresses`；仅允许 RFC1918/ULA，仍拒绝 loopback、metadata/link-local、multicast、unspecified、reserved、IPv4-mapped/scoped 地址及非允许范围。

每次发送前重新解析、检查 **ALL** DNS answers 后只交给 transport 一个 literal IP；保留原 Host/SNI，TLS verify=True。Client/transport 不读代理/证书环境，follow_redirects=False、retries=0。请求不能改变原 origin。DNS policy rejection 是明确拒绝发送，不冒充 delivery_unknown：记录后终止本地 run 的后续 ordinals；已派发并行任务仍排空。timeout/transport error 是不确定交付，也停止后续派发且绝不重发。HTTP 错误/非法输出可作为技术观测完成，均不是成功判定/PASS。单次/整个 run deadline 与不可回收字节预算保持不变。

## 5. 输出、失败、取消与核对

创建新目录 POSIX 0700、`observations.jsonl` 0600；Windows 的 mode 参数不构成 ACL 保证。必须在可信父目录/私有 ACL 下运行。输出采用一次独占打开的 descriptor，锁内单次写 + fsync；不按被替换的路径重新打开，短写/fsync 失败不补写/重试。带明文敏感输出声明的元数据行先于 journal/发送确认，只有完整创建才能开始 run；输出上限按累计响应与固定开销界定。

JSONL header/ordinal/final summary 均带 scope、run_id、NOT_EVALUATED；ordinal 只包含技术状态、计数、HTTP status、时长和敏感 extracted output，不附输入、credentials 或 gold。**目标输出本身可能回显凭据/输入或包含个人信息**，本命令不承诺 redaction/脱敏；保护目录、传递与保留期限是运行者责任。journal 不包含敏感输出/输入/请求值。

所有目录/输出/SQLite 创建、写入、读取、finish 和关闭均在线程 offload/drain 后再传播取消；重复取消不能提前释放 journal。创建期间已创建的 journal 和输出 descriptor 也必须关闭；final append 失败不改写已终结 journal。保留**原 ID/目录**只读核对，禁止 resume、recreate、清空重跑、自动 retry 或重新发送未知 ordinal；硬进程退出也不产生恢复权限。部分输出不是完整报告；journal collected 仅说明技术采集终结，final JSONL fsync 仍可能失败。文件 fsync 不是目录项/整主机断电持久性保证，亦不是真实目标交付证明。

正常技术 collected 返回码 0，预检/策略/执行/落盘拒绝或 interrupted 返回 1，Ctrl-C 返回 130；错误不输出 traceback、请求/输入/凭据/异常细节。诊断/人工调查不能把缺失输出推断为未发送，也不能自动新建 ID 重试。

## 6. 验证与未完成事项

新增合成回归覆盖 strict schema/版本/预算、无网络默认、多重同意、文件类型、ALL DNS/私网/重绑定、实际 CLI module 完整 mock sends（并发 1/2）、真实 journal commit-before-wire、Host/SNI、TLS/无 env/redirect/retry、HTTP 错误非 PASS、partial/fsync 不重试、重复取消输出排空和创建期关闭。真实 socket/DNS fail-closed；没有目标/模型实发。

首次基线缺模块的 collection failure、首次 Ruff 违规以及重绑定回归失败日志均保留。后者揭示共享 collector 将 policy rejection 记录为已知拒绝，原共享 run 仅对 delivery_unknown 停发；本地 record callback 新增记录后终止，不改 App，不将 known no-send 改成 unknown，也不隐藏失败/加超时。门禁与源码/证据/提交归档和 exact-SHA Actions 在交付收据独立核验。

未完成：平台授权来源 manifest/数据交付 tiers、完整锁定依赖工程/签名或来源真实性、输出加密与保留治理、external/unverified 结果隔离/导入、独立冻结 QA 调度、Lost Worker 对账、正式批准、另行授权升级/真实用户验收。当前不导入/发布平台 evidence，不改授权/执行开关，不部署。

## 7. 联合回归发现的同路径锁修复

首轮联合回归 **718 passed / 1 failed**：既有 journal 并发只读核对测试抛出 generic unconfirmed。原对象只共享自己的 lock，新建 read-only handle 不受 owner 串行锁保护；12 个独立诊断压力批次未复现，不作为原失败已消除的证据。补充 canonical-path 进程内弱引用 lock registry，将同路径 owner/只读 handle（包括路径别名）共同串行，保留 SQLite timeout=0、外部进程锁失败关闭、原并发断言与 idle WAL anchor；无 retry、延时或自动重发。新增锁身份/别名、持锁读不进入 SQLite、闲置 registry 不滞留三项确定性回归。进程间不会因此获得续跑/claim 权限，跨进程冲突仍只能原 ID 只读核对。

## 8. 最终本地门禁

本模块最终本地门禁：CLI 新增 **83 passed**，journal 专项 **82 passed**（含新增三项确定性锁回归），联合 **722 passed**（141.92s）；标准 `make test` **12,918 passed / 18 skipped / 11 deselected / 40 warnings**（761.90s），纯领域 **15 / 58 passed**；Blocking IO **72 passed**（5.72s）；Ruff **1,259 files**、两份领域源独立 lint/format、offline lock 全通过。前端完整 **152 files / 1,293 passed**（13.3s），完整 Prettier 与八份模块文档格式独立核验。实际 sdist→wheel 十二个公开成员逐 bytes 相等，`-I` 实际模块离线/完整 mock run 均通过，真实 DNS/socket 与 business imports 禁止。最终源码、证据、提交归档、专用资源收尾与新 SHA 的实际 Actions 另行闭环；未重跑本地 frontend build/browser/performance，无部署/执行启用/真实调用。

没有把失败日志删掉或仅采用重跑结果：DNS policy 行为经实际 callback 修复、同路径读锁通过确定性新增门禁；wheel 首次助手因测试目录非 package 导入失败，改为显式 runpy helper 后核验同一实际 wheel，源码未为助手修改。

## 9. 原 ID 只读对账入口

后续[只读对账命令](DevPilot_Local_QA_Reconciliation.md)显式接收原 journal 与 run ID，仅显示技术元数据、ALL 冻结分母和累计预算。不读取此处明文输出、不验证输出 fsync、不续跑/修复/重发，也不修改现有执行同意或 journal schema。

## 10. 发送前原 ID 回执 / Pre-dispatch identity

后续[独立身份回执](DevPilot_Local_QA_Run_Receipt.md)在新 journal 创建后、start/reserve/DNS/send 前写入 run-receipt.json；写/fsync/close 不确定则停止且不重试。异常后读取此技术文件即可取得原 ID，不需打开敏感 observations；最终 stdout 仍一个 JSON。receipt 不表示当前状态、来源或交付，缺失也不证明未发送；既有同意、输出保密边界和 no-resend 不变。
