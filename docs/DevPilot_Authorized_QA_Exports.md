# Authorized QA configuration exports / 平台授权 QA 配置导出

> 后续工作台切片 / Subsequent workspace slice: [explicit policy, source, same-ID recovery and ZIP download](DevPilot_Authorized_QA_Export_Workspace.md). The original no-UI scope below describes this backend slice only.

> 2026-11-10. Candidate backend/API; default disabled and undeployed. No UI,
> target/model calls, execution enablement, result import or formal approval.

## Scope / 范围

`app.evaluation.authorized_exports` creates an immutable configuration ZIP from
an explicitly selected frozen plan, using the **existing** local CLI manifest
and shared execution core. It does not introduce another runner, change manifest
v1, decrypt stored request values, execute requests or package App/Harness code.
The separate [software-only distribution](DevPilot_Local_QA_Distribution.md)
remains required.

中文摘要：新增人类 owner 专属授权导出 API、加密不可变档案及访问审计。
仅支持无输入骨架和额外获准的 baseline 输入；没有验收集输入、金标、历史输出、
凭据或完整请求导出。输入齐备不代表请求值已绑定，更不是执行许可或正式批准。

## Operator policy and consent / 策略与同意

Startup strictly validates the App-owned `evaluation_exports` extra configuration
and copies it into the repository. Changes require a restart; there is no grant
administration API or dynamic enablement. The safe default is:

```yaml
evaluation_exports:
  enabled: false
  software_archive_sha256: null
  grants: []
```

Enabling requires a trusted software archive SHA-256 and at least one unique
exact grant (maximum 200). This module does not modify production configuration
or generate encryption keys. The archive hash needs a trusted channel; a package
claiming its own hash/revision is not authenticated provenance or a signature.

Each grant binds a 32-lowercase-hex ID, exact owner/project/plan IDs and plan
hash, canonical recipient account UUID, exact `skeleton` or `baseline_inputs`
tier, canonical request origin, literal-true `off_platform_authorized` and an
absolute expiry in epoch milliseconds. Missing/expired/revoked grants block
creation and download. The recipient is a declared manual handoff destination,
not a new project member or an authenticated delivery channel. Only the owner
uses these routes; there is no account directory or recipient delivery API.

The owner separately submits literal-true `confirmed`, `data_use_confirmed` and
`external_controls_acknowledged`. Missing, numeric or string booleans fail. This
is data-export consent, not execution admission or approval. Modified offline
software cannot be continually controlled: destination, load, output protection
and retention remain external responsibilities. Restricted targets without
explicit off-platform authorization must not receive a grant.

Policy limits default to 65,536 bytes per response (maximum 1,048,576) and
67,108,864 total response reservation bytes. ALL frozen request/body/time and
concurrency budgets must fit the existing CLI; no subset or silently reduced
budget is substituted to make an incompatible plan look runnable.

## Tiers and package / 分级与包结构

| Tier              | Included                                                          | Excluded / incomplete                                                                      |
| ----------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `skeleton`        | Value-free wiring, frozen bindings/budgets, explicit empty inputs | Does not SELECT sample/reference tables; authorized inputs must be supplied                |
| `baseline_inputs` | ALL verified frozen baseline input strings, sample-ID order       | No acceptance inputs, reference answers, source references, slice tags or historic outputs |

Both tiers retain method, canonical origin and header names. ALL URL/path/query,
header and body **values** must be rebound, including credentials. Neither tier
selects or decrypts stored request ciphertext. A complete baseline input set
still has `ready_for_preflight=false`; empty example bindings are not a usable
request. Skeleton READMEs explicitly say evaluation cannot yet be completed.
No request values are borrowed from the environment or platform.

Creation verifies plan hash, linked component, request/template fingerprints,
dataset revision/hash/purpose/count and ALL input integrity. Baseline validation
internally reads the existing gold-bound source to verify its dataset hash;
reference answers never enter ZIP/receipt/audit. Skeleton reads neither sensitive
table. Malformed templates produce private conflicts, not parser exceptions.
Unsupported HTTP, performance mode, counts and budgets fail closed.

The ZIP has exactly six fixed-time ZIP_STORED regular 0600 members, no executable
scripts, software dependencies, machine paths or extra files:

