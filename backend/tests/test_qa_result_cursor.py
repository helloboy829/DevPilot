"""Signed, query-bound cursors for effectiveness result pagination."""

import copy

import pytest

from app.evaluation.qa_result_cursor import InvalidResultCursor, decode_cursor, encode_cursor

SECRET = "synthetic-jwt-secret-for-result-cursor-tests"
BINDING = {
    "actor_id": "actor-1",
    "project_id": "project-1",
    "resource": "run-cases",
    "filters": {"status": "complete"},
    "limit": 20,
    "ordering": "ordinal-asc",
    "snapshot_hash": "a" * 64,
    "result_version": "b" * 64,
}
PAYLOAD = {"binding": BINDING, "position": {"ordinal": 17}}


def test_cursor_round_trip_returns_position_for_identical_query():
    token = encode_cursor(PAYLOAD, SECRET)

    assert decode_cursor(token, SECRET, BINDING) == PAYLOAD


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "actor-2"),
        ("project_id", "project-2"),
        ("resource", "other-resource"),
        ("filters", {"status": "failed"}),
        ("limit", 21),
        ("ordering", "ordinal-desc"),
        ("snapshot_hash", "c" * 64),
        ("result_version", "d" * 64),
    ],
)
def test_cursor_rejects_a_different_query_binding(field, value):
    token = encode_cursor(PAYLOAD, SECRET)
    changed_binding = copy.deepcopy(BINDING)
    changed_binding[field] = value

    with pytest.raises(InvalidResultCursor):
        decode_cursor(token, SECRET, changed_binding)


def test_cursor_rejects_tampering_and_a_different_signing_secret():
    token = encode_cursor(PAYLOAD, SECRET)
    replacement = "A" if token[-1] != "A" else "B"

    with pytest.raises(InvalidResultCursor):
        decode_cursor(token[:-1] + replacement, SECRET, BINDING)
    with pytest.raises(InvalidResultCursor):
        decode_cursor(token, SECRET + "-rotated", BINDING)


@pytest.mark.parametrize("token", ["", "not-a-cursor", "!" * 4097])
def test_cursor_rejects_malformed_or_oversized_tokens(token):
    with pytest.raises(InvalidResultCursor):
        decode_cursor(token, SECRET, BINDING)


def test_cursor_does_not_depend_on_evidence_encryption_key(monkeypatch):
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)

    token = encode_cursor(PAYLOAD, SECRET)

    assert decode_cursor(token, SECRET, BINDING)["position"] == {"ordinal": 17}
