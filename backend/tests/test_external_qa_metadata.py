"""Strict external metadata only: real local producer, no upload/import/send."""

import hashlib
import json
import socket
from dataclasses import FrozenInstanceError
from pathlib import Path
from uuid import uuid4

import pytest
from devpilot.local_json_run import LocalJSONJournal
from devpilot.local_qa_cli import LocalRunManifest, _write_run_receipt
from devpilot.local_qa_reconcile import reconcile
from devpilot.qa_json_attempt import AttemptObservation

from app.evaluation.external_qa_metadata import ExternalMetadataRejected, inspect_local_metadata

ROOT = Path(__file__).resolve().parents[2]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("Real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", deny)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, deny)


@pytest.fixture
def sources(tmp_path):
    manifest = LocalRunManifest.from_dict(json.loads((ROOT / "devpilot/distribution/examples/manifest.json").read_text()))
    run_id = str(uuid4())
    definition = manifest.definition(run_id, 1000)
    journal = LocalJSONJournal.create(tmp_path / "journal.sqlite", definition)
    _write_run_receipt(tmp_path, run_id, manifest)
    receipt = (tmp_path / "run-receipt.json").read_bytes()
    yield {"manifest": manifest, "journal": journal, "run_id": run_id, "receipt": receipt}
    journal.close()


def inspect(sources, *, receipt=None, summary=None, **changes):
    receipt = sources["receipt"] if receipt is None else receipt
    summary = encode(reconcile(sources["journal"]._path, sources["run_id"])) if summary is None else summary
    arguments = {
        "original_run_id": sources["run_id"],
        "manifest_fingerprint": sources["manifest"].fingerprint,
        "receipt_sha256": digest(receipt),
        "reconciliation_sha256": digest(summary),
        **changes,
    }
    return inspect_local_metadata(receipt, summary, **arguments)


def collect(sources, kind="output_collected"):
    journal = sources["journal"]
    journal.start(1001)
    for ordinal in range(1, 6):
        ticket = journal.reserve(ordinal, 20, 1002)
        status = 400 if kind == "http_error" else None if kind in {"delivery_unknown", "policy_rejected"} else 200
        size = 0 if kind in {"http_error", "unsupported_response", "policy_rejected"} else 8
        journal.record(ticket, AttemptObservation(kind=kind, http_status=status, body_bytes=size, elapsed_ms=1, output="SENSITIVE_SYNTHETIC_OUTPUT" if kind == "output_collected" else None))
        if kind == "delivery_unknown":
            break
    return journal.finish(completed=kind != "delivery_unknown")


def assert_untrusted(document):
    assert document["verdict"] == "NOT_EVALUATED"
    for key in ("platform_provenance_verified", "per_ordinal_evidence_verified", "output_content_verified", "evidence_admitted", "approval_granted", "dispatch_authorized", "resend_permitted", "resume_permitted"):
        assert document[key] is False


@pytest.mark.parametrize("state", ["ready", "running", "interrupted", "collected"])
def test_real_same_id_pair_preserves_all_frozen_denominators(sources, state):
    journal = sources["journal"]
    if state == "running":
        journal.start(1001)
        journal.reserve(1, 20, 1002)
    elif state == "interrupted":
        journal.start(1001)
        journal.reserve(1, 20, 1002)
        journal.finish(completed=False)
    elif state == "collected":
        collect(sources)
    result = inspect(sources)
    document = result.to_dict()
    assert document["schema"] == "external-qa-metadata-inspection.v1"
    assert document["scope"] == "external_technical_metadata_quarantine_only"
    assert document["claimed_state"] == state
    assert document["original_run_id"] == sources["run_id"]
    assert document["frozen_input_count"] == 2 and document["frozen_request_count"] == 5
    assert document["aggregate_coherence_checked"] is True
    assert document["declared_byte_hashes_matched"] is True
    assert_untrusted(document)
    assert "SENSITIVE_SYNTHETIC_OUTPUT" not in json.dumps(document)
    assert sources["run_id"] not in repr(result)
    document["frozen_request_count"] = 1
    assert result.to_dict()["frozen_request_count"] == 5
    assert result.metadata_sha256 == digest(encode(result.to_dict()))
    with pytest.raises(FrozenInstanceError):
        result._canonical_json = b"changed"


@pytest.mark.parametrize("kind", ["output_collected", "http_error", "unsupported_response", "response_limit", "invalid_output", "delivery_unknown", "policy_rejected"])
def test_all_real_observation_kinds_remain_not_evaluated(sources, kind):
    collect(sources, kind)
    document = inspect(sources).to_dict()
    assert document["observation_kinds"][kind] == (1 if kind == "delivery_unknown" else 5)
    assert document["frozen_input_count"] == 2 and document["frozen_request_count"] == 5
    assert_untrusted(document)


