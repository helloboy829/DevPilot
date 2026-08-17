"""评测指标聚合：纯逻辑、零依赖。

对一组 ``EvaluationResult`` 做统计，产出：
    - 各字段均值 / 通过率
    - 幻觉率分布（供「过时偏好」/幻觉审计）
    - 按任务的明细（供报表）
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from devpilot.evaluation.judge import EvaluationResult


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def aggregate(
    results: Iterable[EvaluationResult],
    *,
    pass_threshold: float = 60.0,
) -> dict:
    """聚合多个评测结果为统计摘要。

    ``pass_threshold``：``overall >= threshold`` 视为「通过」，用于计算通过率。
    """
    items = list(results)
    n = len(items)
    if n == 0:
        return {
            "count": 0,
            "avg_task_score": 0.0,
            "avg_code_score": 0.0,
            "avg_test_score": 0.0,
            "avg_hallucination_rate": 0.0,
            "avg_confidence": 0.0,
            "avg_overall": 0.0,
            "pass_rate": 0.0,
        }

    overalls = [r.overall for r in items]
    passed = sum(1 for o in overalls if o >= pass_threshold)
    return {
        "count": n,
        "avg_task_score": round(_mean([r.task_score for r in items]), 2),
        "avg_code_score": round(_mean([r.code_score for r in items]), 2),
        "avg_test_score": round(_mean([r.test_score for r in items]), 2),
        "avg_hallucination_rate": round(_mean([r.hallucination_rate for r in items]), 4),
        "avg_confidence": round(_mean([r.confidence for r in items]), 2),
        "avg_overall": round(_mean(overalls), 2),
        "pass_rate": round(passed / n, 4),
    }


__all__ = ["aggregate"]
