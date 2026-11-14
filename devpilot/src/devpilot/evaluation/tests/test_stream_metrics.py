"""流式 TTFT/吞吐纯核心单测（零依赖，unittest）。

运行（repo 根目录）：
    python -m unittest discover -s devpilot/src/devpilot/evaluation/tests -p 'test_stream_metrics.py' -v
"""

from __future__ import annotations

import json
import unittest

from devpilot.qa_stream_metrics import compute_stream_metrics

START = 1_800_000_000_000


def observation(**changes):
    values = {
        "mode": "streaming",
        "outcome": "collected",
        "started_at_ms": START,
        "first_content_at_ms": START + 120,
        "last_content_at_ms": START + 1_120,
        "finished_at_ms": START + 1_200,
        "content_units": 500,
        "content_unit": "chars",
    }
    values.update(changes)
    return values


class TestStreamMetrics(unittest.TestCase):
    def test_streaming_ttft_and_throughput_are_computed(self):
        result = compute_stream_metrics(observation())
        self.assertEqual(result["schema"], "qa-stream-metrics.v1")
        self.assertEqual(result["scope"], "technical_stream_metrics_only")
        self.assertEqual(result["approval"], "not_approved")
        self.assertEqual(result["ttft"], {"status": "available", "ms": 120, "reason": None})
        self.assertEqual(
            result["throughput"],
            {"status": "available", "unit": "chars", "units": 500, "duration_ms": 1_000, "value": 500.0, "reason": None},
        )
        json.dumps(result)

    def test_token_unit_is_echoed_and_used(self):
        result = compute_stream_metrics(observation(content_units=250, content_unit="tokens"))
        self.assertEqual(result["throughput"]["unit"], "tokens")
        self.assertEqual(result["throughput"]["value"], 250.0)

    def test_non_streaming_metrics_are_not_applicable_not_zero(self):
        result = compute_stream_metrics(observation(mode="non_streaming", first_content_at_ms=None, last_content_at_ms=None))
        for key in ("ttft", "throughput"):
            self.assertEqual(result[key]["status"], "not_applicable")
            self.assertIsNone(result[key].get("ms"))
            self.assertIsNone(result[key].get("value"))
            self.assertEqual(result[key]["reason"], "non_streaming_response")

    def test_technical_incomplete_never_fabricates_values(self):
        result = compute_stream_metrics(observation(outcome="technical_incomplete"))
        for key in ("ttft", "throughput"):
            self.assertEqual(result[key]["status"], "unavailable")
            self.assertEqual(result[key]["reason"], "technical_incomplete")
            self.assertIsNone(result[key].get("ms"))
            self.assertIsNone(result[key].get("value"))

    def test_missing_content_window_is_explicit(self):
        result = compute_stream_metrics(observation(first_content_at_ms=None, last_content_at_ms=None))
        self.assertEqual(result["ttft"], {"status": "unavailable", "ms": None, "reason": "first_content_not_observed"})
        self.assertEqual(result["throughput"]["status"], "unavailable")
        self.assertEqual(result["throughput"]["reason"], "generation_window_not_observed")
        self.assertIsNone(result["throughput"]["value"])

    def test_ttft_without_last_content_still_reports_ttft(self):
        result = compute_stream_metrics(observation(last_content_at_ms=None))
        self.assertEqual(result["ttft"]["status"], "available")
        self.assertEqual(result["ttft"]["ms"], 120)
        self.assertEqual(result["throughput"]["reason"], "generation_window_not_observed")

    def test_zero_units_and_zero_interval_are_unavailable(self):
        zero_units = compute_stream_metrics(observation(content_units=0))
        self.assertEqual(zero_units["throughput"]["status"], "unavailable")
        self.assertEqual(zero_units["throughput"]["reason"], "no_content_units")
        self.assertIsNone(zero_units["throughput"]["value"])
        zero_interval = compute_stream_metrics(observation(last_content_at_ms=START + 120))
        self.assertEqual(zero_interval["throughput"]["reason"], "zero_generation_interval")
        self.assertIsNone(zero_interval["throughput"]["value"])

    def test_malformed_or_incoherent_observations_fail_closed(self):
        cases = [
            [],
            {**observation(), "extra": 1},
            observation(mode="batch"),
            observation(outcome="failed"),
            observation(content_unit="words"),
            observation(content_units=True),
            observation(content_units=-1),
            observation(content_units=1.5),
            observation(started_at_ms=True),
            observation(finished_at_ms=START - 1),
            observation(first_content_at_ms=START - 1),
            observation(last_content_at_ms=START + 110),
            observation(last_content_at_ms=START + 1_500),
            observation(first_content_at_ms=None),
            observation(first_content_at_ms=None, last_content_at_ms=None, extra=1),
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ValueError):
                    compute_stream_metrics(case)


if __name__ == "__main__":
    unittest.main()
