"""Pinned pure projection of an already-rendered frozen QA HTTP request.

No input/gold lookup, rendering, environment, transport, budget reservation or
execution authority. Values are sensitive: this is NOT a public/export DTO.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from devpilot.request_versions import FrozenRequest

_VERSION = "qa-json-request.v1"


@dataclass(frozen=True, slots=True, init=False)
class QAJSONRequest:
    """Immutable transport values, with the collector's exact encoding policy.

    Preserve URL/method/body and header case/order/duplicates. Append identity
    only when no case-insensitive Accept-Encoding header exists. An original
    maximum of 64 headers can therefore yield 65, as in the existing collector;
    the projection is not a newly persisted FrozenRequest or RequestSpec.

    Content encoding stays lazy: callers access content within their total
    attempt deadline, as before. Bounded validation happens before any client.
    No JSON parse/render, URL canonicalization, credential resolution or consent
    is performed. Do not log/serialize the data fields despite repr suppression.
    """

    url: str = field(repr=False)
    method: str
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    body: str = field(repr=False)
    version: str = _VERSION

    def __init__(self, request: FrozenRequest, *, version: str = _VERSION):
        try:
            if version != _VERSION or not isinstance(request, FrozenRequest):
                raise ValueError
            checked = request.to_request()
            headers = tuple(tuple(pair) for pair in checked.headers)
            if not any(name.lower() == "accept-encoding" for name, _ in headers):
                headers = (*headers, ("Accept-Encoding", "identity"))
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise ValueError("Invalid QA JSON request") from None
        object.__setattr__(self, "url", checked.url)
        object.__setattr__(self, "method", checked.method)
        object.__setattr__(self, "headers", headers)
        object.__setattr__(self, "body", checked.body)
        object.__setattr__(self, "version", _VERSION)

    @property
    def content(self) -> bytes:
        """Exact UTF-8 request content, not a network-send or billing receipt."""
        return self.body.encode("utf-8")
