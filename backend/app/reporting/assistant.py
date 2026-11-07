"""Opt-in report advisor: one bounded, tool-free LangChain/LangGraph agent run.

Only allowlisted aggregate metrics cross the model boundary. No general lead
agent, memory, sandbox, target requests, checkpointing or report publication.
"""

import asyncio
import json
from dataclasses import asdict
from typing import Any

from devpilot.reporting import ReportFacts, ReportTemplate, ReportValidationError, facts_digest, validate_advice
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langsmith import tracing_context
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deerflow.models import create_chat_model


class ReportAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    enabled: bool = False
    model_name: str | None = Field(default=None, min_length=1, max_length=100)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_output_tokens: int = Field(default=1200, ge=128, le=4096)


class AssistantUnavailable(Exception):
    """Safe reason code only, never the provider response or submitted data."""


_slots = asyncio.Semaphore(2)  # Per worker; no unbounded wait queue.
_SYSTEM = """You are a bounded AI component-evaluation report advisor.
The input contains unverified, manually entered aggregate metrics only. No raw
evidence, acceptance thresholds or target outputs are available. Do not invent
measurements, acceptance decisions, verified evidence or project details.
Do not declare PASS/FAIL or change metrics. Highlight incomplete coverage,
missing metrics, sample populations and uncertainty; propose human review and
retesting. TTFT is meaningful only for content-streaming calls. Token throughput
is not request throughput. Reply in the requested language, with exactly one
JSON object containing summary (text <=2000 chars), findings and recommendations
(each an array of <=8 strings, each <=600 chars). No Markdown fences, tools or
additional fields. These are unverified suggestions, never an official report.
"""


def _settings(config: Any) -> ReportAgentConfig:
    return ReportAgentConfig.model_validate(getattr(config, "reports_agent", {}))


def get_status(config: Any) -> dict[str, Any]:
    try:
        settings = _settings(config)
    except (ValidationError, TypeError):
        return {"available": False, "reason": "invalid_configuration"}
    if not settings.enabled:
        return {"available": False, "reason": "disabled"}
    if not settings.model_name:
        return {"available": False, "reason": "model_not_configured"}
    if settings.model_name not in {m.name for m in getattr(config, "models", [])}:
        return {"available": False, "reason": "model_not_configured"}
    return {"available": True, "reason": "available", "model_name": settings.model_name}


def build_agent_input(facts: ReportFacts, template: ReportTemplate) -> str:
    # No arbitrary user prose, names, times, references or identity in this DTO.
    payload = {
        "source": "manual_unverified",
        "language": template.language,
        "evaluation_mode": facts.evaluation_mode,
        "effect": asdict(facts.effect) if facts.effect else None,
        "performance": asdict(facts.performance) if facts.performance else None,
        "derived": {
            "case_pass_rate": facts.effect.passed / facts.effect.total if facts.effect else None,
            "success_rate": facts.performance.successful_requests / facts.performance.requests if facts.performance else None,
        },
    }
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


async def run_report_assistant(config: Any, facts: ReportFacts, template: ReportTemplate) -> dict[str, Any]:
    status = get_status(config)
    if not status["available"]:
        raise AssistantUnavailable(status["reason"])
    settings = _settings(config)
    if _slots.locked():
        raise AssistantUnavailable("busy")
    await _slots.acquire()
    try:
        # Suppress implicit LangSmith environment tracing as well as explicit
        # factory callbacks. Operator-supplied providers remain a trust boundary.
        with tracing_context(enabled=False):
            async with asyncio.timeout(settings.timeout_seconds):
                model = create_chat_model(
                    name=settings.model_name,
                    app_config=config,
                    attach_tracing=False,
                    model_overrides={"max_tokens": settings.max_output_tokens, "max_retries": 0, "callbacks": []},
                )
                graph = create_agent(model=model, tools=[], system_prompt=_SYSTEM)
                result = await graph.ainvoke(
                    {"messages": [{"role": "user", "content": build_agent_input(facts, template)}]},
                    config={"recursion_limit": 3, "callbacks": [], "tags": [], "metadata": {}},
                )
        message = result["messages"][-1]
        if not isinstance(message, AIMessage) or message.tool_calls or message.invalid_tool_calls:
            raise AssistantUnavailable("invalid_response")
        if len(message.text) > 16000:
            raise AssistantUnavailable("invalid_response")
        try:
            advice = validate_advice(json.loads(message.text))
        except (ValueError, TypeError, ReportValidationError):
            raise AssistantUnavailable("invalid_response") from None
        return {
            "source": "ai_unverified_advisory",
            "model_name": settings.model_name,
            "facts_sha256": facts_digest(facts),
            "template_id": template.id,
            "template_version": template.version,
            "advice": advice,
        }
    except AssistantUnavailable:
        raise
    except TimeoutError:
        raise AssistantUnavailable("timeout") from None
    except Exception:
        # Do not log/echo a provider error body, prompt, identifiers or metrics.
        raise AssistantUnavailable("provider_error") from None
    finally:
        _slots.release()
