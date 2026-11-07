"""Synthetic immutable request and protected-value contract tests; no network."""

import copy
import json

import pytest
from cryptography.fernet import Fernet
from devpilot.http import RequestSpec
from devpilot.request_versions import FrozenRequest

from app.evaluation.request_protection import RequestProtection, RequestProtectionError, RequestProtectionUnavailable


def sample_request():
    return RequestSpec(url="https://example.test/private-SYNTHETIC_PATH?key=SYNTHETIC_QUERY", method="POST", headers=[["Authorization", "Bearer SYNTHETIC_TOKEN"], ["X-Api-Key", "SYNTHETIC_KEY"]], body='{"question":"SYNTHETIC_BODY"}')


def binding(version="r1", owner="owner"):
    return {"owner_id": owner, "project_id": "p1", "component_id": "c1", "request_version_id": version}


def test_frozen_request_defensively_copies_both_directions_and_hides_repr():
    original = sample_request()
    frozen = FrozenRequest.from_request(original)
    original.headers[0][1] = "CHANGED"
    assert frozen.to_request().headers[0][1] == "Bearer SYNTHETIC_TOKEN"
    restored = frozen.to_request()
    restored.headers.clear()
    assert len(frozen.to_request().headers) == 2
    assert "SYNTHETIC" not in repr(frozen)
    assert "Authorization" not in repr(frozen)
    assert frozen.template.to_dict()["scope"] == "configuration_only"
    assert "SYNTHETIC" not in json.dumps(frozen.template.to_dict())
    with pytest.raises(AttributeError):
        frozen.method = "DELETE"


def test_frozen_request_round_trip_and_strict_revalidation():
    frozen = FrozenRequest.from_request(sample_request())
    data = frozen.to_protected_dict()
    assert FrozenRequest.from_protected_dict(data) == frozen
    assert frozen.to_request() == sample_request()
    data["headers"][0][1] = "CHANGED"
    assert frozen.to_request() == sample_request()
    for change in ({"version": "future"}, {"unexpected": "SYNTHETIC_SECRET"}, {"headers": [["Host", "SYNTHETIC_SECRET"]]}, {"url": "file:///SYNTHETIC_SECRET"}):
        with pytest.raises(ValueError) as error:
            FrozenRequest.from_protected_dict({**frozen.to_protected_dict(), **change})
        assert "SYNTHETIC" not in str(error.value)
    bad = sample_request()
    bad.headers.append(["Authorization", "bad\r\nHost: SYNTHETIC_SECRET"])
    with pytest.raises(ValueError):
        FrozenRequest.from_request(bad)


def test_frozen_direct_construction_requires_deep_immutable_headers():
    with pytest.raises(ValueError):
        FrozenRequest(url="https://example.test", method="GET", headers=[["X-Test", "secret"]], body="")
    frozen = FrozenRequest(url="https://example.test", method="GET", headers=(("X-Test", "value"),), body="")
    assert copy.deepcopy(frozen) == frozen


def test_protection_encrypts_all_values_randomizes_and_binds_context():
    protector = RequestProtection(Fernet.generate_key())
    frozen = FrozenRequest.from_request(sample_request())
    first = protector.seal(frozen, binding())
    second = protector.seal(frozen, binding())
    assert first != second
    assert all(value not in first for value in ("SYNTHETIC", "example.test", "Authorization"))
    assert protector.open(first, binding()) == frozen
    for context in (binding("r2"), binding(owner="other"), {**binding(), "project_id": "p2"}, {**binding(), "component_id": "c2"}):
        with pytest.raises(RequestProtectionError):
            protector.open(first, context)
    for damaged in ("SYNTHETIC_INVALID_CIPHER", first[:-4], first[:50] + "AAAA" + first[54:]):
        with pytest.raises(RequestProtectionError) as error:
            protector.open(damaged, binding())
        assert "SYNTHETIC" not in str(error.value)
    with pytest.raises(RequestProtectionError):
        RequestProtection(Fernet.generate_key()).open(first, binding())
    assert "SYNTHETIC" not in repr(protector)


@pytest.mark.parametrize("changes", [{"schema": "future"}, {"binding": binding("other")}, {"unknown": "SYNTHETIC_SECRET"}, {"request": {"url": "file:///SYNTHETIC_SECRET"}}])
def test_protection_revalidates_authenticated_envelope(changes):
    key = Fernet.generate_key()
    protector = RequestProtection(key)
    envelope = {"schema": "protected-request.v1", "binding": binding(), "request": sample_request().to_dict()}
    token = Fernet(key).encrypt(json.dumps({**envelope, **changes}).encode()).decode()
    with pytest.raises(RequestProtectionError) as error:
        protector.open(token, binding())
    assert "SYNTHETIC" not in str(error.value)


def test_protection_requires_operator_key_and_never_falls_back(monkeypatch):
    monkeypatch.delenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RequestProtectionUnavailable):
        RequestProtection.from_environment()
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", "SYNTHETIC_INVALID_KEY")
    with pytest.raises(RequestProtectionUnavailable) as error:
        RequestProtection.from_environment()
    assert "SYNTHETIC" not in str(error.value)
    monkeypatch.setenv("DEVPILOT_REQUEST_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert isinstance(RequestProtection.from_environment(), RequestProtection)


def test_request_value_whitespace_is_not_normalized_by_intake():
    from app.evaluation.request_versions import RequestVersionCreate

    request = {"url": "https://example.test", "method": "POST", "headers": [["X-Test", " leading and trailing "]], "body": "  content\n "}
    parsed = RequestVersionCreate(version_label="label", confirmed=True, request=request)
    assert parsed.request["body"] == request["body"]
    assert parsed.request["headers"] == request["headers"]
