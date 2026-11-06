"""性能测试（perf test）：阶梯并发压测 + 硬阈值判定。

铁律（源自 skill 的 pitfalls，口径严格）：

- **聚合吞吐 = 总 token ÷ 墙钟**（不是「各请求吞吐之和」）。
- **成功 QPS = 成功请求数 ÷ 墙钟**（失败的请求不计入 QPS 分母外的成功计数）。
- TTFT 只读取 transport 提供的内容分片计时；完整流式能力/缓冲有效性验证仍待实现。
- 配置的延迟/TTFT 阈值要求覆盖所有成功请求，缺失/无效测量不能跳过。
- 流式无 ``usage`` 时按文本估 token（``estimate_tokens``）。

``perf_run`` 返回每档聚合；逐请求采样尚未持久化。
``perf_eval`` 只读聚合 + 阈值判定 PASS/FAIL；总 token 吞吐不是纯输出 TPS。
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from devpilot.toolkit.transports import TransportConfig, call_transport


@dataclass
class PerfSample:
    success: bool
    latency_ms: float
    ttft_ms: float | None
    total_tokens: int
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "ttft_ms": round(self.ttft_ms, 2) if self.ttft_ms is not None else None,
            "total_tokens": self.total_tokens,
            "error": self.error,
        }


@dataclass
class PerfLevelResult:
    """单个并发档位的聚合指标。"""

    concurrency: int
    total: int = 0
    success: int = 0
    failed: int = 0
    success_rate: float = 0.0
    wall_time_ms: float = 0.0
    success_qps: float = 0.0
    throughput_tok_per_s: float = 0.0
    total_tokens: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_p99_ms: float | None = None
    ttft_p50_ms: float | None = None
    ttft_p95_ms: float | None = None
    latency_sample_count: int = 0
    ttft_sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "success_rate": round(self.success_rate, 4),
            "wall_time_ms": round(self.wall_time_ms, 2),
            "success_qps": round(self.success_qps, 3),
            "throughput_tok_per_s": round(self.throughput_tok_per_s, 2),
            "total_tokens": self.total_tokens,
            "latency_p50_ms": _round(self.latency_p50_ms),
            "latency_p95_ms": _round(self.latency_p95_ms),
            "latency_p99_ms": _round(self.latency_p99_ms),
            "ttft_p50_ms": _round(self.ttft_p50_ms),
            "ttft_p95_ms": _round(self.ttft_p95_ms),
            "latency_sample_count": self.latency_sample_count,
            "ttft_sample_count": self.ttft_sample_count,
        }


@dataclass
class PerfThresholds:
    """性能验收硬阈值。可选阈值为 None 时不启用；0 是有效阈值。"""

    success_rate_min: float = 0.0
    p95_latency_max_ms: float | None = None
    ttft_p95_max_ms: float | None = None
    min_qps: float | None = None
    min_throughput_tok_per_s: float | None = None

    @classmethod
    def from_criteria(cls, criteria: Mapping[str, Any] | None) -> PerfThresholds:
        perf = (criteria or {}).get("perf") or {}

        def _f(key: str) -> float | None:
            v = perf.get(key)
            if v is None or v == "":
                return None
            value = float(v)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and non-negative")
            if key == "success_rate_min" and value > 1:
                raise ValueError("success_rate_min must be between 0 and 1")
            return value

        return cls(
            success_rate_min=_f("success_rate_min") or 0.0,
            p95_latency_max_ms=_f("p95_latency_max_ms"),
            ttft_p95_max_ms=_f("ttft_p95_max_ms"),
            min_qps=_f("min_qps"),
            min_throughput_tok_per_s=_f("min_throughput_tok_per_s"),
        )


@dataclass
class PerfReport:
    levels: list[PerfLevelResult] = field(default_factory=list)
    overall: str = "FAIL"  # PASS | FAIL
    summary: PerfLevelResult | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    check_reasons: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "summary": self.summary.to_dict() if self.summary else None,
            "checks": self.checks,
            "check_reasons": self.check_reasons,
            "levels": [lv.to_dict() for lv in self.levels],
        }


def percentile(values: Sequence[float], p: float) -> float | None:
    """最近秩（nearest-rank）百分位。空序列返回 None。"""
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = min(len(sorted_vals) - 1, max(0, math.ceil(p / 100.0 * len(sorted_vals)) - 1))
    return sorted_vals[idx]


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


async def _run_level(
    config: TransportConfig,
    payload: Mapping[str, Any],
    *,
    concurrency: int,
    max_requests: int,
    duration_seconds: float | None,
    stream: bool | None,
    client: Any = None,
) -> tuple[list[PerfSample], float]:
    """以固定并发跑一个档位，返回 (采样, 墙钟秒)。

    ``client`` 复用同一个 ``httpx.AsyncClient``（keep-alive），否则每个请求
    新建连接，既放慢压测又污染延迟/TTFT 测量。
    """
    import itertools

    sem = asyncio.Semaphore(concurrency)
    counter = itertools.count()
    samples: list[PerfSample] = []
    start = time.monotonic()
    stop_at = start + duration_seconds if duration_seconds else None

    async def worker() -> None:
        while True:
            idx = next(counter)
            if idx >= max_requests:
                return
            if stop_at is not None and time.monotonic() >= stop_at:
                return
            async with sem:
                result = await call_transport(config, payload, stream=stream, client=client)
                samples.append(
                    PerfSample(
                        success=result.success,
                        latency_ms=result.latency_ms,
                        ttft_ms=result.ttft_ms,
                        total_tokens=result.total_tokens,
                        error=result.error,
                    )
                )

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return samples, time.monotonic() - start


def _aggregate_level(concurrency: int, samples: Sequence[PerfSample], wall_seconds: float) -> PerfLevelResult:
    total = len(samples)
    success = sum(1 for s in samples if s.success)
    failed = total - success
    level = PerfLevelResult(concurrency=concurrency, total=total, success=success, failed=failed)
    if total:
        level.success_rate = success / total
    if wall_seconds > 0:
        level.wall_time_ms = wall_seconds * 1000
        level.success_qps = success / wall_seconds
        level.total_tokens = sum(s.total_tokens for s in samples)
        level.throughput_tok_per_s = level.total_tokens / wall_seconds

    latencies = [s.latency_ms for s in samples if s.success and _valid_metric(s.latency_ms)]
    ttfts = [s.ttft_ms for s in samples if s.success and _valid_metric(s.ttft_ms)]
    level.latency_sample_count = len(latencies)
    level.ttft_sample_count = len(ttfts)
    level.latency_p50_ms = percentile(latencies, 50)
    level.latency_p95_ms = percentile(latencies, 95)
    level.latency_p99_ms = percentile(latencies, 99)
    level.ttft_p50_ms = percentile(ttfts, 50)
    level.ttft_p95_ms = percentile(ttfts, 95)
    return level


async def perf_run(
    config: TransportConfig,
    payload: Mapping[str, Any],
    *,
    concurrency_levels: Sequence[int] = (1, 5, 10, 20),
    max_requests: int = 100,
    duration_seconds: float | None = None,
    stream: bool | None = None,
    client: Any = None,
) -> list[PerfLevelResult]:
    """阶梯并发压测，返回每档聚合指标。

    ``stream`` 为 None 时按 transport 能力决定（支持 SSE 的走流式以测 TTFT）。
    ``client`` 复用同一个 ``httpx.AsyncClient``（keep-alive）；为 None 时每个请求
    新建连接。
    """
    levels: list[PerfLevelResult] = []
    for concurrency in concurrency_levels:
        samples, wall_seconds = await _run_level(
            config,
            payload,
            concurrency=concurrency,
            max_requests=max_requests,
            duration_seconds=duration_seconds,
            stream=stream,
            client=client,
        )
        levels.append(_aggregate_level(concurrency, samples, wall_seconds))
    return levels


def _valid_metric(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value >= 0


def perf_eval(levels: Sequence[PerfLevelResult], *, criteria: Mapping[str, Any] | None = None) -> PerfReport:
    """Evaluate the highest concurrency level, failing closed on missing evidence.

    A configured latency/TTFT threshold requires valid measurements for every
    successful request. Unconfigured TTFT remains optional for non-streaming APIs.
    """
    thresholds = PerfThresholds.from_criteria(criteria)
    report = PerfReport(levels=list(levels))
    if not levels:
        report.checks["requests"] = False
        report.check_reasons["requests"] = "no_levels"
        return report

    summary = max(levels, key=lambda lv: lv.concurrency)
    report.summary = summary
    checks = report.checks
    reasons = report.check_reasons

    def record(name: str, passed: bool, reason: str) -> None:
        checks[name] = passed
        if not passed:
            reasons[name] = reason

    record("requests", summary.total > 0, "no_requests")
    record("successful_requests", summary.success > 0, "no_successful_requests")
    record(
        "request_counts",
        summary.total >= 0 and 0 <= summary.success <= summary.total and 0 <= summary.failed <= summary.total and summary.success + summary.failed == summary.total,
        "inconsistent_request_counts",
    )
    record("measurement_window", _valid_metric(summary.wall_time_ms) and summary.wall_time_ms > 0, "invalid_measurement_window")
    # Serialized rates are rounded to four places; gate on exact request counts.
    expected_rate = summary.success / summary.total if summary.total > 0 else 0.0
    valid_rate = _valid_metric(summary.success_rate) and summary.success_rate <= 1 and math.isclose(summary.success_rate, expected_rate, rel_tol=0.0, abs_tol=5e-5)
    record(
        "success_rate",
        valid_rate and expected_rate >= thresholds.success_rate_min,
        "below_minimum" if valid_rate else "invalid_success_rate",
    )

    def check_metric(name: str, value: float | None, threshold: float, *, maximum: bool, sample_count: int | None = None) -> None:
        if value is None:
            record(name, False, "required_metric_unavailable")
        elif not _valid_metric(value):
            record(name, False, "invalid_metric")
        elif sample_count is not None and sample_count != summary.success:
            record(name, False, "incomplete_metric_samples")
        else:
            passed = value <= threshold if maximum else value >= threshold
            record(name, passed, "above_maximum" if maximum else "below_minimum")

    if thresholds.p95_latency_max_ms is not None:
        check_metric("p95_latency", summary.latency_p95_ms, thresholds.p95_latency_max_ms, maximum=True, sample_count=summary.latency_sample_count)
    if thresholds.ttft_p95_max_ms is not None:
        check_metric("ttft_p95", summary.ttft_p95_ms, thresholds.ttft_p95_max_ms, maximum=True, sample_count=summary.ttft_sample_count)
    if thresholds.min_qps is not None:
        check_metric("qps", summary.success_qps, thresholds.min_qps, maximum=False)
    if thresholds.min_throughput_tok_per_s is not None:
        check_metric("throughput", summary.throughput_tok_per_s, thresholds.min_throughput_tok_per_s, maximum=False)

    report.overall = "PASS" if all(checks.values()) else "FAIL"
    return report


__all__ = [
    "PerfSample",
    "PerfLevelResult",
    "PerfThresholds",
    "PerfReport",
    "percentile",
    "perf_run",
    "perf_eval",
    "_aggregate_level",
]
