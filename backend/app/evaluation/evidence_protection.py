"""Domain-separated encryption for extracted output and human review notes.

Uses the operator-owned request-storage key, never a model/JWT secret or an
implicitly generated key. Callers must scope DB reads and audit plaintext opens.
Neither payloads nor plaintext fingerprints belong in public metadata/logs.
"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from app.evaluation.request_protection import RequestProtectionError, RequestProtectionUnavailable


class EvidenceProtection:
    def __init__(self, key: bytes):
        try:
            self._cipher = Fernet(key)
        except (ValueError, TypeError):
            raise RequestProtectionUnavailable("Evidence protection key is missing or invalid; contact the operator") from None

    @classmethod
    def from_environment(cls):
        try:
            key = os.environ["DEVPILOT_REQUEST_ENCRYPTION_KEY"].encode("ascii")
        except (KeyError, UnicodeError):
            raise RequestProtectionUnavailable("Evidence protection key is missing or invalid; contact the operator") from None
        return cls(key)

    @staticmethod
    def _binding(binding):
        names = {"owner_id", "project_id", "run_id", "ordinal", "sample_id", "plan_hash", "observation_hash"}
        if (
            not isinstance(binding, dict)
            or set(binding) != names
            or any(type(binding[name]) is not str or not 1 <= len(binding[name]) <= 80 for name in names - {"ordinal"})
            or type(binding["ordinal"]) is not int
            or not 1 <= binding["ordinal"] <= 10_000
        ):
            raise RequestProtectionError("Invalid evidence context")
        return dict(binding)

    @staticmethod
    def _payload(kind, payload):
        if kind == "output":
            if type(payload) is not str or not payload.strip() or len(payload.encode("utf-8")) > 1_048_576:
                raise ValueError
        elif kind == "review":
            if (
                type(payload) is not dict
                or set(payload) != {"revision", "decision", "note", "actor", "case_hash"}
                or type(payload["revision"]) is not int
                or not 1 <= payload["revision"] <= 100
                or payload["decision"] not in {"pass", "fail", "uncertain"}
                or any(type(payload[name]) is not str or not payload[name].strip() for name in ("note", "actor", "case_hash"))
                or len(payload["note"]) > 2000
                or len(payload["actor"]) > 64
                or len(payload["case_hash"]) != 64
            ):
                raise ValueError
        else:
            raise ValueError
        return payload

    def seal(self, kind, payload, binding):
        try:
            envelope = {"schema": "protected-qa-evidence.v1", "kind": kind, "binding": self._binding(binding), "payload": self._payload(kind, payload)}
            return self._cipher.encrypt(json.dumps(envelope, ensure_ascii=True, separators=(",", ":")).encode()).decode("ascii")
        except (ValueError, TypeError, UnicodeError):
            raise RequestProtectionError("Evidence cannot be protected") from None

    def open(self, kind, token, binding):
        try:
            context = self._binding(binding)
            if type(token) is not str or len(token) > 9_000_000:
                raise ValueError
            envelope = json.loads(self._cipher.decrypt(token.encode("ascii")))
            if type(envelope) is not dict or set(envelope) != {"schema", "kind", "binding", "payload"} or envelope["schema"] != "protected-qa-evidence.v1" or envelope["kind"] != kind or envelope["binding"] != context:
                raise ValueError
            return self._payload(kind, envelope["payload"])
        except (ValueError, TypeError, KeyError, UnicodeError, InvalidToken):
            raise RequestProtectionError("Evidence cannot be opened or failed integrity checks") from None
