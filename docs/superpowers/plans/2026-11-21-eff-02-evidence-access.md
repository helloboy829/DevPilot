# EFF-02 Evidence Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit, audited, short-lived access to captured effectiveness evidence without exposing evidence through ordinary result DTOs or bypassing independent-review blindness.

**Architecture:** Keep evidence authorization in `app.evaluation`; the router validates human identity and permission, while the repository binds each grant to actor, project, run, case, evidence kind, evidence hash, task/round context and expiry. Persist only a one-way access-token hash and append-only audit metadata; every content read rechecks actor, object state and any review assignment before decrypting a bounded artifact. Only evidence that is actually captured is readable; unsupported historical/input/reference/request/stream evidence fails closed and is never reconstructed from extracted output.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, Pydantic, AES-GCM response artifact store, pytest, Ruff.

**Spec:** `docs/DevPilot_效果测试工作台设计.md` sections 4-7 and `docs/DevPilot_Feature_Implementation_Spec.md` EFF-02.

## Global Constraints

- Ordinary result DTOs must not contain expected, raw request, raw response or credential material.
- Each evidence type requires a separate explicit grant and access audit; project membership does not grant blind-review answers or another reviewer's decisions.
- Access IDs are opaque, short-lived, actor-bound, stored only as hashes and revalidated at content-read time.
- Evidence responses use `Cache-Control: no-store`, strict media handling, bounded body/range reads, and generic errors without filesystem paths or decryption details.
- Unknown, legacy-unavailable, partial-integrity, stale-hash, expired-grant and unauthorized evidence fails closed; no raw request body may be synthesized.
- All verification uses synthetic fixtures and Mock transports; do not deploy or call real models/targets.
- Preserve `docs/superpowers/plans/.patch-test`; do not stage it.

### Current implementation checkpoint (2026-11-21)

- Implemented encrypted artifact range extraction in `ResponseArtifactStore.open_range`: full reads, one inclusive byte range, suffix ranges, and bounded end positions; malformed, multi-range, empty-body, and unsatisfiable ranges fail closed.
- Verification on Windows/Python 3.12 isolated environment: `tests/test_qa_artifact_store.py -k open_range` passed (7 passed); Ruff check and format check passed for the artifact store and its tests.
- This is storage groundwork only. No grant, audit, actor revalidation, authorized response route, review-task blindness enforcement, migration, or end-to-end EFF-02 behavior is complete.

---

### Task 1: Define and test grant/access contracts

**Files:**
- Modify: `backend/tests/test_qa_evidence_router.py`
- Modify: `backend/tests/test_qa_evidence.py`
- Modify: `docs/DevPilot_效果测试工作台设计.md`

**Interfaces:**
- Produces strict request DTO `EvidenceAccessCreate(kind, evidence_hash, confirmed=True)` and response `{access_id, expires_at_ms, evidence_kind, evidence_hash}`.
- Supported first captured kind is `response`; all unavailable kinds return the same non-disclosing conflict response.
- A read returns bounded raw bytes and a safe media type, never an artifact path or key metadata.

- [ ] Add synthetic API cases proving no body appears in ordinary list/detail DTOs, grant requires explicit confirmation and exact current hash, and unsupported/unavailable kinds fail closed.
- [ ] Run the new tests and confirm they fail because grant/read routes do not exist.
- [ ] Document response-only initial availability and explicit future inputs required before adding request/reference/stream reads.

### Task 2: Persist opaque grants and append-only access audit

**Files:**
- Modify: `backend/app/evaluation/tables.py`
- Create: `backend/app/evaluation/migrations/versions/eval_0021_evidence_access.py`
- Modify: `backend/tests/test_qa_evidence.py`
- Modify: `backend/tests/test_qa_assessments_migrations.py`

**Interfaces:**
- `evaluation_evidence_access_grants` stores token hash, actor/object/evidence binding, optional task/round binding, expiry, and consumed/revoked state; it never stores raw access IDs or plaintext evidence.
- `evaluation_evidence_access_audit` stores sequence, actor, object, kind, evidence hash, action, authorization basis and timestamp; it never stores evidence bytes.