```text
export.json
manifest.json
values.example.json
inputs.json
README.zh.md
README.en.md
```

`export.json` fixes source IDs/revisions/hashes, grant, policy, exporter version,
software pin, existing manifest fingerprint and member hashes. Hashes are
integrity declarations, not source attestation. Scope remains execute-only,
`NOT_EVALUATED`, without criteria evaluation, execution authority or approval.
The v2 criteria remain bound through the source plan hash; the local command
does not evaluate them or claim an equivalent quality verdict.

Bounds in bytes: streamed PUT 16,384 before buffering; manifest 32,768; values
524,288; inputs 4,194,304; ZIP 5,242,880. The encrypted token is bounded to
15,000,000 ASCII characters. Bound failures release no partial archive. ZIP
metadata cannot enforce extracted filesystem permissions: private extraction,
manual transfer and recipient storage require separate controls.

## API and permissions / API 与权限

Base: `/api/evaluation/projects/{project_id}/exports/{export_id}`. Export IDs are
32 lowercase hex. Existing authentication, owner scope and human-only checks
apply to all routes; internal Agents are rejected. Permissions do not replace
operator grants or data-use consent.

| Method / suffix | Additional permissions beyond project read          | Contract                                                                       |
| --------------- | --------------------------------------------------- | ------------------------------------------------------------------------------ |
| `PUT`           | Project write + review; `evaluation_exports:create` | Exact source/grant/recipient/tier and three confirmations; create once         |
| `GET`           | `evaluation_exports:read`                           | Immutable metadata, no ciphertext/input read                                   |
| `GET /bundle`   | Project review; `evaluation_exports:download`       | Exact `viewed_receipt_hash` and `confirm_download=true`; current authorization |
| `GET /audit`    | `evaluation_exports:read`                           | Explicit `after_sequence` (default 0) and limit 1–200 (default 100)            |

Audit returns `{events, next_after_sequence}`. Positive sequence is monotonic
per export, not timestamp/UUID order. A full page gives its final sequence as the
next cursor; the next page may be empty. Events contain actor/action/export ID,
sequence and time, never inputs, answers, credentials or ciphertext. No polling.

Receipts bind source IDs/hashes/revisions, grant, policy/software pins, ciphertext
hash, byte length and time. No plaintext input/ZIP hash is public. Private
no-store applies to responses/errors; submitted private values are never echoed.
Missing IDs/sources return 404; duplicate/changed sources 409; unavailable policy,
key, DB or uncertain writes generic 503; oversized bodies 413; invalid fields 422.

Failed/unknown PUTs reconcile **only by GET of the same export ID**, even after 404. No resend, automatic new ID or replacement export. Duplicate PUT always
conflicts, not a second write. Historic metadata/audit remain readable disabled,
expired or without a key. Download requires the exact current grant, policy and
software pin, decrypts the stored historic bytes, then rechecks under project
lock and commits audit before returning bytes. Current source edits never rebuild
an old ZIP. Audit failure releases no body.

## Storage, locking and cancellation / 存储与生命周期

Additive App migration `eval_0013` adds only two tables and two indexes:

- `evaluation_authorized_exports`: owner/project/plan binding, immutable document,
  request/receipt hashes, ciphertext and time; same-project plan foreign key.
- `evaluation_export_audit`: same-project export foreign key, bounded action,
  positive time/sequence, unique `(export_id, sequence)`.

Old App revisions, Harness ledger and existing source tables remain unchanged.
Candidate head is `eval_0013`; historic eval_0009 deployment receipts are not this
machine's runtime. Test downgrades use owned synthetic databases: operational
rollback must not drop new archives/audits. A separate backed-up upgrade/rollback
plan must preserve accounts, configuration, data and mounts.

The ZIP is encrypted in a domain-separated `protected-platform-qa-export.v1`
Fernet envelope using explicit `DEVPILOT_REQUEST_ENCRYPTION_KEY`, no fallback or
generation. Binding includes owner/project/export/plan/grant hash. Wrong context,
domain/key, tampered receipt/ciphertext and non-ASCII tokens fail generically.
Decrypted JSON failures are not retained in exception context. Crypto, source
verification, ZIP work and large hashes run off-loop.

