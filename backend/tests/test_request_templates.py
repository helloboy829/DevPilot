"""Synthetic, value-free request template contracts; no outbound calls."""

import copy
import json

import pytest
from devpilot.http import RequestSpec
from devpilot.request_templates import RequestTemplate


def fixture_spec():
    return RequestSpec(url="https://example.test/private-SYNTHETIC_PATH?token=SYNTHETIC_QUERY", method="POST", headers=[["Authorization", "Bearer SYNTHETIC_HEADER"], ["X-Api-Key", "SYNTHETIC_KEY"]], body='{"token":"SYNTHETIC_BODY"}')


def test_template_excludes_every_request_value_and_is_content_addressed():
    template = RequestTemplate.from_request(fixture_spec())
    exported = template.to_dict()
    serialized = json.dumps(exported)
    assert "SYNTHETIC" not in serialized
    assert "private-" not in serialized
    assert exported["scope"] == "configuration_only"
    assert len(exported["fingerprint"]) == 64
    assert RequestTemplate.from_dict(exported) == template
    assert "Authorization" in serialized
    assert "DEVPILOT_REQUEST_HEADER_1" in serialized
    assert RequestTemplate.from_request(fixture_spec()).fingerprint == template.fingerprint


def test_runtime_resolution_is_explicit_preserves_spec_and_checks_origin():
    template = RequestTemplate.from_request(fixture_spec())
    values = {"DEVPILOT_REQUEST_URL": fixture_spec().url, "DEVPILOT_REQUEST_BODY": fixture_spec().body, "DEVPILOT_REQUEST_HEADER_1": "Bearer SYNTHETIC_HEADER", "DEVPILOT_REQUEST_HEADER_2": "SYNTHETIC_KEY"}
    assert template.resolve(values) == fixture_spec()
    for bad_url in ("https://other.test/private", "http://example.test/private", "https://example.test:444/private", "https://name:secret@example.test/private"):
        with pytest.raises(ValueError) as error:
            template.resolve({**values, "DEVPILOT_REQUEST_URL": bad_url})
        assert bad_url not in str(error.value)
    with pytest.raises(ValueError):
        template.resolve({})
    with pytest.raises(ValueError):
        template.resolve({**values, "DEVPILOT_REQUEST_HEADER_1": "bad\r\nHost: secret"})


def test_template_cannot_mutate_and_rejects_tampered_or_unknown_fields():
    template = RequestTemplate.from_request(fixture_spec())
    exported = template.to_dict()
    for field, value in (("method", "DELETE"), ("origin", "https://other.test"), ("scope", "approved"), ("schema", "unknown"), ("secret", "SYNTHETIC")):
        changed = {**exported, field: value}
        with pytest.raises(ValueError):
            RequestTemplate.from_dict(changed)
    exported["headers"][0][0] = "Modified"
    assert template.to_dict()["headers"][0][0] == "Authorization"
    with pytest.raises(AttributeError):
        template.method = "DELETE"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(headers=[["Host", "DEVPILOT_REQUEST_HEADER_1"]]),
        lambda x: x.update(url_ref="arbitrary"),
        lambda x: x.update(body_ref="arbitrary"),
        lambda x: x.update(headers=[["Accept", "arbitrary"]]),
        lambda x: x.update(origin="https://example.test/path"),
        lambda x: x.update(headers="bad"),
        lambda x: x.update(method=None),
    ],
)
def test_invalid_structure_rejected_even_with_recomputed_hash(mutate):
    from devpilot.request_templates import fingerprint

    data = copy.deepcopy(RequestTemplate.from_request(fixture_spec()).to_dict())
    data.pop("fingerprint")
    mutate(data)
    data["fingerprint"] = fingerprint(data)
    with pytest.raises(ValueError):
        RequestTemplate.from_dict(data)


def test_origin_canonicalization_and_empty_request():
    template = RequestTemplate.from_request(RequestSpec(url="https://EXAMPLE.test:443/a"))
    assert template.origin == "https://example.test:443"
    spec = template.resolve({"DEVPILOT_REQUEST_URL": "https://example.test/b", "DEVPILOT_REQUEST_BODY": ""})
    assert spec.body == "" and spec.headers == []
    assert RequestTemplate.from_dict(template.to_dict()).fingerprint == template.fingerprint
