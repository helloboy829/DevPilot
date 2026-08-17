from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from deerflow.persistence.base import Base


class ComponentRow(Base):
    """Registered AI component under test (配置驱动，一次配置反复评测)."""

    __tablename__ = "component_tests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    component_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transport: Mapped[str] = mapped_column(String(32))
    api_url: Mapped[str] = mapped_column(Text)
    api_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_mode: Mapped[str] = mapped_column(String(16), default="blocking")
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=False)
    validation_type: Mapped[str] = mapped_column(String(32))
    acceptance_criteria: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ComponentTestRunRow(Base):
    """One effect/perf test execution against a :class:`ComponentRow`."""

    __tablename__ = "component_test_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    component_id: Mapped[str] = mapped_column(String(64), index=True)
    test_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
