"""Report assistant HTTP boundaries: explicit consent, auth, no model fallback."""

from unittest.mock import AsyncMock

from test_reports_router import client, payload

from app.gateway.deps import get_config
from app.reporting import assistant


def setup(api, **settings):
    from types import SimpleNamespace

    api.app.dependency_overrides[get_config] = lambda: SimpleNamespace(reports_agent={"enabled": True, "model_name": "synthetic", **settings}, models=[SimpleNamespace(name="synthetic")])


def test_agent_status_disabled_by_default():
    api, _ = client()
    setup(api, enabled=False)
    assert api.get("/api/reports/assistant").json()["available"] is False


def test_agent_requires_consent_and_write_and_run_permission(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr(assistant, "run_report_assistant", run)
    api, _ = client(authenticated=False)
    setup(api)
    assert api.post("/api/reports/assistant", json=payload() | {"consent": True}).status_code == 401
    api, _ = client(writable=False)
    setup(api)
    assert api.post("/api/reports/assistant", json=payload() | {"consent": True}).status_code == 403
    api, _ = client()
    setup(api)
    assert api.post("/api/reports/assistant", json=payload() | {"consent": True}).status_code == 403
    run.assert_not_awaited()


def test_unconfirmed_advisory_cannot_be_attached_and_facts_must_match():
    api, _ = client()
    data = payload()
    result = api.post("/api/reports/preview", json=data).json()
    attachment = dict(
        summary="Synthetic draft",
        findings=["Review evidence"],
        recommendations=["Review pending cases"],
        model_name="synthetic",
        facts_sha256=result["manifest"]["facts_sha256"],
        template_id=data["template_id"],
        template_version=data["template_version"],
        human_confirmed=False,
    )
    assert api.post("/api/reports/preview", json=data | {"advisory": attachment}).status_code == 422
    attachment["human_confirmed"] = True
    response = api.post("/api/reports/preview", json=data | {"advisory": attachment})
    assert response.status_code == 200
    assert response.json()["advisory"]["source"] == "client_supplied_ai_advice_unverified"
    assert response.json()["advisory"]["human_confirmed"] is True
    assert response.json()["manifest"]["advisory_sha256"]
    assert response.json()["facts"] == result["facts"]
    assert "Synthetic draft" in response.json()["markdown"]
    data["facts"]["title"] = "Changed synthetic title"
    assert api.post("/api/reports/preview", json=data | {"advisory": attachment}).status_code == 422
    attachment["template_version"] = "other"
    assert api.post("/api/reports/preview", json=payload() | {"advisory": attachment}).status_code == 422


def test_assistant_success_explicit_consent_and_no_model_on_bad_facts(monkeypatch):
    api, _ = client(runnable=True)
    setup(api)
    run = AsyncMock(return_value={"advice": {"summary": "Synthetic", "findings": [], "recommendations": []}})
    monkeypatch.setattr(assistant, "run_report_assistant", run)
    for consent in [None, False, "true"]:
        data = payload() | ({} if consent is None else {"consent": consent})
        assert api.post("/api/reports/assistant", json=data).status_code == 422
    invalid = payload()
    invalid["facts"]["effect"]["total"] = 0
    assert api.post("/api/reports/assistant", json=invalid | {"consent": True}).status_code == 422
    run.assert_not_awaited()
    response = api.post("/api/reports/assistant", json=payload() | {"consent": True})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    run.assert_awaited_once()


def test_disabled_and_busy_have_safe_http_errors(monkeypatch):
    api, _ = client(runnable=True)
    setup(api, enabled=False)
    run = AsyncMock()
    monkeypatch.setattr(assistant, "run_report_assistant", run)
    assert api.post("/api/reports/assistant", json=payload() | {"consent": True}).status_code == 503
    run.assert_not_awaited()
    setup(api)
    for reason, status in [("busy", 429), ("timeout", 504), ("invalid_response", 502), ("provider_error", 502)]:
        run.side_effect = assistant.AssistantUnavailable(reason)
        response = api.post("/api/reports/assistant", json=payload() | {"consent": True})
        assert response.status_code == status
        assert "no-store" in response.headers["cache-control"]
