"""Bounded, non-executing frozen QA JSON plan contracts."""

import unicodedata
from typing import Literal

from devpilot.qa_json_binding import QAJSONBinding
from pydantic import Field, field_validator, model_validator

from app.evaluation.criteria import EffectivenessCriteria
from app.evaluation.datasets import StrictDTO
from app.evaluation.registry import version_key


class PlanPreflightError(Exception):
    """Stable, non-sensitive mapping/budget failure. Never include input values."""


class PlanLimits(StrictDTO):
    mode: Literal["effectiveness", "performance"]
    concurrency: int = Field(ge=1, le=64)
    request_count: int = Field(ge=1, le=10_000)
    timeout_ms: int = Field(ge=100, le=300_000)
    wall_time_ms: int = Field(ge=100, le=3_600_000)
    max_total_body_bytes: int = Field(ge=1, le=67_108_864)

    @model_validator(mode="after")
    def bounded(self):
        if (self.mode == "effectiveness" and self.concurrency > 8) or self.wall_time_ms < self.timeout_ms:
            raise ValueError("Invalid QA execution limits")
        return self


class PlanSettings(StrictDTO):
    version_label: str = Field(min_length=1, max_length=80)
    request_version_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    request_protected_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dataset_revision: int = Field(ge=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    binding: dict
    limits: PlanLimits
    response_mode: Literal["json_text"]

    @field_validator("version_label")
    @classmethod
    def bounded_label(cls, value):
        if any(unicodedata.category(char).startswith("C") for char in value) or len(version_key(value)) > 240:
            raise ValueError("Invalid plan version label")
        return value

    @field_validator("binding")
    @classmethod
    def checked_binding(cls, value):
        return QAJSONBinding.from_dict(value).to_dict()


class PlanCreate(PlanSettings):
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


class PlanPreflight(StrictDTO):
    sample_count: int = Field(ge=1, le=500)
    request_count: int = Field(ge=1, le=10_000)
    total_body_bytes: int = Field(ge=1, le=67_108_864)


class PlanDefinition(PlanSettings):
    schema_version: Literal["qa-json-plan.v1"] = Field(alias="schema")
    scope: Literal["frozen_definition_only"]
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    component_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    request_template_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_purpose: Literal["baseline", "acceptance"]
    sample_order: Literal["sample_id_ascending_cycle.v1"]
    evaluation_policy: Literal["human_review_required.v1"]
    preflight: PlanPreflight

    @model_validator(mode="after")
    def consistent_budget(self):
        check = self.preflight
        if (
            check.request_count != self.limits.request_count
            or check.request_count < check.sample_count
            or (self.limits.mode == "effectiveness" and check.request_count != check.sample_count)
            or check.total_body_bytes > self.limits.max_total_body_bytes
        ):
            raise ValueError("Invalid frozen QA plan budget")
        return self


class AcceptancePlanCreate(PlanCreate):
    acceptance_criteria: EffectivenessCriteria

    @model_validator(mode="after")
    def effectiveness_only(self):
        if self.limits.mode != "effectiveness":
            raise ValueError("Effectiveness criteria require effectiveness mode")
        return self


class AcceptancePlanDefinition(PlanDefinition):
    schema_version: Literal["qa-json-plan.v2"] = Field(alias="schema")
    acceptance_criteria: EffectivenessCriteria

    @model_validator(mode="after")
    def effectiveness_only(self):
        if self.limits.mode != "effectiveness":
            raise ValueError("Effectiveness criteria require effectiveness mode")
        return self
