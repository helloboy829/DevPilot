from datetime import UTC, datetime
from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ALLOWED_MATERIAL_SUFFIXES = {".csv", ".docx", ".jpeg", ".jpg", ".json", ".jsonl", ".md", ".pdf", ".png", ".txt", ".webp", ".xlsx"}


class MaterialComponent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    component_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["llm", "cv", "agent", "model"]
    purpose: str = Field(min_length=1, max_length=500)
    attachment_ids: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("attachment_ids")
    @classmethod
    def unique_attachments(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("attachment ids must be unique within a component")
        return values


class MaterialAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    attachment_id: str = Field(pattern=r"^att_[A-Za-z0-9_-]{1,60}$")
    file_name: str = Field(min_length=1, max_length=255)
    authorization_basis: Literal["user_provided", "public_domain", "license", "contract", "explicit_consent"]
    purpose: str = Field(min_length=1, max_length=500)
    sensitivity: Literal["public", "internal", "confidential", "restricted"]
    retention_until: datetime

    @field_validator("file_name")
    @classmethod
    def basename_only(cls, value):
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("file_name must be a basename")
        if PurePath(value).suffix.casefold() not in _ALLOWED_MATERIAL_SUFFIXES:
            raise ValueError("file_name extension is not supported")
        return value

    @field_validator("retention_until")
    @classmethod
    def future_timezone_aware_retention(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retention_until must include a timezone")
        if value.astimezone(UTC) <= datetime.now(UTC):
            raise ValueError("retention_until must be in the future")
        return value


class MaterialBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)
    components: list[MaterialComponent] = Field(min_length=1, max_length=10000)
    attachments: list[MaterialAttachment] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_manifest(self):
        ids = [item.component_id for item in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("component ids must be unique")
        attachment_ids = [item.attachment_id for item in self.attachments]
        if len(attachment_ids) != len(set(attachment_ids)):
            raise ValueError("attachment ids must be unique")
        referenced = {attachment_id for component in self.components for attachment_id in component.attachment_ids}
        if referenced - set(attachment_ids):
            raise ValueError("component references an unknown attachment")
        if set(attachment_ids) - referenced:
            raise ValueError("every attachment must be explicitly mapped to a component")
        return self


def initial_component_states(manifest):
    return [{"component_id": c.component_id, "status": "pending", "reason": None} for c in manifest.components]
