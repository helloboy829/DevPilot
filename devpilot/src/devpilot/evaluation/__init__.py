"""DevPilot 评测体系（7 字段 LLM-as-Judge）。

纯逻辑（judge/metrics）与模型调用（runner）分离，便于离线单测与真实评测复用。
"""

from devpilot.evaluation.judge import (
    SEVEN_FIELDS,
    EvaluationResult,
    build_prompt,
    compute_overall,
    parse_judge_output,
)
from devpilot.evaluation.metrics import aggregate

__all__ = [
    "SEVEN_FIELDS",
    "EvaluationResult",
    "build_prompt",
    "compute_overall",
    "parse_judge_output",
    "aggregate",
]
