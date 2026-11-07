"""App-owned evaluation tables, intentionally separate from Harness metadata."""

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Integer, MetaData, String, Table, Text

metadata = MetaData()
projects = Table(
    "evaluation_projects",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("name", String(160), nullable=False),
    Column("created_at", String(40), nullable=False),
)
datasets = Table(
    "evaluation_datasets",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False, index=True),
    Column("name", String(160), nullable=False),
    Column("purpose", String(16), nullable=False),
    Column("source", JSON, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("sample_count", Integer, nullable=False),
    Column("content_hash", String(64), nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("frozen_at", String(40), nullable=True),
    Column("frozen_by", String(64), nullable=True),
    CheckConstraint("status IN ('draft', 'frozen')", name="ck_evaluation_dataset_status"),
    CheckConstraint("purpose IN ('baseline', 'acceptance')", name="ck_evaluation_dataset_purpose"),
)
samples = Table(
    "evaluation_samples",
    metadata,
    Column("dataset_id", ForeignKey("evaluation_datasets.id"), primary_key=True),
    Column("sample_id", String(80), primary_key=True),
    Column("input", Text, nullable=False),
    Column("source_ref", String(500), nullable=False),
    Column("slice_tag", String(80), nullable=False),
)
references = Table(
    "evaluation_references",
    metadata,
    Column("dataset_id", String(64), primary_key=True),
    Column("sample_id", String(80), primary_key=True),
    Column("expected", Text, nullable=False),
    ForeignKeyConstraint(["dataset_id", "sample_id"], ["evaluation_samples.dataset_id", "evaluation_samples.sample_id"]),
)
audit = Table(
    "evaluation_data_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False),
    Column("dataset_id", ForeignKey("evaluation_datasets.id"), nullable=False, index=True),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("at", String(40), nullable=False),
)
