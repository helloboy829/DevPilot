"""Immutable, value-free request wiring. No persistence, environment reads or I/O.

A fingerprint detects accidental edits; it is NOT a signature or execution approval.
Every URL/path/query, body and header value must be supplied separately at runtime.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from devpilot.http import RequestSpec


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    return f"{parsed.scheme}://{host}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"


@dataclass(frozen=True)
class RequestTemplate:
    method: str
    origin: str
    # Header names only; no values. Tuples prevent mutation through frozen fields.
    header_names: tuple[str, ...]

    def __post_init__(self):
        try:
            if not isinstance(self.header_names, tuple) or not all(isinstance(name, str) for name in self.header_names):
                raise ValueError
            probe = RequestSpec(url=self.origin, method=self.method, headers=[[name, ""] for name in self.header_names])
            if self.origin != _origin(probe.url):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid request template structure") from None

    def _payload(self) -> dict:
        return {
            "schema": "request-template.v1",
            "scope": "configuration_only",
            "request_version": "request.v1",
            "method": self.method,
            "origin": self.origin,
            "url_ref": "DEVPILOT_REQUEST_URL",
            "body_ref": "DEVPILOT_REQUEST_BODY",
            "headers": [[name, f"DEVPILOT_REQUEST_HEADER_{index}"] for index, name in enumerate(self.header_names, 1)],
        }

    @property
    def fingerprint(self) -> str:
        return fingerprint(self._payload())

    def to_dict(self) -> dict:
        return {**self._payload(), "fingerprint": self.fingerprint}

    @classmethod
    def from_request(cls, spec: RequestSpec) -> RequestTemplate:
        # Revalidate because RequestSpec's legacy list fields are mutable.
        checked = RequestSpec.from_dict(spec.to_dict())
        return cls(checked.method, _origin(checked.url), tuple(name for name, _ in checked.headers))

    @classmethod
    def from_dict(cls, data: dict) -> RequestTemplate:
        try:
            if not isinstance(data, dict) or not isinstance(data.get("headers"), list):
                raise ValueError
            headers = data["headers"]
            if len(headers) > 64 or any(not isinstance(pair, list) or len(pair) != 2 for pair in headers):
                raise ValueError
            template = cls(data["method"], data["origin"], tuple(pair[0] for pair in headers))
            if data != template.to_dict():
                raise ValueError
            return template
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ValueError("Invalid or modified request template") from None

    def resolve(self, values: dict[str, str]) -> RequestSpec:
        """Resolve explicitly provided values without reading env or sending a request.

        Changing values or paths requires fresh target authorization and consent.
        The fingerprint binds wiring, NOT runtime values or successful debugging.
        """
        try:
            payload = self._payload()
            if not isinstance(values, dict):
                raise ValueError
            spec = RequestSpec(
                url=values[payload["url_ref"]],
                method=self.method,
                headers=[[name, values[ref]] for name, ref in payload["headers"]],
                body=values[payload["body_ref"]],
            )
            if _origin(spec.url) != self.origin:
                raise ValueError
            return spec
        except (ValueError, KeyError, TypeError, AttributeError):
            # Never interpolate runtime URLs, bodies or credentials into errors.
            raise ValueError("Missing or invalid request bindings, or target origin changed") from None
