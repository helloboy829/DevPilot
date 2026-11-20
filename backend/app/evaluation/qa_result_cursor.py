"""Versioned, query-bound cursors for effectiveness result pagination."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from typing import Any

_CURSOR_VERSION = 1
_MAX_TOKEN_BYTES = 4096
_MAX_PAYLOAD_BYTES = 3072
_PURPOSE = b"devpilot:effectiveness-results-cursor:v1"
_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class InvalidResultCursor(ValueError):
    """The cursor is malformed, tampered, or belongs to another query."""


class StaleResultCursor(InvalidResultCursor):
    """The cursor is authentic but its visible result snapshot has changed."""


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise InvalidResultCursor from None


def _signing_key(secret: str) -> bytes:
    if type(secret) is not str or not secret:
        raise InvalidResultCursor
    return hmac.new(secret.encode("utf-8"), _PURPOSE, hashlib.sha256).digest()


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_segment(value: str) -> bytes:
    if not value or _BASE64URL.fullmatch(value) is None:
        raise InvalidResultCursor
    padded = value + "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        raise InvalidResultCursor from None
    if _encode_segment(decoded) != value:
        raise InvalidResultCursor
    return decoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidResultCursor
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise InvalidResultCursor


def encode_cursor(payload: dict[str, Any], secret: str) -> str:
    """Encode a cursor payload containing exactly a query binding and position."""
    if type(payload) is not dict or set(payload) != {"binding", "position"}:
        raise InvalidResultCursor
    if type(payload["binding"]) is not dict or type(payload["position"]) is not dict:
        raise InvalidResultCursor

    document = _canonical_json({"version": _CURSOR_VERSION, "payload": payload})
    if len(document) > _MAX_PAYLOAD_BYTES:
        raise InvalidResultCursor
    signature = hmac.new(_signing_key(secret), document, hashlib.sha256).digest()
    token = _encode_segment(document) + "." + _encode_segment(signature)
    if len(token.encode("ascii")) > _MAX_TOKEN_BYTES:
        raise InvalidResultCursor
    return token


def decode_cursor(
    token: str,
    secret: str,
    expected_binding: dict[str, Any],
    *,
    stale_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Verify the cursor signature and require an exact canonical query binding."""
    if type(token) is not str or len(token.encode("utf-8", errors="ignore")) > _MAX_TOKEN_BYTES:
        raise InvalidResultCursor
    if type(expected_binding) is not dict:
        raise InvalidResultCursor

    segments = token.split(".")
    if len(segments) != 2:
        raise InvalidResultCursor
    document, signature = (_decode_segment(segment) for segment in segments)
    if len(document) > _MAX_PAYLOAD_BYTES or len(signature) != hashlib.sha256().digest_size:
        raise InvalidResultCursor

    expected_signature = hmac.new(_signing_key(secret), document, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidResultCursor

    try:
        envelope = json.loads(
            document.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidResultCursor):
        raise InvalidResultCursor from None
    if type(envelope) is not dict or set(envelope) != {"version", "payload"} or type(envelope["version"]) is not int or envelope["version"] != _CURSOR_VERSION:
        raise InvalidResultCursor

    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != {"binding", "position"}:
        raise InvalidResultCursor
    if type(payload["binding"]) is not dict or type(payload["position"]) is not dict:
        raise InvalidResultCursor
    actual_binding = payload["binding"]
    if set(actual_binding) != set(expected_binding):
        raise InvalidResultCursor
    changed_fields = {name for name, value in expected_binding.items() if not hmac.compare_digest(_canonical_json(actual_binding[name]), _canonical_json(value))}
    if changed_fields:
        if changed_fields <= stale_fields:
            raise StaleResultCursor
        raise InvalidResultCursor
    return payload
