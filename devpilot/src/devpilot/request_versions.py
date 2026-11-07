"""Deeply immutable request values. Protected serialization is NOT a public DTO.

No environment access, storage or network. The value-free template describes wiring,
not execution approval or a hash of credentials. Construct a fresh RequestSpec for
execution only after authorization, consent and outbound-policy checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from devpilot.http import RequestSpec
from devpilot.request_templates import RequestTemplate


@dataclass(frozen=True, slots=True)
class FrozenRequest:
    url: str = field(repr=False)
    method: str
    headers: tuple[tuple[str, str], ...] = field(repr=False)
    body: str = field(repr=False)

    def __post_init__(self):
        try:
            if not isinstance(self.headers, tuple) or any(not isinstance(pair, tuple) or len(pair) != 2 for pair in self.headers):
                raise ValueError
            self.to_request()
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid immutable request definition") from None

    @classmethod
    def from_request(cls, spec: RequestSpec) -> FrozenRequest:
        try:
            checked = RequestSpec.from_dict(spec.to_dict())
            return cls(checked.url, checked.method, tuple(tuple(pair) for pair in checked.headers), checked.body)
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid immutable request definition") from None

    def to_request(self) -> RequestSpec:
        return RequestSpec(url=self.url, method=self.method, headers=[list(pair) for pair in self.headers], body=self.body)

    @property
    def template(self) -> RequestTemplate:
        return RequestTemplate.from_request(self.to_request())

    def to_protected_dict(self) -> dict:
        """Contains secrets. Only for an authenticated encryption/storage boundary."""
        return self.to_request().to_dict()

    @classmethod
    def from_protected_dict(cls, payload: dict) -> FrozenRequest:
        try:
            return cls.from_request(RequestSpec.from_dict(payload))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid immutable request definition") from None
