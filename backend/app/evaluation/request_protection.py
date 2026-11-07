"""App-owned encryption boundary for complete request values, not just auth headers.

The operator key is separate from model keys/JWT secrets. Never auto-generate an
unrecoverable ephemeral key. Envelope context prevents ciphertext transplantation.
No plaintext fingerprint, disk access, network or implicit environment resolution.
"""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken
from devpilot.request_versions import FrozenRequest


class RequestProtectionUnavailable(Exception):
    pass


class RequestProtectionError(Exception):
    pass


class RequestProtection:
    def __init__(self, key: bytes):
        try:
            self._cipher = Fernet(key)
        except (ValueError, TypeError):
            raise RequestProtectionUnavailable("Request protection key is missing or invalid; contact the operator") from None

    @classmethod
    def from_environment(cls):
        try:
            key = os.environ["DEVPILOT_REQUEST_ENCRYPTION_KEY"].encode("ascii")
        except (KeyError, UnicodeError):
            raise RequestProtectionUnavailable("Request protection key is missing or invalid; contact the operator") from None
        return cls(key)

    @staticmethod
    def _binding(binding):
        if not isinstance(binding, dict) or set(binding) != {"owner_id", "project_id", "component_id", "request_version_id"} or any(not isinstance(value, str) or not 1 <= len(value) <= 64 for value in binding.values()):
            raise RequestProtectionError("Invalid protected request context")
        return dict(binding)

    def seal(self, frozen: FrozenRequest, binding: dict) -> str:
        envelope = {"schema": "protected-request.v1", "binding": self._binding(binding), "request": frozen.to_protected_dict()}
        return self._cipher.encrypt(json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode()).decode("ascii")

    def open(self, token: str, binding: dict) -> FrozenRequest:
        try:
            expected = self._binding(binding)
            if not isinstance(token, str) or len(token) > 6_000_000:
                raise ValueError
            envelope = json.loads(self._cipher.decrypt(token.encode("ascii")))
            if not isinstance(envelope, dict) or set(envelope) != {"schema", "binding", "request"} or envelope["schema"] != "protected-request.v1" or envelope["binding"] != expected:
                raise ValueError
            return FrozenRequest.from_protected_dict(envelope["request"])
        except (ValueError, TypeError, KeyError, AttributeError, InvalidToken):
            raise RequestProtectionError("Protected request cannot be opened or its binding changed") from None
