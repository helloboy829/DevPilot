import math

import pytest

from app.evaluation.performance_metrics import nearest_rank, summarize_performance_dispatches


@pytest.mark.parametrize(
    ("values", "percentile", "expected"),
    [([1.0], 0.5, 1.0), ([1, 2, 3, 4], 0.5, 2), ([1, 2, 3, 4], 0.99, 4)],
)
def test_nearest_rank_uses_ceiling_without_interpolation(values, percentile, expected):
    assert nearest_rank(values, percentile) == expected


@pytest.mark.parametrize("values,percentile", [([1, math.inf], 0.5), ([1], 0), ([1], 1.1), ([True], 0.5)])
def test_nearest_rank_rejects_invalid_inputs(values, percentile):
    with pytest.raises(ValueError):
        nearest_rank(values, percentile)


def test_nearest_rank_empty_population_is_unavailable():
    assert nearest_rank([], 0.5) is None


def test_summary_excludes_warmup_and_out_of_window_sends_and_keeps_failures_in_population():
    rows = [
        {"ordinal": 0, "phase": "warmup", "state": "succeeded", "send_started_ns": 100, "finished_ns": 110, "elapsed_ms": 1.0, "output_tokens": 99, "token_source": "provider"},
        {"ordinal": 1, "phase": "measurement", "state": "succeeded", "send_started_ns": 100, "finished_ns": 200, "elapsed_ms": 10.0, "output_tokens": 8, "token_source": "provider"},
        {"ordinal": 2, "phase": "measurement", "state": "failed", "send_started_ns": 150, "finished_ns": 250, "elapsed_ms": 20.0, "output_tokens": None, "token_source": None},
        {"ordinal": 3, "phase": "measurement", "state": "unknown", "send_started_ns": 190, "finished_ns": None, "elapsed_ms": None, "output_tokens": None, "token_source": None},
        {"ordinal": 4, "phase": "measurement", "state": "succeeded", "send_started_ns": 200, "finished_ns": 210, "elapsed_ms": 1.0, "output_tokens": 100, "token_source": "provider"},
    ]

    result = summarize_performance_dispatches(rows, window_start_ns=100, window_end_ns=200)

    assert result["quantile_method"] == "nearest_rank.v1"
    assert result["cohort_count"] == 3
    assert result["state_counts"] == {"succeeded": 1, "failed": 1, "timeout": 0, "unknown": 1}
    assert result["attempt_qps"] == 30_000_000
    assert result["success_qps"] == 10_000_000
    assert result["output_token_throughput"] == 80_000_000
    assert result["successful_latency_ms"]["p50"] == 10.0
    assert result["failed_latency_ms"]["p50"] == 20.0
    assert result["censored_count"] == 1
    assert result["successful_latency_ms"]["p99"] is None
    assert result["successful_latency_ms"]["p99_applicability"] == "insufficient_samples"
    assert result["population_sha256"]


def test_summary_marks_zero_window_rates_unavailable():
    rows = [{"ordinal": 1, "phase": "measurement", "state": "succeeded", "send_started_ns": 5, "finished_ns": 6, "elapsed_ms": 1.0, "output_tokens": 5, "token_source": None}]

    result = summarize_performance_dispatches(rows, window_start_ns=5, window_end_ns=5)

    assert result["attempt_qps"] is None
    assert result["success_qps"] is None
    assert result["output_token_throughput"] is None
    assert result["rate_applicability"] == "zero_measurement_window"


def test_summary_marks_missing_token_source_unavailable():
    rows = [{"ordinal": 1, "phase": "measurement", "state": "succeeded", "send_started_ns": 5, "finished_ns": 6, "elapsed_ms": 1.0, "output_tokens": 5, "token_source": None}]

    result = summarize_performance_dispatches(rows, window_start_ns=5, window_end_ns=7)

    assert result["output_token_count"] is None
    assert result["output_token_throughput"] is None
    assert result["token_applicability"] == "source_unavailable"


@pytest.mark.parametrize(
    ("state", "sent", "finished", "elapsed"),
    [("pending", 100, None, None), ("dispatched", None, None, None), ("unknown", None, None, None)],
)
def test_summary_rejects_timing_combinations_disallowed_by_ledger(state, sent, finished, elapsed):
    row = {
        "ordinal": 1,
        "phase": "measurement",
        "state": state,
        "send_started_ns": sent,
        "finished_ns": finished,
        "elapsed_ms": elapsed,
        "output_tokens": None,
        "token_source": None,
    }

    with pytest.raises(ValueError):
        summarize_performance_dispatches([row], window_start_ns=0, window_end_ns=200)
