"""Pure, bounded QA text wiring into JSON requests and out of JSON responses.

This prepares values only. No network, environment, model, storage, expected-answer
access, grading, stream decoding or execution approval. A caller must independently
verify ownership, frozen versions, HTTP status, consent and outbound policy.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException

from devpilot.request_versions import FrozenRequest

_SCHEMA = "qa-json-binding.v1"
_MAX_DEPTH = 32
_MAX_NODES = 50_000


def _pointer(value: str, *, input_pointer: bool = False) -> tuple[str, ...]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError
    if not value:
        if input_pointer:
            raise ValueError
        return ()
    if not value.startswith("/"):
        raise ValueError
    parts = value[1:].split("/")
    if len(parts) > 16 or any(re.search(r"~(?![01])", part) for part in parts):
        raise ValueError
    return tuple(part.replace("~1", "/").replace("~0", "~") for part in parts)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError


def _decimal(value):
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError
    return result


def _decode(document: str, maximum: int):
    if not isinstance(document, str) or len(document.encode("utf-8")) > maximum:
        raise ValueError
    result = json.loads(document, object_pairs_hook=_unique, parse_constant=_reject_constant, parse_float=_decimal)
    stack, count = [(result, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if depth > _MAX_DEPTH or count > _MAX_NODES:
            raise ValueError
        if isinstance(value, (dict, list)):
            stack.extend((child, depth + 1) for child in (value.values() if isinstance(value, dict) else value))
    return result


def _key(container, part):
    if isinstance(container, dict) and part in container:
        return part
    if isinstance(container, list) and re.fullmatch(r"0|[1-9][0-9]{0,8}", part) and int(part) < len(container):
        return int(part)
    raise ValueError


def _locate(document, parts):
    value = document
    for part in parts:
        value = value[_key(value, part)]
    return value


def _encode(value):
    """Serialize bounded parsed JSON without rounding untouched decimal values."""
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _encode(child) for key, child in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_encode(child) for child in value) + "]"
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError
        return str(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class QAJSONBinding:
    """An existing JSON string leaf receives QA input; a JSON string is extracted.

    Pointers use a bounded RFC 6901-style subset, never JSONPath or expressions.
    Empty output pointer selects the root string. Empty input pointer, implicit
    path creation, array appends, nontext leaf coercion and duplicate keys fail.
    """

    input_pointer: str = field(repr=False)
    output_pointer: str = field(repr=False)
    schema: str = _SCHEMA

    def __post_init__(self):
        try:
            if self.schema != _SCHEMA:
                raise ValueError
            _pointer(self.input_pointer, input_pointer=True)
            _pointer(self.output_pointer)
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Invalid QA JSON binding") from None

    def to_dict(self) -> dict:
        return {"schema": self.schema, "input_pointer": self.input_pointer, "output_pointer": self.output_pointer}

    @classmethod
    def from_dict(cls, payload: dict) -> QAJSONBinding:
        try:
            if not isinstance(payload, dict) or set(payload) != {"schema", "input_pointer", "output_pointer"}:
                raise ValueError
            return cls(**payload)
        except (ValueError, TypeError):
            raise ValueError("Invalid QA JSON binding") from None

    def render(self, request: FrozenRequest, sample_input: str) -> FrozenRequest:
        """Copy the request with exactly one existing text leaf replaced by input.

        JSON whitespace/number spelling may change, not numeric precision or other
        field values. Full request values are protected, never a public/log DTO.
        """
        try:
            checked = self.from_dict(self.to_dict())
            if not isinstance(sample_input, str) or not sample_input.strip() or len(sample_input) > 10_000:
                raise ValueError
            sample_input.encode("utf-8")
            if not isinstance(request, FrozenRequest):
                raise ValueError
            original = FrozenRequest.from_protected_dict(request.to_protected_dict())
            document = _decode(original.body, 262_144)
            parts = _pointer(checked.input_pointer, input_pointer=True)
            parent = _locate(document, parts[:-1])
            key = _key(parent, parts[-1])
            if not isinstance(parent[key], str):
                raise ValueError
            parent[key] = sample_input
            return FrozenRequest(url=original.url, method=original.method, headers=original.headers, body=_encode(document))
        except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError, OverflowError, UnicodeError, DecimalException):
            raise ValueError("Cannot render QA JSON request") from None

    def extract(self, response_body: str) -> str:
        """Extract a JSON string only; empty text remains empty, never a verdict."""
        try:
            checked = self.from_dict(self.to_dict())
            value = _locate(_decode(response_body, 1_048_576), _pointer(checked.output_pointer))
            if not isinstance(value, str):
                raise ValueError
            value.encode("utf-8")
            return value
        except (ValueError, TypeError, AttributeError, KeyError, IndexError, RecursionError, OverflowError, UnicodeError, DecimalException):
            raise ValueError("Cannot extract QA JSON response") from None
