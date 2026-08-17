"""模型调用粘合层：把 judge 的纯逻辑接到 DeerFlow 配置的模型上。

本模块**惰性 import deerflow**（只在真正需要调用模型时才加载），
保证 judge/metrics 两个纯逻辑模块可在无 deerflow 环境下被单测与复用。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from devpilot.evaluation.judge import EvaluationResult, build_prompt, parse_judge_output

logger = logging.getLogger(__name__)

#: 评测专用系统提示：要求评委模型只输出 JSON，关闭思维链噪音。
_JUDGE_SYSTEM_PROMPT = (
    "你是一名研发评审专家。你只输出一个合法 JSON 对象，"
    "不输出任何解释、Markdown 代码块或思维链。"
)


async def _invoke_judge_model(
    prompt: str,
    *,
    model_name: str | None = None,
) -> str:
    """用 DeerFlow 配置的模型执行一次评测调用，返回模型文本输出。"""
    # 惰性 import：deerflow 依赖较重，且本层应保持可独立单测。
    from deerflow.models import create_chat_model

    # thinking 关闭：评审不需要思维链，且可避免输出夹带 <think> 块。
    model = create_chat_model(name=model_name, thinking_enabled=False, attach_tracing=False)
    response = await model.ainvoke(
        [
            ("system", _JUDGE_SYSTEM_PROMPT),
            ("human", prompt),
        ]
    )
    content = getattr(response, "content", None)
    if isinstance(content, list):
        # 多模态/分块内容：拼出文本部分。
        parts = []
        for piece in content:
            if isinstance(piece, str):
                parts.append(piece)
            elif isinstance(piece, Mapping) and piece.get("type") == "text":
                parts.append(str(piece.get("text", "")))
        content = "".join(parts)
    return str(content or "")


async def judge_with_model(
    requirement: str,
    artifacts: Mapping[str, str],
    *,
    test_summary: str = "",
    transcript_excerpt: str = "",
    model_name: str | None = None,
) -> EvaluationResult:
    """构造 prompt → 调用模型 → 解析 7 字段。

    失败时（模型不可达等）返回 ``overall=0`` 且 report 记录错误，不抛出，
    以便评测链路 fail-open，不阻断研发主流程。
    """
    prompt = build_prompt(
        requirement=requirement,
        artifacts=artifacts,
        test_summary=test_summary,
        transcript_excerpt=transcript_excerpt,
    )
    try:
        raw = await _invoke_judge_model(prompt, model_name=model_name)
    except Exception as exc:  # noqa: BLE001 - 评测 fail-open，记录并降级。
        logger.exception("评测模型调用失败")
        return EvaluationResult(
            overall=0.0,
            report=f"[评测失败] 模型调用异常：{exc}",
        )
    return parse_judge_output(raw)


__all__ = ["judge_with_model", "_invoke_judge_model"]