def test_parser_has_no_io_and_cannot_mutate_the_journal(sources, monkeypatch):
    receipt = sources["receipt"]
    summary = encode(reconcile(sources["journal"]._path, sources["run_id"]))
    before = sources["journal"].snapshot()

    def deny(*args, **kwargs):
        raise AssertionError("Metadata parser must not open any file/database")

    with monkeypatch.context() as patch:
        patch.setattr("builtins.open", deny)
        patch.setattr(Path, "open", deny)
        patch.setattr("sqlite3.connect", deny)
        parsed = inspect(sources, receipt=receipt, summary=summary)
    assert_untrusted(parsed.to_dict())
    assert sources["journal"].snapshot() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("verdict", "PASS"),
        ("scope", "platform_verified"),
        ("run_id", str(uuid4())),
        ("platform_provenance_verified", True),
        ("resend_permitted", 0),
        ("resume_permitted", None),
        ("frozen_input_count", True),
        ("frozen_request_count", 5.0),
        ("frozen_input_count", 0),
        ("frozen_input_count", 501),
        ("frozen_request_count", 10001),
        ("schema", "local-qa-run-receipt.v2"),
        ("receipt_kind", "execution_approved"),
        ("manifest_fingerprint", "a" * 64),
    ],
)
def test_rejects_receipt_claims_and_coercions(sources, field, value):
    receipt = json.loads(sources["receipt"])
    receipt[field] = value
    with pytest.raises(ExternalMetadataRejected, match="^External QA metadata rejected; no evidence accepted$"):
        inspect(sources, receipt=encode(receipt))


@pytest.mark.parametrize("field", ["gold", "output", "encrypted_payload", "authorization", "recipient", "approved", "path", "extra"])
def test_extra_sensitive_authority_or_unknown_fields_rejected(sources, field):
    for target in ("receipt", "summary"):
        document = json.loads(sources["receipt"]) if target == "receipt" else reconcile(sources["journal"]._path, sources["run_id"])
        document[field] = "SENSITIVE_UNTRUSTED_MARKER"
        with pytest.raises(ExternalMetadataRejected) as caught:
            inspect(sources, **{target: encode(document)})
        assert "SENSITIVE_UNTRUSTED_MARKER" not in str(caught.value)
        assert caught.value.__context__ is None and caught.value.__cause__ is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("original_run_id", str(uuid4())),
        ("original_run_id", ""),
        ("original_run_id", None),
        ("manifest_fingerprint", "a" * 64),
        ("manifest_fingerprint", "A" * 64),
        ("receipt_sha256", "0" * 64),
        ("reconciliation_sha256", "f" * 64),
        ("receipt_sha256", True),
        ("reconciliation_sha256", "sha256:" + "0" * 64),
    ],
)
def test_declared_original_identity_and_raw_byte_hashes_required(sources, field, value):
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, **{field: value})


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        pytest.param(b" " * 8193, id="over-byte-limit"),
        b"\xef\xbb\xbf{}",
        b"\xff",
        b"[]",
        b"null",
        b"true",
        b"1",
        b"{}{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e0}',
        b'{"x":1.0}',
        b'{"x":-0}',
        b'{"x":10000000000}',
        b'{"x":1,"x":2}',
        b'{"x":1,"\\u0078":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":[0]}',
        b'{"x":{"y":{}}}',
        pytest.param(b"{" * 4000 + b"}" * 4000, id="excessive-nesting"),
        b'{"x":"unterminated}',
        b'{"x":"\\"}',
    ],
)
def test_strict_bounded_json_rejection(sources, payload):
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, summary=payload)


@pytest.mark.parametrize("value", ["{}", bytearray(b"{}"), memoryview(b"{}"), Path("untrusted.sqlite"), {}, None])
def test_only_already_bounded_exact_bytes_not_file_objects_or_paths(sources, value):
    with pytest.raises(ExternalMetadataRejected):
        inspect_local_metadata(value, b"{}", original_run_id=sources["run_id"], manifest_fingerprint=sources["manifest"].fingerprint, receipt_sha256="0" * 64, reconciliation_sha256=digest(b"{}"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "unknown"),
        ("run_id", str(uuid4())),
        ("scope", "verified"),
        ("verdict", "PASS"),
        ("frozen_input_count", 1),
        ("frozen_request_count", 4),
        ("declared_source_sha256", "b" * 64),
        ("output_content_verified", True),
        ("platform_provenance_verified", 0),
        ("state", []),
        ("state", "completed"),
        ("reserved_attempt_count", True),
        ("reserved_attempt_count", 1),
        ("unreserved_in_snapshot_count", 4),
        ("covered_input_count", 1),
        ("reserved_request_bytes", 1),
        ("reserved_response_bytes", 1),
        ("attempt_states", {"dispatched": False, "observed": 0, "delivery_unknown": 0}),
        ("attempt_states", {"dispatched": 0, "observed": 0, "delivery_unknown": 0, "PASS": 0}),
        ("observation_kinds", {}),
    ],
)
def test_summary_exact_schema_original_identity_and_ready_coherence(sources, field, value):
    summary = reconcile(sources["journal"]._path, sources["run_id"])
    summary[field] = value
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, summary=encode(summary))