Creation reads a bounded snapshot, closes its session, builds/encrypts off-loop,
then locks the project row, rereads the full snapshot and exact unexpired grant,
and commits archive/audit atomically. Mutation, expiry and concurrent same-ID
creation are fenced. All repository operations shield and drain DB **reads as
well as writes** and off-loop work across repeated cancellation, then preserve
cancellation. Unknown commit results never grant retry authority. Project locks
serialize audit sequence; no timeout increase hides stranded pooled locks.

## Verification / 验证

Synthetic users, data, credentials, grants and keys only; real DNS/socket sends
fail closed. Actual shared/local CLI uses fake pinned wire, not real targets.

- `test_authorized_qa_exports.py`: permissions, private validation, tiers, full
  source/budgets, races, mutations, expiry, immutable history, audit rollback and
  pagination, repeated-cancellation reads/writes, corruption and streaming bounds.
- `test_authorized_qa_exports_migrations.py`: API-seeded SQLite with foreign keys
  ON and an explicitly owned temporary PostgreSQL database; previous-table
  snapshots, upgrade/downgrade, constraints, index/metadata parity, export/download.
- `test_authorized_qa_exports_installed.py`: explicit software archive/hash and
  actual API configuration, fresh no-system-site venv, full offline dependency
  install, actual installed `-I` origins within the venv. App/Harness/business
  imports and real sockets fail closed. Real CLI preflight, one mock send after
  durable receipt/journal, then read-only original-ID reconciliation.

The trusted source checker is invoked normally to import its reviewed sibling
helper; actual installed runtime remains `-I`, without checkout fallback. No
archive means the optional integration skips, **not passes**. A separate CI job
consumes the independently built/tested software-only artifact plus hash, installs
backend verifier dependencies separately, and explicitly runs the installed gate.
The original pure distribution job still cannot use backend `uv sync` or no-deps
fallback. Static regressions enforce this separation. Locally the retained
software-only archive was independently rehashed before a fresh offline install;
no venv/database/private configuration was copied from another computer.

Focused gates initially passed 67 tests; a joint regression then rejected mixing
backend verification dependencies into the independent distribution job. The
workflow was separated without weakening that assertion. Final focused/full,
source/evidence/resource checks and new exact-SHA Actions are separately recorded;
no older green SHA establishes this module passing.

## Final local gate results / 最终本地门禁

Final module-local verification: focused **88 passed / 1 warning** (including
actual fresh offline installed CLI and SQLite/owned PostgreSQL migrations), joint
**397 passed / 1 warning**; standard backend **13,254 passed / 19 skipped /
11 deselected / 40 warnings / 841.65s**, domain **15 / 58 passed**,
Blocking IO **72 passed**, Ruff **1,270 files** and offline lock passed.
Frontend runtime source is unchanged: full **152 files / 1,293 passed**, entire
frontend Prettier, ESLint and TypeScript passed in this module. No local build,
browser/Windows/real-user acceptance, deployment or real calls are claimed.

The first full run retained **5 failed / 13,242 passed**: its independent exact
permission inventories lacked the three new export actions. Explicit inventories
and ordered provider requests were extended, with six action/failure-mode cases;
no wildcard assertion, authorization policy change or failure suppression.
A separate red regression exposed expiry between grant checking and receipt time;
creation now fails privately without an archive/audit. Template-corruption and
pure-distribution isolation failures also remain in the retained diagnostics.
The second full run passed, but its following format check found a stale
container copy of `deps.py`; that file was synchronized and the exact final
source was fully retested. No source mismatch is waived by a green test count.
Successful local gates do not prove push or CI: final source/evidence/resource
receipts and the new exact-SHA Actions, including the separate installed-export
job, require independent verification. The whole platform remains incomplete.

## Exclusions and next gates / 排除项与后续

No capabilities/export UI, authenticated recipient transfer, acceptance/gold/judge
tier, performance/streaming exporter, signed provenance, local output encryption
or retention, quarantined upload/import, platform-run replacement, approval,
frozen QA scheduling or lost-Worker recovery. Recipient request values and
execution consent remain separate. Modified offline software cannot be remotely
enforced. Real-target authorization/equivalence, current-machine/browser/user
acceptance, keys and a backed-up deployment require separate authorization.
