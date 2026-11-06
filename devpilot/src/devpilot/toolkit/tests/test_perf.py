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
        latency_sample_count=99,
        ttft_sample_count=99,
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
        report = perf_eval([_level(success_rate=0.8, success=80, failed=20)], criteria={"perf": {"success_rate_min": 0.99}})
        self.assertEqual(report.overall, "FAIL")
        self.assertFalse(report.checks["success_rate"])

    def test_empty_levels_fail(self):
        report = perf_eval([], criteria=None)
        self.assertEqual(report.overall, "FAIL")

    def test_highest_concurrency_is_summary(self):
        report = perf_eval([_level(concurrency=1, success_qps=1), _level(concurrency=20, success_qps=5)], criteria=None)
        self.assertEqual(report.summary.concurrency, 20)


class TestPerfEvidence(unittest.TestCase):
    def test_all_requests_failed_cannot_pass_with_only_latency_threshold(self):
        level = _aggregate_level(1, [PerfSample(False, 10, None, 0, "timeout")], 1.0)
        report = perf_eval([level], criteria={"perf": {"p95_latency_max_ms": 100}})
        self.assertEqual(report.overall, "FAIL")
        self.assertFalse(report.checks["p95_latency"])

    def test_no_requests_cannot_pass_without_thresholds(self):
        report = perf_eval([_aggregate_level(1, [], 1.0)])
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(report.check_reasons["requests"], "no_requests")

    def test_no_success_cannot_pass_without_thresholds(self):
        level = _aggregate_level(1, [PerfSample(False, 10, None, 0)], 1.0)
        report = perf_eval([level])
        self.assertEqual(report.overall, "FAIL")
        self.assertFalse(report.checks["successful_requests"])

    def test_required_missing_metric_cannot_be_skipped(self):
        for metric, threshold, check in (
            ("latency_p95_ms", "p95_latency_max_ms", "p95_latency"),
            ("ttft_p95_ms", "ttft_p95_max_ms", "ttft_p95"),
        ):
            with self.subTest(metric=metric):
                report = perf_eval([_level(**{metric: None})], criteria={"perf": {threshold: 2000}})
                self.assertEqual(report.overall, "FAIL")
                self.assertFalse(report.checks[check])
                self.assertEqual(report.check_reasons[check], "required_metric_unavailable")
                self.assertEqual(report.to_dict()["check_reasons"], report.check_reasons)

    def test_non_streaming_does_not_require_ttft_when_not_configured(self):
        level = _aggregate_level(1, [PerfSample(True, 10, None, 0)], 1.0)
        report = perf_eval([level], criteria={"perf": {"p95_latency_max_ms": 100}})
        self.assertEqual(report.overall, "PASS")
        self.assertNotIn("ttft_p95", report.checks)
        self.assertIsNone(level.ttft_p95_ms)

    def test_partial_ttft_coverage_cannot_pass_required_threshold(self):
        level = _aggregate_level(2, [PerfSample(True, 10, 5, 1), PerfSample(True, 20, None, 1)], 1.0)
        report = perf_eval([level], criteria={"perf": {"ttft_p95_max_ms": 100}})
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(level.ttft_sample_count, 1)
        self.assertEqual(report.check_reasons["ttft_p95"], "incomplete_metric_samples")
        self.assertEqual(level.to_dict()["ttft_sample_count"], 1)

    def test_invalid_metric_values_cannot_pass(self):
        for metric, threshold, check in (
            ("latency_p95_ms", "p95_latency_max_ms", "p95_latency"),
            ("ttft_p95_ms", "ttft_p95_max_ms", "ttft_p95"),
            ("success_qps", "min_qps", "qps"),
            ("throughput_tok_per_s", "min_throughput_tok_per_s", "throughput"),
        ):
            for value in (float("nan"), float("inf"), float("-inf"), -1.0):
                with self.subTest(metric=metric, value=value):
                    report = perf_eval([_level(**{metric: value})], criteria={"perf": {threshold: 1000}})
                    self.assertEqual(report.overall, "FAIL")
                    self.assertFalse(report.checks[check])

    def test_incomplete_latency_samples_cannot_pass_required_threshold(self):
        level = _aggregate_level(2, [PerfSample(True, 10, None, 0), PerfSample(True, float("nan"), None, 0)], 1.0)
        report = perf_eval([level], criteria={"perf": {"p95_latency_max_ms": 100}})
        self.assertEqual(report.overall, "FAIL")
        self.assertEqual(level.latency_sample_count, 1)
        self.assertEqual(report.check_reasons["p95_latency"], "incomplete_metric_samples")

    def test_zero_threshold_is_not_treated_as_missing(self):
        level = _aggregate_level(1, [PerfSample(True, 0, 0, 0)], 1.0)
        report = perf_eval([level], criteria={"perf": {"p95_latency_max_ms": 0, "ttft_p95_max_ms": 0}})
        self.assertEqual(report.overall, "PASS")
        self.assertTrue(report.checks["ttft_p95"])

    def test_invalid_threshold_is_rejected(self):
        for key in ("success_rate_min", "p95_latency_max_ms", "ttft_p95_max_ms", "min_qps", "min_throughput_tok_per_s"):
            for value in (float("nan"), float("inf"), -1):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    PerfThresholds.from_criteria({"perf": {key: value}})
        with self.assertRaises(ValueError):
            PerfThresholds.from_criteria({"perf": {"success_rate_min": 1.1}})

    def test_invalid_wall_time_cannot_pass(self):
        for wall_time in (0, -1, float("nan"), float("inf")):
            with self.subTest(wall_time=wall_time):
                report = perf_eval([_level(wall_time_ms=wall_time)])
                self.assertEqual(report.overall, "FAIL")
                self.assertFalse(report.checks["measurement_window"])

    def test_rounded_serialized_rate_uses_exact_counts_for_gate(self):
        samples = [PerfSample(True, 10, None, 0), PerfSample(True, 10, None, 0), PerfSample(False, 10, None, 0)]
        level = PerfLevelResult(**_aggregate_level(1, samples, 1.0).to_dict())
        self.assertEqual(perf_eval([level], criteria={"perf": {"success_rate_min": 0.66}}).overall, "PASS")
        self.assertEqual(perf_eval([level], criteria={"perf": {"success_rate_min": 0.66668}}).overall, "FAIL")

    def test_inconsistent_counts_cannot_pass(self):
        for updates in ({"success": 0}, {"total": 0}, {"failed": 0}, {"success_rate": 1.0}):
            with self.subTest(updates=updates):
                report = perf_eval([_level(**updates)])
                self.assertEqual(report.overall, "FAIL")


if __name__ == "__main__":
    unittest.main()
