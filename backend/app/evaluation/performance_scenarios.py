"""Bounded, immutable performance scenario contracts. No requests are sent here."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.evaluation.datasets import StrictDTO

_CASE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


class PerformanceProfile(StrictDTO):
    concurrency: int = Field(ge=1, le=64)
    measured_request_count: int = Field(ge=1, le=10_000)
    warmup_request_count: int = Field(ge=0, le=1_000)
    duration_limit_seconds: int | None = Field(default=None, ge=1, le=3_600)
    request_timeout_ms: int = Field(ge=100, le=300_000)
    max_in_flight: int = Field(ge=1, le=64)
    wall_time_limit_seconds: int = Field(ge=1, le=7_200)
    drain_limit_seconds: int = Field(ge=1, le=300)
    max_request_bytes: int = Field(ge=1, le=10_000_000)
    max_response_bytes: int = Field(ge=1, le=10_000_000)
    max_total_bytes: int = Field(ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def validate_budget(self):
        if self.max_in_flight < self.concurrency:
            raise ValueError("max_in_flight must cover configured concurrency")
        if self.request_timeout_ms > self.wall_time_limit_seconds * 1000:
            raise ValueError("request timeout exceeds wall-time limit")
        if self.drain_limit_seconds > self.wall_time_limit_seconds:
            raise ValueError("drain limit exceeds wall-time limit")
        if self.max_total_bytes < self.max_request_bytes + self.max_response_bytes:
            raise ValueError("total byte budget must cover one bounded request and response")
        return self


class ManifestEntry(StrictDTO):
    ordinal: int = Field(ge=0)
    phase: Literal["warmup", "measurement"]
    case_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    iteration: int = Field(ge=0)


def build_case_manifest(case_ids: list[str] | tuple[str, ...], *, warmup_count: int, measured_count: int) -> list[dict]:
    """Freeze sorted case cycling with independent phase iteration origins."""
    if not case_ids or any(not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id) for case_id in case_ids):
        raise ValueError("Invalid case scope")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("Duplicate case IDs")
    if not isinstance(warmup_count, int) or isinstance(warmup_count, bool) or warmup_count < 0:
        raise ValueError("Invalid warmup count")
    if not isinstance(measured_count, int) or isinstance(measured_count, bool) or measured_count < 1:
        raise ValueError("Invalid measured count")

    ordered = sorted(case_ids)
    entries = []
    ordinal = 0
    for phase, count in (("warmup", warmup_count), ("measurement", measured_count)):
        for index in range(count):
            entries.append(
                ManifestEntry(
                    ordinal=ordinal,
                    phase=phase,
                    case_id=ordered[index % len(ordered)],
                    iteration=index // len(ordered),
                ).model_dump()
            )
            ordinal += 1
    return entries


class PerformanceScenarioCreate(StrictDTO):
    plan_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    profile: PerformanceProfile
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def require_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value
