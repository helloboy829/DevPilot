import pytest
from pydantic import ValidationError

from app.evaluation.performance_scenarios import PerformanceProfile, build_case_manifest


def test_manifest_cycles_sorted_cases_and_preserves_each_ordinal():
    manifest = build_case_manifest(["case-b", "case-a"], warmup_count=1, measured_count=5)

    assert manifest == [
        {"ordinal": 0, "phase": "warmup", "case_id": "case-a", "iteration": 0},
        {"ordinal": 1, "phase": "measurement", "case_id": "case-a", "iteration": 0},
        {"ordinal": 2, "phase": "measurement", "case_id": "case-b", "iteration": 0},
        {"ordinal": 3, "phase": "measurement", "case_id": "case-a", "iteration": 1},
        {"ordinal": 4, "phase": "measurement", "case_id": "case-b", "iteration": 1},
        {"ordinal": 5, "phase": "measurement", "case_id": "case-a", "iteration": 2},
    ]


@pytest.mark.parametrize("case_ids", [[], ["same", "same"], [""]])
def test_manifest_rejects_empty_or_ambiguous_case_scope(case_ids):
    with pytest.raises(ValueError):
        build_case_manifest(case_ids, warmup_count=0, measured_count=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"concurrency": 0},
        {"concurrency": 65},
        {"measured_request_count": 0},
        {"measured_request_count": 10_001},
        {"max_in_flight": 65},
        {"wall_time_limit_seconds": 30, "request_timeout_ms": 30_001},
        {"duration_limit_seconds": 0},
        {"max_total_bytes": 0},
    ],
)
def test_profile_rejects_unbounded_or_contradictory_limits(changes):
    payload = {
        "concurrency": 4,
        "measured_request_count": 20,
        "warmup_request_count": 2,
        "duration_limit_seconds": None,
        "request_timeout_ms": 30_000,
        "max_in_flight": 4,
        "wall_time_limit_seconds": 300,
        "drain_limit_seconds": 30,
        "max_request_bytes": 1_000_000,
        "max_response_bytes": 1_000_000,
        "max_total_bytes": 10_000_000,
    }
    payload.update(changes)

    with pytest.raises(ValidationError):
        PerformanceProfile.model_validate(payload)


def test_duration_is_optional_but_measured_count_remains_finite():
    profile = PerformanceProfile.model_validate(
        {
            "concurrency": 4,
            "measured_request_count": 20,
            "warmup_request_count": 2,
            "duration_limit_seconds": None,
            "request_timeout_ms": 30_000,
            "max_in_flight": 4,
            "wall_time_limit_seconds": 300,
            "drain_limit_seconds": 30,
            "max_request_bytes": 1_000_000,
            "max_response_bytes": 1_000_000,
            "max_total_bytes": 10_000_000,
        }
    )

    assert profile.measured_request_count == 20
    assert profile.duration_limit_seconds is None
