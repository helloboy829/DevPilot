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
