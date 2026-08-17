"""性能测试（perf test）：阶梯并发压测 + 硬阈值判定。

铁律（源自 skill 的 pitfalls，口径严格）：

- **聚合吞吐 = 总 token ÷ 墙钟**（不是「各请求吞吐之和」）。
- **成功 QPS = 成功请求数 ÷ 墙钟**（失败的请求不计入 QPS 分母外的成功计数）。
- **TTFT = 首个用户可见 answer 分片**（由 transports 保证口径）。
- 流式无 ``usage`` 时按文本估 token（``estimate_tokens``）。

``perf_run`` 产出原始采样；``perf_eval`` 只读采样 + 阈值判定 PASS/FAIL。
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from devpilot.toolkit.transports import TransportConfig, TransportResult, call_transport


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
        }


@dataclass
class PerfThresholds:
    """性能验收硬阈值。None/0 表示不设该维度门槛。"""

    success_rate_min: float = 0.0
    p95_latency_max_ms: float | None = None
    ttft_p95_max_ms: float | None = None
    min_qps: float | None = None
    min_throughput_tok_per_s: float | None = None

    @classmethod
    def from_criteria(cls, criteria: Mapping[str, Any] | None) -> "PerfThresholds":
        perf = (criteria or {}).get("perf") or {}

        def _f(key: str) -> float | None:
            v = perf.get(key)
            if v is None or v == "":
                return None
            return float(v)

        return cls(
            success_rate_min=float(perf.get("success_rate_min") or 0.0),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "summary": self.summary.to_dict() if self.summary else None,
            "checks": self.checks,
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

    latencies = [s.latency_ms for s in samples if s.success]
    ttfts = [s.ttft_ms for s in samples if s.success and s.ttft_ms is not None]
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


def perf_eval(levels: Sequence[PerfLevelResult], *, criteria: Mapping[str, Any] | None = None) -> PerfReport:
    """对每档聚合指标做硬阈值判定，汇总 PASS/FAIL。

    判定基于**最高并发档**（最能代表吞吐/延迟上限）；若无档位则 FAIL。
    """
    thresholds = PerfThresholds.from_criteria(criteria)
    report = PerfReport(levels=list(levels))
    if not levels:
        report.overall = "FAIL"
        return report

    summary = max(levels, key=lambda lv: lv.concurrency)
    report.summary = summary

    checks: dict[str, bool] = {}
    checks["success_rate"] = summary.success_rate >= thresholds.success_rate_min
    if thresholds.p95_latency_max_ms is not None and summary.latency_p95_ms is not None:
        checks["p95_latency"] = summary.latency_p95_ms <= thresholds.p95_latency_max_ms
    if thresholds.ttft_p95_max_ms is not None and summary.ttft_p95_ms is not None:
        checks["ttft_p95"] = summary.ttft_p95_ms <= thresholds.ttft_p95_max_ms
    if thresholds.min_qps is not None:
        checks["qps"] = summary.success_qps >= thresholds.min_qps
    if thresholds.min_throughput_tok_per_s is not None:
        checks["throughput"] = summary.throughput_tok_per_s >= thresholds.min_throughput_tok_per_s

    report.checks = checks
    report.overall = "PASS" if (checks and all(checks.values())) else "FAIL"
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
