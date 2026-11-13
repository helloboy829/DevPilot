# 独立本地 QA 锁定软件分发 / Hash-locked local QA software distribution

## 2026-11-11 接续：native-qualified v2

[加密输出模块](DevPilot_Local_QA_Protected_Output.md)使 cryptography 成为 devpilot 直接依赖，复用已锁定的 cryptography/cffi/pycparser，闭包从九项增加到 **12**，第一方源码 **37** 项。新 `local-qa-distribution.v2` 明确 CPython 3.12 native platform；支持 profile 静态校验不等于该平台实际安装验收。旧 v1/35-member/pure-wheel 验证记录保留为历史，不改写原档案或以其证明 v2。六项 build-lock 工具不变。

English: v2 pins native crypto wheels and the full 12-package closure. Both exact wheel bytes and fresh no-system-site offline installs are required; declared archive hashes do not establish provenance, data-export consent or execution authority. Legacy plaintext remains separately explicit.

日期 / Date：2026-11-10。状态 / Status：候选代码，未部署。

## 1. 解决的缺口 / Scope

此前实际 wheel/CLI 验证依赖后端已安装的 HTTPX 环境，只证明代码可以独立导入，**不能证明新环境能够完整安装**。本模块补齐独立软件的依赖锁定、完整第一方成员核验和真实新 venv 安装，不提供平台数据导出权限或第二套 runner。

- `scripts/build_local_qa_distribution.py`：标准库、显式输入、无网络的构建器，仅支持 Python **3.12**。
- `devpilot/distribution/source-members.txt`：完整公开包成员 allowlist，目前 **37** 项，包含旧 toolkit/evaluation/reporting 与 local QA retention，而不只核验 QA 的入口/核心。测试检查清单覆盖整个源码包。新成员必须显式审阅更新，untracked/额外 wheel 成员不自动入包。
- 运行依赖取自已有 `backend/uv.lock`：HTTPX/HTTPCore/h11/certifi/AnyIO/idna/typing-extensions/openpyxl/et-xmlfile，共九项。版本、原始 wheel SHA256、大小、官方 URL 和 Python 3.12 的依赖/marker 图必须一致；不调用 resolver 升级、增加 runtime 依赖或重打包第三方 wheel。
- 第一方 wheel 来自显式选定的可信源；全部源码逐 bytes 一致，METADATA/WHEEL/RECORD 逐项检查，拒绝额外模块、entry_points、`.pth`、路径逃逸、重复/大小写冲突和非 regular 成员。
- 六项构建工具另由 `build-requirements.lock` 固定版本及官方原始 wheel hash；只用于新建构建 venv，不放入运行软件包，也不改变后端/runtime 依赖。Python 3.12 不需要条件构建依赖 tomli。

**This is a software-only distribution, not a platform-authorized exporter, signed release, provenance attestation, execution authority or approval.** Bare project dependencies remain as before; reproducible distribution installation uses the emitted hash-locked requirements, not an unpinned `pip install devpilot`.

## 2. 文件与来源合同 / Contents and trust

生成 `local-qa-distribution.v1` ZIP，固定 17 个成员：十个 wheel、`requirements.lock`、仓库 MIT `LICENSE`、双语 README、三个完全合成的示例，以及 `distribution.json`。完整第三方 wheel 保留各自许可，不提取、剥离或伪造等价 archive hash。示例只有 example.test、SYNTHETIC 输入/占位凭据，没有客户材料、真实目标、配置、gold、评审或数据库。

Manifest 包含明确的 `software_only_not_platform_export`、Python/package 版本、声明的 source revision、完整 source member hashes、后端锁文件 hash、原始依赖元数据及其他全部文件的 hash/大小。下列字段固定 false：

- `source_revision_authenticated`
- `platform_provenance_verified`
- `execution_authorized`

**声明 revision/hash 并不证明当前源码属于该 commit，也不是签名。** 源码和 wheel 的完整 bytes 一致可核验；commit 来源/发布者身份必须通过独立可信流程确认。攻击者可以同时替换 ZIP 和内置 manifest，因此收件方必须通过单独可信渠道取得整个 archive 的 SHA256，在解压/安装前独立核对。内部 hash 不能作为自己的信任根。

构建器只读固定软件路径、显式 wheel 与专用 wheelhouse；wheelhouse 必须恰好九个原始文件，额外/缺失/变更/目录/symlink 失败。父目录、文件系统和选定 source 必须可信；不是恶意父目录/文件竞态或任意恶意 archive 的隔离执行服务。无配置/环境凭据 fallback、App/数据库读取、平台导出按钮或网络下载。

## 3. 显式构建与安装 / Explicit operations

在可信仓库与 Python 3.12 下，明确准备九个官方原始 wheel、用 hash-locked 构建工具从选定源码构建的第一方 wheel，然后运行：

```sh
python3.12 -I scripts/build_local_qa_distribution.py --describe-dependencies
python3.12 -I scripts/build_local_qa_distribution.py --dependency-lock
python3.12 -I scripts/build_local_qa_distribution.py --wheelhouse EXPLICIT_NINE_WHEEL_DIRECTORY --wheel EXPLICIT_BUILT_WHEEL --output NEW_DISTRIBUTION.zip --source-revision EXPLICIT_40_HEX_SOURCE_REVISION
```

前两条仅输出公开锁元数据/requirements，不下载。任何下载由操作者另外显式执行；保持正常 TLS 与原始 hash，不能复制旧机器 venv、重打包缓存目录冒充官方 wheel，或在构建器内自动取网。

