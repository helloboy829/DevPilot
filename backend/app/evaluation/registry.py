"""Bounded inventory/submission contracts. These snapshots are NOT executable plans."""

import hashlib
import json
import unicodedata
from typing import Literal

from pydantic import Field, field_validator

from app.evaluation.datasets import StrictDTO


class ComponentLinkCreate(StrictDTO):
    source_component_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    kind: Literal["llm", "cv", "agent", "model"]


class SubmissionCreate(StrictDTO):
    version_label: str = Field(min_length=1, max_length=80)
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    dataset_revision: int = Field(ge=1)
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    component_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed: Literal[True]

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value

    @field_validator("version_label")
    @classmethod
    def no_control_characters(cls, value):
        if any(unicodedata.category(char).startswith("C") for char in value) or len(version_key(value)) > 240:
            raise ValueError("Version labels must be bounded and cannot contain control characters")
        return value


def version_key(label: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", label).split()).casefold()


def fingerprint(snapshot: dict) -> str:
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
