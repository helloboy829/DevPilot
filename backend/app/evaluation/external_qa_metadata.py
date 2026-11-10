"""Bounded external technical metadata inspection, never evidence admission.

Accepts only two existing JSON metadata formats, NOT an uploaded SQLite journal,
archive, output or executable. All identifiers/hashes remain caller declarations.
No filesystem/network/DB/config capability or import into the platform run chain.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from uuid import UUID

_SCOPE = "external_unverified_technical_only"
_MAX_BYTES = 8192
_MAX_TOTAL = 67_108_864
_ERROR = "External QA metadata rejected; no evidence accepted"
_STATES = ("dispatched", "observed", "delivery_unknown")
_KINDS = ("delivery_unknown", "http_error", "invalid_output", "output_collected", "policy_rejected", "response_limit", "unsupported_response")
_COMMON = {"schema", "scope", "verdict", "run_id", "frozen_input_count", "frozen_request_count", "platform_provenance_verified", "resend_permitted", "resume_permitted"}
_RECEIPT = _COMMON | {"receipt_kind", "manifest_fingerprint"}
_RECONCILIATION = _COMMON | {
    "declared_source_sha256",
    "state",
    "reserved_attempt_count",
    "unreserved_in_snapshot_count",
    "covered_input_count",
    "attempt_states",
    "observation_kinds",
    "reserved_request_bytes",
    "reserved_response_bytes",
    "output_content_verified",
}


class ExternalMetadataRejected(ValueError):
    """Generic rejection without payload, field values, paths or parser details."""


def _hash(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError
    return value


def _run_id(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError
    return value


def _integer(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _json_integer(text):
    # These schemas have nonnegative, bounded counts/bytes only. Bound BEFORE
    # converting, independently of the interpreter's large-integer setting.
    if len(text) > 10 or not text.isascii() or not text.isdecimal():
        raise ValueError
    return int(text)


def _noninteger(text):
    raise ValueError


def _bounded_json(data, declared_sha256):
    if type(data) is not bytes or not 1 <= len(data) <= _MAX_BYTES or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), _hash(declared_sha256)):
        raise ValueError
    # Limit nesting before json.loads, not after recursive parser allocation.
    # Neither format contains arrays; their only containers are root/flat maps.
    depth, quoted, escaped = 0, False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte == 123:
            depth += 1
            if depth > 2:
                raise ValueError
        elif byte == 125:
            depth -= 1
            if depth < 0:
                raise ValueError
        elif byte in (91, 93):
            raise ValueError
    if quoted or depth:
        raise ValueError
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_int=_json_integer, parse_float=_noninteger, parse_constant=_noninteger)
    if type(value) is not dict:
        raise ValueError
    return value


def _common(document, fields, schema, run_id, inputs, requests):
    if set(document) != fields or document["schema"] != schema or document["scope"] != _SCOPE or document["verdict"] != "NOT_EVALUATED" or document["run_id"] != run_id:
        raise ValueError
    if any(document[name] is not False for name in ("platform_provenance_verified", "resend_permitted", "resume_permitted")):
        raise ValueError
    if _integer(document["frozen_input_count"], 1, 500) != inputs or _integer(document["frozen_request_count"], inputs, 10_000) != requests:
        raise ValueError


def _counts(value, fields, maximum):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError
    return tuple(_integer(value[name], 0, maximum) for name in fields)


@dataclass(frozen=True, slots=True)
class ExternalMetadataInspection:
    """Immutable sanitized inspection, NOT an admission/approval capability.

    Even a completely fabricated coherent pair can pass structural inspection.
    This class/its hash must never be accepted as a platform evidence receipt.
    """

    _canonical_json: bytes = field(repr=False)

    def to_dict(self):
        """Return a fresh copy; callers cannot mutate the inspection in place."""
        return json.loads(self._canonical_json)

    @property
    def metadata_sha256(self):
        """Integrity of this sanitized representation only, never provenance."""
        return hashlib.sha256(self._canonical_json).hexdigest()


def inspect_local_metadata(receipt, reconciliation, *, original_run_id, manifest_fingerprint, receipt_sha256, reconciliation_sha256):
    """Inspect explicitly selected, bounded JSON bytes with no I/O side effects.

    Raw-byte hashes, original ID and fingerprint are supplied declarations, NOT
    an authenticated platform source or transfer receipt. Aggregate consistency
    does not verify per-ordinal facts, chronology, target delivery, current state,
    output persistence/content, ALL-sample evidence or approval. No truth claim
    is upgraded when state=collected or every observation=output_collected.

    A future HTTP caller must bound the request BEFORE buffering and offload this
    synchronous parser; this module does not supply upload/auth/storage/audits.
    """
    try:
        run_id = _run_id(original_run_id)
        fingerprint = _hash(manifest_fingerprint)
        identity = _bounded_json(receipt, receipt_sha256)
        summary = _bounded_json(reconciliation, reconciliation_sha256)
        inputs = _integer(identity.get("frozen_input_count"), 1, 500)
        requests = _integer(identity.get("frozen_request_count"), inputs, 10_000)
        _common(identity, _RECEIPT, "local-qa-run-receipt.v1", run_id, inputs, requests)
        _common(summary, _RECONCILIATION, "local-qa-reconciliation.v1", run_id, inputs, requests)
        if identity["receipt_kind"] != "pre_dispatch_identity_only" or identity["manifest_fingerprint"] != fingerprint or summary["declared_source_sha256"] != fingerprint:
            raise ValueError
        state = summary["state"]
        if type(state) is not str or state not in {"ready", "running", "interrupted", "collected"} or summary["output_content_verified"] is not False:
            raise ValueError
        reserved = _integer(summary["reserved_attempt_count"], 0, requests)
        if _integer(summary["unreserved_in_snapshot_count"], 0, requests) != requests - reserved:
            raise ValueError
        covered = _integer(summary["covered_input_count"], int(reserved > 0), min(inputs, reserved))
        # Distinct ordinals cycle through ALL frozen inputs. Even aggregates must
        # be feasible: k covered inputs cannot account for more than k*cycles
        # plus the most frequent remainder slots. This does NOT prove ordinals.
        cycles, remainder = divmod(requests, inputs)
        if reserved > covered * cycles + min(covered, remainder) or (reserved == requests and covered != inputs):
            raise ValueError
        counts = _counts(summary["attempt_states"], _STATES, reserved)
        kinds = _counts(summary["observation_kinds"], _KINDS, reserved)
        dispatched, observed, unknown = counts
        if sum(counts) != reserved or sum(kinds) != observed + unknown or kinds[0] != unknown:
            raise ValueError
        if (state == "ready" and reserved != 0) or (state in {"running", "collected"} and unknown) or (state == "collected" and (reserved != requests or observed != requests)):
            raise ValueError
        request_bytes = _integer(summary["reserved_request_bytes"], reserved, min(_MAX_TOTAL, reserved * 262_144))
        response_bytes = _integer(summary["reserved_response_bytes"], reserved * 2, min(_MAX_TOTAL, reserved * 1_048_577))
        if reserved and response_bytes % reserved:
            raise ValueError
        checked = {
            "schema": "external-qa-metadata-inspection.v1",
            "scope": "external_technical_metadata_quarantine_only",
            "original_run_id": run_id,
            "declared_manifest_fingerprint": fingerprint,
            "declared_raw_sha256": {"receipt": receipt_sha256, "reconciliation": reconciliation_sha256},
            "frozen_input_count": inputs,
            "frozen_request_count": requests,
            "claimed_state": state,
            "reserved_attempt_count": reserved,
            "unreserved_in_snapshot_count": requests - reserved,
            "covered_input_count": covered,
            "attempt_states": dict(zip(_STATES, counts, strict=True)),
            "observation_kinds": dict(zip(_KINDS, kinds, strict=True)),
            "reserved_request_bytes": request_bytes,
            "reserved_response_bytes": response_bytes,
            "declared_byte_hashes_matched": True,
            "aggregate_coherence_checked": True,
            "platform_provenance_verified": False,
            "per_ordinal_evidence_verified": False,
            "output_content_verified": False,
            "evidence_admitted": False,
            "approval_granted": False,
            "dispatch_authorized": False,
            "resend_permitted": False,
            "resume_permitted": False,
            "verdict": "NOT_EVALUATED",
        }
        return ExternalMetadataInspection(json.dumps(checked, sort_keys=True, separators=(",", ":")).encode("ascii"))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        pass
    # Do not retain JSONDecodeError.doc or attacker text in exception context.
    raise ExternalMetadataRejected(_ERROR)
