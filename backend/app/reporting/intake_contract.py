"""Bounded, client-held conversation DTOs; not durable or authenticated evidence."""

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ComponentSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(default="", max_length=200)


class IntakeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(default="", max_length=200)
    project_name: str = Field(default="", max_length=200)
    components: list[ComponentSuggestion] = Field(default_factory=list, max_length=30)
    questions: list[str] = Field(min_length=1, max_length=12)

    @field_validator("questions")
    @classmethod
    def short_questions(cls, value):
        if any(not q.strip() or len(q) > 600 for q in value):
            raise ValueError("Invalid intake questions")
        return value

    def safe_dict(self):
        return self.model_dump()


class IntakeTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    proposal: IntakeSuggestion


class IntakeContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=4000)
    history: list[IntakeTurn] = Field(default_factory=list, max_length=9)

    @model_validator(mode="after")
    def bounded_context(self):
        if not self.message.strip() or any(not turn.message.strip() for turn in self.history):
            raise ValueError("Empty message")
        if len(json.dumps(self.model_dump(), ensure_ascii=False)) > 24000:
            raise ValueError("Conversation exceeds 24000 characters; start a new conversation")
        return self
