# External QA technical metadata inspection / 外部 QA 技术元数据检查

> 2026-11-10. Candidate source-only module. No platform evidence import, API,
> persistent quarantine, migration, deployment, execution or approval.

## Scope / 范围

`app.evaluation.external_qa_metadata.inspect_local_metadata` is an App-owned,
standard-library, synchronous parser for exactly two already-existing local
technical metadata documents:

- `local-qa-run-receipt.v1`: static pre-dispatch identity only;
- `local-qa-reconciliation.v1`: an explicitly selected original-ID technical
  snapshot, not output content or authenticated platform evidence.

This is one bounded prerequisite for the external-result isolation design, not
its completion. It accepts **bytes**, never filenames, streams, SQLite databases,
ZIP archives, executable code, raw outputs, credentials or gold. There is no
HTTP/upload route, UI, database access, filesystem access, configuration lookup,
network access, decryption, audit append or platform run mutation. Nothing in
Harness or the pure `devpilot` layer imports this App module.

中文摘要：仅检查显式提供的两份本地技术元数据，不接收敏感输出或数据库文件。
原 ID、hash 和结构自洽不证明来源、真实交付或批准；没有平台导入/上传入口或持久隔离区。

## Explicit identity and untrusted hashes / 身份与 hash

The caller must explicitly supply:

1. The original canonical run UUID, never a latest/default/replacement ID.
2. The exact structural manifest fingerprint.
3. A SHA-256 for **each raw byte document**, independently of JSON formatting.
4. Both complete documents, each between 1 and **8,192 bytes**.

Hashes are checked before parsing each document. Matching hashes only bind
provided bytes to the caller's declarations. They are **not an authenticated
export receipt, signature, platform source binding, input-value binding, data
transfer permission or execution authority**. Even if a future caller obtains
hashes from a trusted transport, that alone does not attest these claimed events.

The original ID, declared source/manifest fingerprint, frozen input count and
frozen request count must match across the pair. A missing pre-dispatch receipt
is rejected, never reconstructed from a summary. There is no resend, resume,
repair, retry, latest selection or creation of a replacement local run.

## Fail-closed parser / 严格解析

- Exact UTF-8 JSON object schemas; no BOM, duplicate keys (including escaped
  aliases), arrays, extra fields or missing fields. Limit container depth to two
  **before** the JSON parser runs. Strings/escapes do not bypass depth checks.
- No floating point, exponents, non-finite numbers, negative numbers, large
  integer conversion, string-to-number or boolean-to-integer coercion.
- Exact `NOT_EVALUATED`, fixed unverified scope and literal false provenance,
  output-verification, resend and resume flags. Uploaded `PASS`, approval claims,
  output/gold/credentials/paths and unknown fields cannot enter the result.
- Frozen input denominator remains **ALL 1–500 inputs** and request denominator
  remains **ALL input_count–10,000 requests**, including unreserved/unknown work.
- Reserved + unreserved equals the complete request denominator; attempt-state
  counts sum to reservations and observation kinds sum to observed + unknown.
  Unknown kind equals unknown state. Ready/collected/running constraints match
  the existing producer formats; collected is never PASS.
- Covered-input counts must be feasible for distinct ordinals cycling through
  ALL frozen inputs. This is aggregate feasibility only, not ordinal proof.
- Request reservations respect the existing per-request bounds. Response
  reservations preserve the equal, non-recycled `(max_response_bytes + 1)`
  allocation; totals are bounded by **67,108,864 bytes**, including incomplete
  work. The metadata pair cannot prove these limits were actually enforced.

Errors have a single generic message, with no payload/path/field value and no
chained JSON parser exception retaining its `.doc`. This does not claim process
memory erasure, protection from a debugger, or a sandbox for arbitrary code.

## Result is not a capability / 不是证据或权限

