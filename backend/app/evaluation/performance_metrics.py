"""Versioned deterministic metrics for frozen performance dispatch rows."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence

_TERMINAL_STATES = ("succeeded", "failed", "timeout", "unknown")


def nearest_rank(values: Sequence[float], percentile: float) -> float | None:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError("Invalid percentile population")
    if type(percentile) not in (int, float) or not math.isfinite(percentile) or not 0 < percentile <= 1:
        raise ValueError("Invalid percentile")
    checked = []
    for value in values:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid percentile observation")
        checked.append(float(value))
    if not checked:
        return None
    checked.sort()
    index = math.ceil(float(percentile) * len(checked)) - 1
    return checked[index]


def _latency_summary(values: list[float]) -> dict:
    return {
        "n": len(values),
        "max": max(values) if values else None,
        "p50": nearest_rank(values, 0.50),
        "p90": nearest_rank(values, 0.90),
        "p99": nearest_rank(values, 0.99) if len(values) >= 100 else None,
        "p99_applicability": "available" if len(values) >= 100 else "insufficient_samples",
    }


def _checked_row(row: Mapping) -> dict:
    if not isinstance(row, Mapping):
        raise ValueError("Invalid dispatch row")
    ordinal = row.get("ordinal")
    phase = row.get("phase")
    state = row.get("state")
    sent = row.get("send_started_ns")
    finished = row.get("finished_ns")
    elapsed = row.get("elapsed_ms")
    tokens = row.get("output_tokens")
    source = row.get("token_source")
    if type(ordinal) is not int or ordinal < 0 or phase not in {"warmup", "measurement"} or state not in {*_TERMINAL_STATES, "pending", "dispatched", "not_dispatched"}:
        raise ValueError("Invalid dispatch identity")
    if sent is not None and (type(sent) is not int or sent < 0):
        raise ValueError("Invalid dispatch timestamp")
    if finished is not None and (type(finished) is not int or finished < 0 or sent is None or finished < sent):
        raise ValueError("Invalid dispatch finish timestamp")
    if elapsed is not None and (type(elapsed) not in (int, float) or not math.isfinite(elapsed) or elapsed < 0):
        raise ValueError("Invalid dispatch latency")
    if tokens is not None and (type(tokens) is not int or tokens < 0 or state != "succeeded"):
        raise ValueError("Invalid output token count")
    if source is not None and (type(source) is not str or not 1 <= len(source) <= 40):
        raise ValueError("Invalid output token source")
    return {
        "ordinal": ordinal,
        "phase": phase,
        "state": state,
        "send_started_ns": sent,
        "finished_ns": finished,
        "elapsed_ms": float(elapsed) if elapsed is not None else None,
        "output_tokens": tokens,
        "token_source": source,
    }


def summarize_performance_dispatches(rows: Sequence[Mapping], *, window_start_ns: int, window_end_ns: int) -> dict:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("Invalid dispatch population")
    if type(window_start_ns) is not int or type(window_end_ns) is not int or window_start_ns < 0 or window_end_ns < window_start_ns:
        raise ValueError("Invalid measurement window")
    checked = [_checked_row(row) for row in rows]
    ordinals = [row["ordinal"] for row in checked]
    if len(set(ordinals)) != len(ordinals):
        raise ValueError("Duplicate dispatch ordinal")
    cohort = [row for row in checked if row["phase"] == "measurement" and row["send_started_ns"] is not None and window_start_ns <= row["send_started_ns"] < window_end_ns]
    cohort.sort(key=lambda row: row["ordinal"])
    states = Counter(row["state"] for row in cohort)
    state_counts = {state: states.get(state, 0) for state in _TERMINAL_STATES}
    successful = [row["elapsed_ms"] for row in cohort if row["state"] == "succeeded" and row["finished_ns"] is not None and row["elapsed_ms"] is not None]
    failed = [row["elapsed_ms"] for row in cohort if row["state"] in {"failed", "timeout"} and row["finished_ns"] is not None and row["elapsed_ms"] is not None]
    censored = sum(row["state"] == "unknown" or row["finished_ns"] is None for row in cohort)
    window_seconds = (window_end_ns - window_start_ns) / 1_000_000_000
    rate_applicability = "available" if window_seconds > 0 else "zero_measurement_window"
    successes = [row for row in cohort if row["state"] == "succeeded"]
    token_rows = [row for row in successes if row["output_tokens"] is not None and row["token_source"] is not None]
    token_applicability = "available"
    if len(token_rows) != len(successes):
        token_applicability = "source_unavailable" if not token_rows else "partial_source"
    token_rate = sum(row["output_tokens"] for row in token_rows) / window_seconds if window_seconds > 0 and len(token_rows) == len(successes) else None
    population = json.dumps(cohort, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return {
        "quantile_method": "nearest_rank.v1",
        "cohort_count": len(cohort),
        "state_counts": state_counts,
        "window_seconds": window_seconds,
        "attempt_qps": len(cohort) / window_seconds if window_seconds > 0 else None,
        "success_qps": state_counts["succeeded"] / window_seconds if window_seconds > 0 else None,
        "rate_applicability": rate_applicability,
        "output_token_count": sum(row["output_tokens"] for row in token_rows) if len(token_rows) == len(successes) else None,
        "output_token_throughput": token_rate,
        "token_applicability": token_applicability,
        "successful_latency_ms": _latency_summary(successful),
        "failed_latency_ms": _latency_summary(failed),
        "censored_count": censored,
        "population_sha256": hashlib.sha256(population).hexdigest(),
    }
