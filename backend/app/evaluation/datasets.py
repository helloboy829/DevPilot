"""Strict, bounded QA import contracts. No model, file, network or tool calls."""

from __future__ import annotations

from typing import Literal

from devpilot.datasets import MAX_IMPORT_BYTES, dataset_fingerprint, load_qa_rows, normalized_question
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True, hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("Empty text is not allowed")
        return value


class ProjectCreate(StrictDTO):
    name: str = Field(min_length=1, max_length=160)


class SourceDeclaration(StrictDTO):
    label: str = Field(min_length=1, max_length=160)
    reference: str = Field(min_length=1, max_length=500)
    authorization_basis: str = Field(min_length=1, max_length=1000)
    attested: Literal[True]

    @field_validator("attested", mode="before")
    @classmethod
    def confirm_source(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


class DatasetCreate(StrictDTO):
    name: str = Field(min_length=1, max_length=160)
    purpose: Literal["baseline", "acceptance"]
    source: SourceDeclaration


class QASample(StrictDTO):
    sample_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    input: str = Field(min_length=1, max_length=10_000)
    expected: str = Field(min_length=1, max_length=10_000)
    source_ref: str = Field(min_length=1, max_length=500)
    slice_tag: str = Field(default="default", min_length=1, max_length=80)


class DatasetImport(StrictDTO):
    revision: int = Field(ge=1)
    format: Literal["json", "jsonl"]
    content: str = Field(min_length=1, max_length=MAX_IMPORT_BYTES)


class FreezeRequest(StrictDTO):
    revision: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed: Literal[True]

    @field_validator("reviewed", mode="before")
    @classmethod
    def confirm_review(cls, value):
        if value is not True:
            raise ValueError("Explicit boolean confirmation required")
        return value


def parse_samples(payload: DatasetImport) -> list[QASample]:
    """All-or-nothing import. Return stable errors, never record contents."""
    try:
        rows = load_qa_rows(payload.content, payload.format)
        samples = [QASample.model_validate(row) for row in rows]
        ids: set[str] = set()
        questions: set[str] = set()
        for sample in samples:
            question = normalized_question(sample.input)
            if sample.sample_id in ids or question in questions:
                raise ValueError("Duplicate sample")
            ids.add(sample.sample_id)
            questions.add(question)
        return samples
    except (ValueError, TypeError, RecursionError, UnicodeError, ValidationError):
        raise ValueError("Invalid QA import: check schema, unique IDs/questions, references and size limits") from None


def dataset_hash(source: dict, purpose: str, samples: list[QASample]) -> str:
    return dataset_fingerprint(source, purpose, [s.model_dump() for s in samples])