- [ ] Add migration reflection/upgrade/downgrade tests and constraints for bounded IDs, kinds, actions, expiry and sequence.
- [ ] Run focused migration tests and verify SQLite plus configured PostgreSQL schema parity.
- [ ] Implement only additive migration changes; preserve all existing artifact and review-task rows.

### Task 3: Implement actor-bound grant and bounded response read

**Files:**
- Modify: `backend/app/evaluation/qa_evidence.py`
- Modify: `backend/app/evaluation/qa_artifact_store.py`
- Modify: `backend/app/gateway/routers/evaluation_projects.py`
- Modify: `backend/tests/test_qa_evidence.py`
- Modify: `backend/tests/test_qa_evidence_router.py`

**Interfaces:**
- `EvidenceRepository.create_evidence_access(actor, project_id, run_id, ordinal, payload, review_context=None)` returns the public grant DTO.
- `EvidenceRepository.read_evidence_access(actor, access_id, range_header=None)` returns `{body: bytes, content_type: str, status_code: int, content_range: str | None}`.
- Routes: `POST /api/evaluation/projects/{project_id}/review-runs/{run_id}/cases/{ordinal}/evidence-access` and `GET /api/evaluation/projects/{project_id}/evidence/{access_id}`.

- [ ] Add RED tests for owner isolation, wrong project/case/hash, cross-actor token use, expired/replayed/revoked grant, missing key, corrupted artifact, partial/truncated capture, and response size limit.
- [ ] Add RED tests for `no-store`, unsupported Range (416), bounded single-range (206), and safe content-type disposition that cannot render HTML/SVG inline.
- [ ] Implement token generation with cryptographic randomness; persist SHA-256 token hash only, expiry at most five minutes, and one-time consumption in the same transaction as access audit.
- [ ] Recheck project/run/case/artifact hash and actor binding immediately before decrypting; perform filesystem read/decrypt off-loop and expose generic 404/409/503 errors.
- [ ] Return `application/octet-stream` with attachment disposition for active content; allow only validated single byte ranges capped by the frozen response artifact size and configured maximum.
- [ ] Run focused domain/router tests and Ruff; confirm no extracted-output token or request body is used as a fallback.

### Task 4: Enforce review-task blindness and complete the delivery record

**Files:**
- Modify: `backend/app/evaluation/qa_evidence.py`
- Modify: `backend/app/evaluation/review_tasks.py`
- Modify: `backend/tests/test_qa_evidence_router.py`
- Modify: `backend/tests/test_review_tasks.py`
- Modify: `docs/DevPilot_Feature_Implementation_Spec.md`
- Modify: `docs/DevPilot_实现进度与下一步.md`
- Modify: `docs/DevPilot_Delivery_Status.md`

**Interfaces:**
- Review-task evidence grants require the current assigned actor, active role/round, unexpired lease, viewed current revision, and task subject hash matching the case hash.
- Reference evidence is not exposed to independent reviewers before the contract-defined reveal point; owners and other reviewers cannot use owner-review routes to bypass this rule.

- [ ] Add RED tests for unassigned actor, expired lease, changed round/revision, wrong subject hash, pre-reveal reference, and owner/assignee cross-context access.
- [ ] Implement grant context validation under the same run/task locking and recheck context again on read; audit both grant and successful read without evidence content.
- [ ] Run focused test files, `make lint`, `make test-blocking-io`, then full offline `make test`.
- [ ] Update feature matrix, implementation ledger and delivery status with exact local commands, outcomes and SHA; commit and push only after full-suite verification, then check Actions for that exact SHA.

## Known scope boundary

This slice can serve only durable response artifacts already captured by EVID-02. Request body is intentionally not stored; historical raw body, input/reference plaintext, extracted output, token stream and attachments remain unavailable until their own capture profiles, schemas and authorization sources exist. The API must report unavailable without substituting another evidence class.
