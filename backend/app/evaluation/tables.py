"""App-owned evaluation tables, intentionally separate from Harness metadata."""

from sqlalchemy import JSON, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

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

# Composite ownership keys let the database reject accidental cross-project bindings.

Index("uq_evaluation_dataset_project_id", datasets.c.project_id, datasets.c.id, unique=True)
project_components = Table(
    "evaluation_project_components",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False),
    Column("source_component_id", String(64), nullable=False),
    Column("name_at_link", String(255), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("created_at", String(40), nullable=False),
    UniqueConstraint("project_id", "id", name="uq_evaluation_component_project_id"),
    UniqueConstraint("project_id", "source_component_id", name="uq_evaluation_component_source"),
    CheckConstraint("kind IN ('llm','cv','agent','model')", name="ck_evaluation_component_kind"),
)
submissions = Table(
    "evaluation_submissions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("version_label", String(80), nullable=False),
    Column("label_key", String(240), nullable=False),
    Column("dataset_id", String(64), nullable=False),
    Column("dataset_revision", Integer, nullable=False),
    Column("dataset_hash", String(64), nullable=False),
    Column("dataset_purpose", String(16), nullable=False),
    Column("component_snapshot", JSON, nullable=False),
    Column("scope", String(32), nullable=False),
    Column("submission_hash", String(64), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    ForeignKeyConstraint(["project_id", "dataset_id"], ["evaluation_datasets.project_id", "evaluation_datasets.id"]),
    UniqueConstraint("component_id", "label_key", name="uq_evaluation_submission_label"),
    CheckConstraint("scope = 'inventory_only'", name="ck_evaluation_submission_scope"),
)
registry_audit = Table(
    "evaluation_registry_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False, index=True),
    Column("component_id", String(64), nullable=False),
    Column("submission_id", String(64), nullable=True),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("at", String(40), nullable=False),
)


# Append-only request definitions. Entire URL, body and header values are encrypted.
request_versions = Table(
    "evaluation_request_versions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("version_label", String(80), nullable=False),
    Column("label_key", String(240), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("request_template", JSON, nullable=False),
    Column("encrypted_payload", Text, nullable=False),
    Column("protected_hash", String(64), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_request_project_id"),
    UniqueConstraint("component_id", "label_key", name="uq_evaluation_request_label"),
    CheckConstraint("scope = 'request_definition_only'", name="ck_evaluation_request_scope"),
)
request_version_audit = Table(
    "evaluation_request_version_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("request_version_id", String(64), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "request_version_id"], ["evaluation_request_versions.project_id", "evaluation_request_versions.id"]),
)
