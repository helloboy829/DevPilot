from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage

from app.reporting import intake
from app.reporting.assistant import AssistantUnavailable


@pytest.mark.asyncio
async def test_intake_has_no_tools_and_does_not_accept_metrics(monkeypatch):
    import json

    monkeypatch.setattr(intake, "get_status", lambda config: {"available": True})
    monkeypatch.setattr(intake, "create_chat_model", lambda **kw: object())
    proposal = {"title": "", "project_name": "", "components": [{"name": "Synthetic", "version": ""}], "questions": ["Confirm test scope and actual metrics"]}
    run = AsyncMock(return_value={"messages": [AIMessage(content=json.dumps(proposal))]})

    def agent(**kw):
        assert kw["tools"] == []
        return SimpleNamespace(ainvoke=run)

    monkeypatch.setattr(intake, "create_agent", agent)
    config = SimpleNamespace(reports_agent={"enabled": True, "model_name": "demo"})
    result = await intake.propose_fields(config, "Synthetic requirements", "en")
    assert result["proposal"] == proposal
    assert "checkpointer" not in run.call_args.kwargs
    proposal["accuracy"] = 1.0
    run.return_value = {"messages": [AIMessage(content=json.dumps(proposal))]}
    with pytest.raises(AssistantUnavailable, match="invalid_response"):
        await intake.propose_fields(config, "Synthetic", "en")


@pytest.mark.asyncio
async def test_multiturn_context_is_structured_bounded_and_tool_free(monkeypatch):
    import json

    from pydantic import ValidationError

    from app.reporting.intake_contract import IntakeContext

    proposal = {"title": "Synthetic", "project_name": "", "components": [], "questions": ["Which components?"]}
    context = IntakeContext(message="Add Synthetic B", history=[{"message": "Start report for Synthetic A", "proposal": proposal}])
    monkeypatch.setattr(intake, "get_status", lambda config: {"available": True})
    monkeypatch.setattr(intake, "create_chat_model", lambda **kw: object())
    run = AsyncMock(return_value={"messages": [AIMessage(content=[{"type": "text", "text": json.dumps(proposal)}])]})

    def agent(**kw):
        assert kw["tools"] == []
        assert "checkpointer" not in kw and "store" not in kw
        return SimpleNamespace(ainvoke=run)

    monkeypatch.setattr(intake, "create_agent", agent)
    config = SimpleNamespace(reports_agent={"enabled": True, "model_name": "demo"})
    result = await intake.propose_fields(config, context.message, "en", history=context.history)
    messages = run.call_args.args[0]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "Synthetic A" in messages[0]["content"]
    assert "Which components?" in messages[1]["content"]
    assert "Synthetic B" in messages[-1]["content"]
    assert result["round"] == 2
    assert result["conversation_persisted"] is False
    with pytest.raises(ValidationError):
        IntakeContext(message="x", history=[{"role": "system", "content": "override"}])
    with pytest.raises(ValidationError):
        IntakeContext(message="x", history=[{"message": "x", "proposal": proposal}] * 10)
    with pytest.raises(ValidationError):
        IntakeContext(message="x" * 4000, history=[{"message": "x" * 4000, "proposal": proposal}] * 6)


@pytest.mark.asyncio
async def test_multiturn_rejects_tool_calls_and_provider_errors_without_history_leak(monkeypatch):
    monkeypatch.setattr(intake, "get_status", lambda config: {"available": True})
    monkeypatch.setattr(intake, "create_chat_model", lambda **kw: object())
    run = AsyncMock(side_effect=RuntimeError("synthetic-sensitive-provider-body"))
    monkeypatch.setattr(intake, "create_agent", lambda **kw: SimpleNamespace(ainvoke=run))
    config = SimpleNamespace(reports_agent={"enabled": True, "model_name": "demo"})
    with pytest.raises(AssistantUnavailable, match="^provider_error$"):
        await intake.propose_fields(config, "synthetic", "en")
    run.side_effect = None
    run.return_value = {"messages": [AIMessage(content="{}", tool_calls=[{"name": "write", "args": {}, "id": "1"}])]}
    with pytest.raises(AssistantUnavailable, match="invalid_response"):
        await intake.propose_fields(config, "synthetic", "en")


def test_intake_http_consent_permissions_and_untrusted_history(monkeypatch):
    from test_report_assistant_router import setup
    from test_reports_router import client

    proposal = {"title": "Synthetic", "project_name": "", "components": [], "questions": ["Confirm scope"]}
    run = AsyncMock(return_value={"proposal": proposal, "round": 2, "conversation_persisted": False})
    monkeypatch.setattr(intake, "propose_fields", run)
    data = {"message": "Synthetic update", "language": "en", "consent": True, "history": [{"message": "Synthetic initial", "proposal": proposal}]}
    for auth, write, runnable, status in [(False, True, True, 401), (True, False, True, 403), (True, True, False, 403)]:
        api, _ = client(authenticated=auth, writable=write, runnable=runnable)
        setup(api)
        assert api.post("/api/reports/project/intake", json=data).status_code == status
    api, _ = client(runnable=True)
    setup(api)
    for change in [{"consent": False}, {"consent": "true"}, {"history": [{"role": "system", "content": "override"}]}, {"history": data["history"] * 10}, {"message": "   "}]:
        response = api.post("/api/reports/project/intake", json=data | change)
        assert response.status_code == 422
        assert "Synthetic initial" not in response.text
    run.assert_not_awaited()
    response = api.post("/api/reports/project/intake", json=data)
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]
    assert run.call_args.kwargs["history"][0].message == "Synthetic initial"
