"""技术性人工/裁判一致性统计：纯逻辑、零网络、零模型调用。

只统计同时给出确定性标签（pass/fail）的配对；缺失或 uncertain 的配对显式
排除并计数，绝不当作一致、零差异或批准。
"""

from __future__ import annotations

_MAX_ITEMS = 10_000
_LABELS = frozenset({"pass", "fail", "uncertain"})
_FIELDS = frozenset({"human", "judge"})


def compute_judge_calibration(items):
    """Return a fixed calibration projection for paired human/judge labels.

    Items are strict ``{"human": label|None, "judge": label|None}`` mappings.
    Agreement is computed only over definitive pairs; no definitive pairs means
    ``insufficient`` with ``None`` values, never zero.
    """
    if not isinstance(items, list) or len(items) > _MAX_ITEMS:
        raise ValueError("Invalid calibration items")
    counts = {"total": len(items), "both_definitive": 0, "human_missing": 0, "judge_missing": 0, "uncertain_excluded": 0}
    confusion = {"pass_pass": 0, "pass_fail": 0, "fail_pass": 0, "fail_fail": 0}
    for item in items:
        if not isinstance(item, dict) or set(item) != _FIELDS:
            raise ValueError("Invalid calibration item")
        human, judge = item["human"], item["judge"]
        if any(value is not None and (type(value) is not str or value not in _LABELS) for value in (human, judge)):
            raise ValueError("Invalid calibration label")
        if human is None:
            counts["human_missing"] += 1
            continue
        if judge is None:
            counts["judge_missing"] += 1
            continue
        if human == "uncertain" or judge == "uncertain":
            counts["uncertain_excluded"] += 1
            continue
        counts["both_definitive"] += 1
        confusion[human + "_" + judge] += 1
    definitive = counts["both_definitive"]
    if definitive == 0:
        agreement = {"status": "insufficient", "numerator": None, "denominator": 0, "value": None, "reason": "no_definitive_pairs"}
    else:
        matched = confusion["pass_pass"] + confusion["fail_fail"]
        agreement = {"status": "available", "numerator": matched, "denominator": definitive, "value": round(matched / definitive, 4), "reason": None}
    return {
        "schema": "qa-judge-calibration.v1",
        "scope": "technical_judge_calibration_only",
        "counts": counts,
        "confusion": confusion,
        "agreement": agreement,
        "approval": "not_approved",
    }


__all__ = ["compute_judge_calibration"]
