"""perf.py 纯逻辑单测（无网络）。

覆盖：百分位、聚合吞吐口径、成功 QPS、硬阈值 PASS/FAIL。
"""

from __future__ import annotations

import unittest

from devpilot.toolkit.perf import (
    PerfLevelResult,
    PerfSample,
    PerfThresholds,
    _aggregate_level,
    percentile,
    perf_eval,
)


class TestPercentile(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(percentile([], 95))

    def test_nearest_rank_p50(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)

    def test_nearest_rank_p95(self):
        # 20 个值，p95 最近秩 -> 第 19 个（索引 18）= 19
        values = list(range(1, 21))
        self.assertEqual(percentile(values, 95), 19)


class TestAggregateLevel(unittest.TestCase):
    def test_throughput_and_qps(self):
        samples = [
            PerfSample(success=True, latency_ms=10, ttft_ms=5, total_tokens=100),
            PerfSample(success=True, latency_ms=20, ttft_ms=8, total_tokens=200),
            PerfSample(success=False, latency_ms=30, ttft_ms=None, total_tokens=0, error="e"),
        ]
        level = _aggregate_level(concurrency=3, samples=samples, wall_seconds=2.0)
        self.assertEqual(level.total, 3)
        self.assertEqual(level.success, 2)
        self.assertEqual(level.failed, 1)
        # 成功 QPS = 2 / 2s = 1.0（失败请求不计入成功计数）
        self.assertAlmostEqual(level.success_qps, 1.0)
        # 聚合吞吐 = 总 token(300) / 墙钟(2s) = 150
        self.assertEqual(level.throughput_tok_per_s, 150.0)
        self.assertAlmostEqual(level.success_rate, 2 / 3)

    def test_empty_samples(self):
        level = _aggregate_level(concurrency=1, samples=[], wall_seconds=1.0)
        self.assertEqual(level.total, 0)
        self.assertEqual(level.success_rate, 0.0)
        self.assertEqual(level.success_qps, 0.0)
        self.assertEqual(level.throughput_tok_per_s, 0.0)


def _level(**kw):
    defaults = dict(
        concurrency=10,
        total=100,
        success=99,
        failed=1,
        success_rate=0.99,
        wall_time_ms=10000,
        success_qps=9.9,
        throughput_tok_per_s=500.0,
        total_tokens=5000,
        latency_p95_ms=1500.0,
        ttft_p95_ms=800.0,
    )
    defaults.update(kw)
    return PerfLevelResult(**defaults)


class TestPerfEval(unittest.TestCase):
    def test_pass_when_all_thresholds_met(self):
        criteria = {
            "perf": {
                "success_rate_min": 0.99,
                "p95_latency_max_ms": 2000,
                "ttft_p95_max_ms": 1000,
                "min_qps": 9.0,
                "min_throughput_tok_per_s": 400,
            }
        }
        report = perf_eval([_level(concurrency=1), _level(concurrency=10)], criteria=criteria)
        self.assertEqual(report.overall, "PASS")

    def test_fail_on_low_success_rate(self):
        report = perf_eval([_level(success_rate=0.8, success=80)], criteria={"perf": {"success_rate_min": 0.99}})
        self.assertEqual(report.overall, "FAIL")
        self.assertFalse(report.checks["success_rate"])

    def test_empty_levels_fail(self):
        report = perf_eval([], criteria=None)
        self.assertEqual(report.overall, "FAIL")

    def test_highest_concurrency_is_summary(self):
        report = perf_eval([_level(concurrency=1, success_qps=1), _level(concurrency=20, success_qps=5)], criteria=None)
        self.assertEqual(report.summary.concurrency, 20)


if __name__ == "__main__":
    unittest.main()
