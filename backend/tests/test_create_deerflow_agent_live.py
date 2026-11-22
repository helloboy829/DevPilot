"""Live integration tests for create_deerflow_agent.

Verifies the factory produces a working LangGraph agent that can actually
process messages end-to-end with a real LLM.

Tests marked ``requires_llm`` are skipped in CI or when OPENAI_API_KEY is unset.
"""

import os
import uuid

import pytest
from langchain_core.tools import tool


def _live_llm_tests_enabled():
    return os.getenv("CI", "").lower() not in ("true", "1") and os.getenv("DEVPILOT_RUN_LIVE_LLM_TESTS") == "1" and bool(os.getenv("OPENAI_API_KEY"))


requires_llm = pytest.mark.skipif(
    not _live_llm_tests_enabled(),
    reason="Set DEVPILOT_RUN_LIVE_LLM_TESTS=1 and OPENAI_API_KEY outside CI to call a real LLM",
)


def test_live_llm_tests_require_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("DEVPILOT_RUN_LIVE_LLM_TESTS", raising=False)
    monkeypatch.delenv("CI", raising=False)

    assert not _live_llm_tests_enabled()


def test_live_llm_tests_require_an_api_key(monkeypatch):
    monkeypatch.setenv("DEVPILOT_RUN_LIVE_LLM_TESTS", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CI", raising=False)

    assert not _live_llm_tests_enabled()


def test_live_llm_tests_run_only_with_explicit_opt_in_and_key(monkeypatch):
    monkeypatch.setenv("DEVPILOT_RUN_LIVE_LLM_TESTS", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("CI", raising=False)

    assert _live_llm_tests_enabled()


def test_ci_disables_live_llm_tests_even_with_opt_in(monkeypatch):
    monkeypatch.setenv("DEVPILOT_RUN_LIVE_LLM_TESTS", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CI", "true")

    assert not _live_llm_tests_enabled()


def _make_model():
    """Create a real chat model from environment variables."""
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=os.getenv("E2E_MODEL_ID", "ep-20251211175242-llcmh"),
        base_url=os.getenv("E2E_BASE_URL", "https://ark-cn-beijing.bytedance.net/api/v3"),
        api_key=os.getenv("OPENAI_API_KEY", ""),
        max_tokens=256,
        temperature=0,
    )


# ---------------------------------------------------------------------------
# 1. Minimal creation — model only, no features
# ---------------------------------------------------------------------------
@requires_llm
def test_minimal_agent_responds():
    """create_deerflow_agent(model) produces a graph that returns a response."""
    from deerflow.agents.factory import create_deerflow_agent

    model = _make_model()
    graph = create_deerflow_agent(model, features=None, middleware=[])

    result = graph.invoke(
        {"messages": [("user", "Say exactly: pong")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    assert len(messages) >= 2
    last_msg = messages[-1]
    assert hasattr(last_msg, "content")
    assert len(last_msg.content) > 0


# ---------------------------------------------------------------------------
# 2. With custom tool — verifies tool injection and execution
# ---------------------------------------------------------------------------
@requires_llm
def test_agent_with_custom_tool():
    """Agent can invoke a user-provided tool and return the result."""
    from deerflow.agents.factory import create_deerflow_agent

    @tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    model = _make_model()
    graph = create_deerflow_agent(model, tools=[add], middleware=[])

    result = graph.invoke(
        {"messages": [("user", "Use the add tool to compute 3 + 7. Return only the result.")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    # Should have: user msg, AI tool_call, tool result, AI final
    assert len(messages) >= 3
    last_content = messages[-1].content
    assert "10" in last_content


# ---------------------------------------------------------------------------
# 3. RuntimeFeatures mode — middleware chain runs without errors
# ---------------------------------------------------------------------------
@requires_llm
def test_features_mode_middleware_chain():
    """RuntimeFeatures assembles a working middleware chain that executes."""
    from deerflow.agents.factory import create_deerflow_agent
    from deerflow.agents.features import RuntimeFeatures

    model = _make_model()
    feat = RuntimeFeatures(sandbox=False, auto_title=False, memory=False)
    graph = create_deerflow_agent(model, features=feat)

    result = graph.invoke(
        {"messages": [("user", "What is 2+2?")]},
        config={"configurable": {"thread_id": str(uuid.uuid4())}},
    )

    messages = result.get("messages", [])
    assert len(messages) >= 2
    last_content = messages[-1].content
    assert len(last_content) > 0