@pytest.mark.parametrize("damage", ["state-sum", "kind-sum", "unknown-kind", "ready", "collected", "running-unknown", "coverage", "request-low", "request-high", "response-low", "response-high", "response-modulo"])
def test_nonzero_aggregate_incoherence_rejected(sources, damage):
    collect(sources)
    summary = reconcile(sources["journal"]._path, sources["run_id"])
    if damage == "state-sum":
        summary["attempt_states"]["observed"] = 4
    elif damage == "kind-sum":
        summary["observation_kinds"]["output_collected"] = 4
    elif damage == "unknown-kind":
        summary["observation_kinds"]["output_collected"] = 4
        summary["observation_kinds"]["delivery_unknown"] = 1
    elif damage == "ready":
        summary["state"] = "ready"
    elif damage == "collected":
        summary["attempt_states"] = {"observed": 4, "dispatched": 1, "delivery_unknown": 0}
        summary["observation_kinds"]["output_collected"] = 4
    elif damage == "running-unknown":
        summary["state"] = "running"
        summary["attempt_states"] = {"observed": 4, "dispatched": 0, "delivery_unknown": 1}
        summary["observation_kinds"]["output_collected"] = 4
        summary["observation_kinds"]["delivery_unknown"] = 1
    elif damage == "coverage":
        summary["covered_input_count"] = 1
    elif damage.startswith("request-"):
        summary["reserved_request_bytes"] = 4 if damage.endswith("low") else 5 * 262144 + 1
    else:
        summary["reserved_response_bytes"] = {"response-low": 5, "response-high": 5 * 1048577 + 1, "response-modulo": 11}[damage]
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, summary=encode(summary))


def test_a_coherently_forged_collected_pair_is_never_trusted(sources):
    # A producer need not exist: attacker can fabricate all counts and rehash.
    # This parser must NOT turn internally consistent claims into evidence.
    summary = reconcile(sources["journal"]._path, sources["run_id"])
    summary.update(state="collected", reserved_attempt_count=5, unreserved_in_snapshot_count=0, covered_input_count=2, reserved_request_bytes=100, reserved_response_bytes=100)
    summary["attempt_states"]["observed"] = 5
    summary["observation_kinds"]["output_collected"] = 5
    document = inspect(sources, summary=encode(summary)).to_dict()
    assert_untrusted(document)
    assert sources["journal"].snapshot().state == "ready"


def test_missing_receipt_and_duplicate_json_cannot_be_reconstructed(sources):
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, receipt=b"{}")
    original = sources["receipt"].rstrip()
    duplicate = original[:-1] + b',"run_id":"' + sources["run_id"].encode() + b'"}'
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, receipt=duplicate)


def test_raw_hashes_are_checked_before_parsing(sources, monkeypatch):
    summary = encode(reconcile(sources["journal"]._path, sources["run_id"]))

    def deny(*args, **kwargs):
        raise AssertionError("Wrong byte hash must reject BEFORE JSON parse")

    monkeypatch.setattr("app.evaluation.external_qa_metadata.json.loads", deny)
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, summary=summary, receipt_sha256="0" * 64)


@pytest.mark.parametrize("which", ["receipt", "summary"])
def test_every_required_field_is_required_and_errors_retain_no_parser_document(sources, which):
    document = json.loads(sources["receipt"]) if which == "receipt" else reconcile(sources["journal"]._path, sources["run_id"])
    for key in document:
        damaged = {name: value for name, value in document.items() if name != key}
        with pytest.raises(ExternalMetadataRejected) as caught:
            inspect(sources, **{which: encode(damaged)})
        assert caught.value.__context__ is None and caught.value.__cause__ is None
    with pytest.raises(ExternalMetadataRejected) as caught:
        inspect(sources, **{which: b'{"SENSITIVE_PAYLOAD":'})
    assert caught.value.__context__ is None


def test_original_raw_bytes_not_canonicalization_are_hash_bound(sources):
    compact = sources["receipt"].strip()
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, receipt=compact, receipt_sha256=digest(sources["receipt"]))
    assert_untrusted(inspect(sources, receipt=compact).to_dict())


def test_partial_cycling_coverage_cannot_hide_too_many_reservations(sources):
    summary = reconcile(sources["journal"]._path, sources["run_id"])
    # Five ordinals cycling over two inputs: one input can occur only 3 times.
    summary.update(state="running", reserved_attempt_count=4, unreserved_in_snapshot_count=1, covered_input_count=1, reserved_request_bytes=80, reserved_response_bytes=516)
    summary["attempt_states"]["dispatched"] = 4
    with pytest.raises(ExternalMetadataRejected):
        inspect(sources, summary=encode(summary))
    summary.update(reserved_attempt_count=3, unreserved_in_snapshot_count=2, reserved_request_bytes=60, reserved_response_bytes=387)
    summary["attempt_states"]["dispatched"] = 3
    assert_untrusted(inspect(sources, summary=encode(summary)).to_dict())
