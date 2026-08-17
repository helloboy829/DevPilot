"""报告组装：把 effect / perf 的判定结果组装成 JSON 报告与 DB 摘要。

M6 只出 JSON（``build_component_test_report`` / ``build_run_summary``）；
M7 补 openpyxl 多 sheet（明细 / 人工评审模板 / 加权汇总 / 性能对照）。

本模块零外部依赖，纯函数，可独立单测。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from devpilot.toolkit.effect import EffectReport
from devpilot.toolkit.perf import PerfReport


def build_component_test_report(
    component: Mapping[str, Any],
    *,
    test_type: str,
    params: Mapping[str, Any] | None = None,
    effect_report: EffectReport | None = None,
    perf_report: PerfReport | None = None,
) -> dict[str, Any]:
    """组装一次运行的完整 JSON 报告。

    ``component`` 为组件注册表的一行（含 id/name/transport/validation_type 等）。
    """
    report: dict[str, Any] = {
        "component": {
            "id": component.get("id"),
            "name": component.get("name"),
            "transport": component.get("transport"),
            "validation_type": component.get("validation_type"),
        },
        "test_type": test_type,
        "params": params or {},
    }
    if effect_report is not None:
        report["effect"] = effect_report.to_dict()
    if perf_report is not None:
        report["perf"] = perf_report.to_dict()
    return report


def build_run_summary(
    component: Mapping[str, Any],
    *,
    test_type: str,
    effect_report: EffectReport | None = None,
    perf_report: PerfReport | None = None,
) -> dict[str, Any]:
    """构造写入 run 行 ``result`` 列的紧凑摘要（供列表页/状态轮询展示）。"""
    overall = "PASS"
    if effect_report is not None and perf_report is not None:
        overall = "PASS" if (effect_report.overall == "PASS" and perf_report.overall == "PASS") else "FAIL"
    elif effect_report is not None:
        overall = effect_report.overall
    elif perf_report is not None:
        overall = perf_report.overall

    summary: dict[str, Any] = {
        "overall": overall,
        "component_name": component.get("name"),
        "test_type": test_type,
    }
    if effect_report is not None:
        summary["effect"] = {
            "passed": effect_report.passed,
            "failed": effect_report.failed,
            "manual_review": effect_report.manual_review,
            "auto_pass_rate": effect_report.auto_pass_rate,
            "overall": effect_report.overall,
        }
    if perf_report is not None:
        s = perf_report.summary
        summary["perf"] = {
            "overall": perf_report.overall,
            "concurrency": s.concurrency if s else None,
            "success_rate": s.success_rate if s else None,
            "success_qps": s.success_qps if s else None,
            "throughput_tok_per_s": s.throughput_tok_per_s if s else None,
            "p95_latency_ms": s.latency_p95_ms if s else None,
            "ttft_p95_ms": s.ttft_p95_ms if s else None,
        }
    return summary


__all__ = ["build_component_test_report", "build_run_summary"]
