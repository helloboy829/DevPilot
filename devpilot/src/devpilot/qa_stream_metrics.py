"""技术性流式指标投影：TTFT 与内容吞吐，纯逻辑、零网络。

只对有界的技术观测做换算；缺失、不可观测或不适用的指标一律显式
``unavailable`` / ``not_applicable``，绝不填 0，也不代表质量 PASS 或批准。
"""

from __future__ import annotations

_MAX_MS = 9_007_199_250_000_000
_MODES = frozenset({"streaming", "non_streaming"})
_OUTCOMES = frozenset({"collected", "technical_incomplete"})
_UNITS = frozenset({"chars", "tokens"})
_FIELDS = frozenset(
    {
        "mode",
        "outcome",
        "started_at_ms",
        "first_content_at_ms",
        "last_content_at_ms",
        "finished_at_ms",
        "content_units",
        "content_unit",
    }
)


def _instant(value):
    if type(value) is not int or not 1 <= value <= _MAX_MS:
        raise ValueError("Invalid stream timestamp")
    return value


def _optional_instant(value):
    return None if value is None else _instant(value)


def compute_stream_metrics(observation):
    """Return a fixed technical projection for one observable stream.

    ``ttft`` and ``throughput`` carry an explicit status; unavailable values are
    ``None`` rather than zero. Any malformed, incoherent or unknown input fails
    closed with ``ValueError``.
    """
    if not isinstance(observation, dict) or set(observation) != _FIELDS:
        raise ValueError("Invalid stream observation")
    mode = observation["mode"]
    outcome = observation["outcome"]
    unit = observation["content_unit"]
    if mode not in _MODES or outcome not in _OUTCOMES or unit not in _UNITS:
        raise ValueError("Invalid stream observation")
    started = _instant(observation["started_at_ms"])
    finished = _instant(observation["finished_at_ms"])
    first = _optional_instant(observation["first_content_at_ms"])
    last = _optional_instant(observation["last_content_at_ms"])
    units = observation["content_units"]
    if type(units) is not int or not 0 <= units <= _MAX_MS:
        raise ValueError("Invalid stream content units")
    if started > finished:
        raise ValueError("Invalid stream window")
    if first is not None and not started <= first <= finished:
        raise ValueError("Invalid stream window")
    if last is not None and (first is None or not first <= last <= finished):
        raise ValueError("Invalid stream window")

    ttft = {"status": "unavailable", "ms": None, "reason": "technical_incomplete"}
    throughput = {"status": "unavailable", "unit": unit, "units": None, "duration_ms": None, "value": None, "reason": "technical_incomplete"}
    if outcome == "collected":
        if mode == "non_streaming":
            ttft = {"status": "not_applicable", "ms": None, "reason": "non_streaming_response"}
            throughput = {"status": "not_applicable", "unit": unit, "units": None, "duration_ms": None, "value": None, "reason": "non_streaming_response"}
        else:
            if first is None:
                ttft = {"status": "unavailable", "ms": None, "reason": "first_content_not_observed"}
            else:
                ttft = {"status": "available", "ms": first - started, "reason": None}
            if first is None or last is None:
                throughput = _throughput_unavailable(unit, "generation_window_not_observed")
            elif units == 0:
                throughput = _throughput_unavailable(unit, "no_content_units")
            elif last <= first:
                throughput = _throughput_unavailable(unit, "zero_generation_interval")
            else:
                duration = last - first
                throughput = {"status": "available", "unit": unit, "units": units, "duration_ms": duration, "value": round(units * 1000 / duration, 3), "reason": None}
    return {
        "schema": "qa-stream-metrics.v1",
        "scope": "technical_stream_metrics_only",
        "ttft": ttft,
        "throughput": throughput,
        "approval": "not_approved",
    }


def _throughput_unavailable(unit, reason):
    return {"status": "unavailable", "unit": unit, "units": None, "duration_ms": None, "value": None, "reason": reason}


__all__ = ["compute_stream_metrics"]
