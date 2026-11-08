"""Pre-run effectiveness criteria. Threshold satisfaction is never approval."""

import unicodedata
from typing import Literal

from pydantic import Field, field_validator

from app.evaluation.datasets import StrictDTO
from app.evaluation.registry import version_key


class EffectivenessCriteria(StrictDTO):
    schema_version: Literal["qa-effectiveness-criteria.v1"] = Field(alias="schema")
    version_label: str = Field(min_length=1, max_length=80)
    min_pass_rate_bps: int = Field(ge=0, le=10000)

    @field_validator("version_label")
    @classmethod
    def valid_label(cls, value):
        if not value.strip() or any(unicodedata.category(char).startswith("C") for char in value) or len(version_key(value)) > 240:
            raise ValueError("Invalid criteria version label")
        return value


def assess_criteria(criteria, numerator, denominator, blockers):
    """Caller authenticates the frozen plan and ALL sample decisions first.

    Basis points avoid binary floating point and display-rounding decisions.
    Missing/uncertain/technical results block even a zero threshold.
    """
    frozen = EffectivenessCriteria.model_validate(criteria).model_dump(by_alias=True)
    if type(numerator) is not int or type(denominator) is not int or not 0 <= numerator <= denominator or not 1 <= denominator <= 500:
        raise ValueError("Invalid verified counts")
    status = "incomplete" if blockers else "met" if numerator * 10000 >= denominator * frozen["min_pass_rate_bps"] else "not_met"
    return {"scope": "effectiveness_threshold_only", "criteria": frozen, "status": status, "blockers": list(blockers), "approval": "not_approved"}