所有校验先于输出创建；输出使用 exclusive create，固定 ZIP 时间/权限、排序成员。同输入及相同压缩运行时可重复生成相同 bytes，不承诺不同 zlib/Python 版本压缩 bytes 一致。flush/fsync/close 完成才返回 archive hash；写入不确定时保留 partial file，不替换、修复、删除或自动重试。没有跨平台父目录 fsync/断电持久性保证。

可信 hash 核对、解压到新目录后，README 要求新建**无 system-site-packages** 的 Python 3.12 venv：

```sh
python3.12 -m venv .venv
.venv/bin/python -I -m pip --isolated install --no-index --find-links wheels --require-hashes --only-binary=:all: -r requirements.lock
.venv/bin/python -I -m pip --isolated check
.venv/bin/python -I -m devpilot.local_qa_cli --manifest examples/manifest.json --values examples/values.json --inputs examples/inputs.json
```

Windows 需显式选择 Python 3.12，以 `.venv/Scripts/python.exe` 替代 POSIX 路径；不需要激活脚本或更改执行策略。当前真实验收为 Linux，**不宣称 Windows/其他 OS 或 Python 3.13+ 已验收**。不使用 `--no-deps` 隐藏依赖缺口；不设置 system-site-packages 或 editable/source sys.path 兜底。

末条仍为默认 OFFLINE preflight，合成目标不可当成真实执行授权。本包没有实发快捷脚本；真实数据/目标/host policy/私有明文输出都须另行授权和显式同意。

## 4. 运行与结果边界 / Execution and result boundaries

不改变共享 collector/run/transport/journal，也不自动执行。既有合同继续适用：dispatch-before-wire、ALL 冻结分母、原 deadline/预算、无重试/重发/恢复；发送前原 ID receipt 与未知后显式 same-ID 只读对账。缺失 receipt 不是未发送证明，collected 不证明最终输出 fsync 或目标交付成功。

结果仍是**本地私有明文**，`external_unverified_technical_only` / `NOT_EVALUATED`，不是平台加密证据或独立验收。输出加密/保留/删除策略、平台来源/数据 tiers 授权 exporter、外部结果隔离导入仍未完成；不得把软件 manifest/hash 替代这些合同。

The independently checked entry points are the local QA commands and their declared runtime closure. Bundling the whole existing first-party package does not establish that legacy evaluation or Harness-integration entry points work independently.

No migration, App route, runtime configuration, deployment, execution enablement, real model or real target call is added. Candidate head remains eval_0012; the old eval_0009 deployment receipt is historical, not this machine's runtime acceptance.

## 5. 验证 / Verification

`backend/tests/test_local_qa_distribution.py` 覆盖真实锁闭包、全源码清单、所有第一方成员/元数据/RECORD、专用 wheelhouse、格式/路径/重复/非 regular/尺寸约束、独占输出/fsync 不确定、通用错误、默认离线示例，以及验收器在错误 hash/成员/路径/旧目录时不得调用安装器。

`scripts/check_local_qa_distribution.py` 是显式 **CI 测试工具**，不是用户自动安装器或不可信文件服务：校验外部 archive hash/全部文件 hash 后，创建新私有目录和新 venv；实际证明缺依赖与篡改 wheel 被 pip 拒绝，再从恢复的可信测试 bytes 完整离线安装，运行 pip check。它检查全部十一项包/命令 import origin 位于新 venv，然后由真实安装的模块默认预检、5 次 mock wire（每次先查真实 dispatch/原 ID receipt）、同 ID reconcile。真实 DNS/socket send 与业务 imports 被禁止，保留 ALL 两输入/五请求、NOT_EVALUATED/no-resend。

Unit Tests workflow 新增独立 `local-qa-distribution` job：从六项 hash-locked 构建工具的新 venv 构建真实 sdist→wheel，显式下载九个 hash-locked runtime wheel，再构建并离线验收。CI 中下载只是公开软件获取，不是目标调用。具体源码/证据、完整回归、资源停止、提交 SHA 和实际 Actions 以每次交付收据分别闭环；push 不是 CI 成功。

本地新增/联合/full/Blocking/lint/完整 frontend Prettier 与单测继续按模块门禁执行。没有借用旧机器的部署证据，也没有将 Linux 验证替代浏览器、生产真实用户、性能或 Windows 验收。

### Module-local results

Final module-local gates: new **61 passed / 9.85s**, joint **873 passed / 152.69s**; standard backend **13,069 passed / 18 skipped / 11 deselected / 40 warnings / 753.49s**, domain **15 / 58 passed**, Blocking IO **72 passed / 5.56s**, Ruff **1,262 files** and offline lock passed. Frontend runtime source is unchanged: full **152 files / 1,293 passed / 12.5s** and entire Prettier passed; final module documentation is checked separately. A fresh six-tool hash-locked build venv produced real sdist/wheel; a fresh nine-dependency offline runtime venv passed default-offline, five mock sends, every pre-dispatch receipt and original-ID reconciliation. Missing/tampered wheels were rejected and two same-input archives were byte-identical. Final archive SHA256: `2dd2964219f5ed8b1186b1a6fd2ded4921f81566b212045c011f9c7d0e27f21e` (declared baseline revision, not this commit's authenticated provenance). Intermediate and fixture/static-check diagnostics are retained; no retry, weaker assertion or longer timeout hides failures.

No local browser, frontend build/lint/typecheck, performance, Windows or real-user acceptance was rerun, and previous module results are not borrowed. The new commit's Actions run their existing gates independently. Public source/evidence hashes, exact resource shutdown, commit/push and exact-SHA Actions have separate module receipts; local success and push are not CI success.
