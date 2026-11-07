"""Write-only request-value intake; saved definitions are not execution approval."""

import unicodedata
from typing import Literal

from devpilot.request_versions import FrozenRequest
from pydantic import Field, field_validator

from app.evaluation.datasets import StrictDTO
from app.evaluation.registry import version_key


class RequestVersionCreate(StrictDTO):
    version_label: str = Field(min_length=1, max_length=80)
    request: dict = Field(repr=False)
    confirmed: Literal[True]

    @field_validator("version_label")
    @classmethod
    def bounded_label(cls, value):
        if any(unicodedata.category(char).startswith("C") for char in value) or len(version_key(value)) > 240:
            raise ValueError("Invalid request version label")
        return value

    @field_validator("request")
    @classmethod
    def validate_request(cls, value):
        return FrozenRequest.from_protected_dict(value).to_protected_dict()

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value