The frozen/slots result stores only canonical sanitized JSON bytes, suppresses
payloads from `repr`, and returns a fresh dictionary on each `to_dict()`.
`metadata_sha256` identifies this representation only. Neither the class, hash,
`aggregate_coherence_checked` nor `declared_byte_hashes_matched` is an admission
token or authenticated receipt. The `quarantine_only` scope is a restriction,
**not a claim that a persistent quarantine service exists**.

Every successful result explicitly retains:

- `verdict=NOT_EVALUATED`;
- `platform_provenance_verified=false`;
- `per_ordinal_evidence_verified=false`, `output_content_verified=false`;
- `evidence_admitted=false`, `approval_granted=false`;
- `dispatch_authorized=false`, `resend_permitted=false`, `resume_permitted=false`.

A fully fabricated but internally coherent pair **can pass** this structural
inspection and must still carry every false trust/authority flag. It establishes
neither chronology, current journal state, output fsync/content, per-ordinal
truth, target delivery, ALL-sample evidence completeness, nor formal approval.
It must never replace platform runs, frozen assessment revisions or decisions.

## Verification / 验证

`backend/tests/test_external_qa_metadata.py` uses the actual existing synthetic
manifest, real local journal, real pre-dispatch receipt and original-ID
reconciliation. It covers ready/running/interrupted/collected and all seven
observation kinds without real sends. The parser is tested with file/SQLite
opens forbidden and network/DNS fail-closed; journal snapshots remain unchanged.

Regressions cover raw hashes before parsing, raw-byte versus canonical hashes,
every required field, extra sensitive/authority fields, malformed UTF-8/JSON,
duplicate keys, size/depth/type/numeric bounds, original-ID/fingerprint mismatch,
state/count/byte/coverage incoherence, immutable sanitized output and a coherent
forgery that remains untrusted. Parser-test injection is performed only after
materializing the synthetic source snapshot: patching the shared `json.loads`
before fixture reconciliation also blocks the fixture's real journal decoder,
not the parser contract. That initial fixture diagnostic is retained separately.

## Module-local verification (2026-11-10)

- New parser regressions: **111 passed / 4.76s**; shared-core/local-command/
  platform-workflow joint regression: **984 passed / 163.54s**. These overlap
  the full suite and are not added to its total.
- Standard `make test`: **13,180 passed / 18 skipped / 11 deselected /
  40 warnings / 774.85s**, plus the existing pure-domain unittest gates.
- Blocking IO: **72 passed / 5.50s**; Ruff check and format:
  **1,264 files**; `uv lock --check --offline` passed.
- Frontend runtime source is unchanged. Full frontend regression:
  **152 files / 1,293 passed / 12.5s**; entire frontend Prettier passed.
  The final six Markdown documents are independently format-checked.
- Initial **106 passed** and the later **110 passed / 1 failed** fixture
  diagnostic are retained. The latter patched shared `json.loads` before
  preparing real reconciliation; the test now materializes that source first.
  No runtime retry, timeout extension or weaker assertion hides the diagnostic.

Final tested-source matching, evidence export/hash verification, exact session
resource shutdown, commit/push and the new SHA's actual Actions have separate
receipts. Local test success does not establish remote CI success. Previous
module `5484861` Actions belong only to that SHA. No local browser, frontend
build/lint/typecheck, performance, Windows or real-user acceptance is claimed
for this parser module. No deployment, execution enablement or real calls.

## Remaining gates / 后续缺口

A future integration must authenticate the owner/human permissions, enforce
upload limits **before buffering**, offload synchronous parsing, implement a
bounded persistent isolation namespace and bind separately authorized exact
historical export/source/recipient/data-tier receipts. Source authentication,
ALL per-ordinal evidence, crypto, atomic immutable same-ID receipt/audit and
explicit human association still need independent modules/tests. Unknown writes
must reconcile only by GET of the original ID. No accepted client `PASS` can
authorize approval or overwrite platform history.

This module does not add encrypted local output/retention, exporter/data
transfer consent, scheduler, Lost Worker fencing, formal approval policy, an
upgrade or real-user acceptance. No dependency/runtime configuration, migration,
execution enablement, model call, target call or deployment is introduced.
