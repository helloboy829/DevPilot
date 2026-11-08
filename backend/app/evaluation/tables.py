"""App-owned evaluation tables, intentionally separate from Harness metadata."""

from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

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

# A plan must reference a request belonging to the SAME project component.
Index("uq_evaluation_request_component_id", request_versions.c.project_id, request_versions.c.component_id, request_versions.c.id, unique=True)
plans = Table(
    "evaluation_plans",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("request_version_id", String(64), nullable=False),
    Column("dataset_id", String(64), nullable=False),
    Column("version_label", String(80), nullable=False),
    Column("label_key", String(240), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("definition_hash", String(64), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    ForeignKeyConstraint(["project_id", "component_id", "request_version_id"], ["evaluation_request_versions.project_id", "evaluation_request_versions.component_id", "evaluation_request_versions.id"]),
    ForeignKeyConstraint(["project_id", "dataset_id"], ["evaluation_datasets.project_id", "evaluation_datasets.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_plan_project_id"),
    UniqueConstraint("component_id", "label_key", name="uq_evaluation_plan_label"),
    CheckConstraint("scope = 'frozen_definition_only'", name="ck_evaluation_plan_scope"),
)
plan_audit = Table(
    "evaluation_plan_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("plan_id", String(64), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
)

# Technical dispatch metadata only: not admission, output evidence or quality verdicts.
dispatch_runs = Table(
    "evaluation_dispatch_runs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("plan_id", String(64), nullable=False),
    Column("plan_hash", String(64), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("request_count", Integer, nullable=False),
    Column("concurrency", Integer, nullable=False),
    Column("timeout_ms", Integer, nullable=False),
    Column("max_total_body_bytes", Integer, nullable=False),
    Column("max_response_bytes", Integer, nullable=False),
    Column("max_total_response_bytes", Integer, nullable=False),
    Column("lease_grace_ms", Integer, nullable=False),
    Column("started_at_ms", BigInteger, nullable=False),
    Column("deadline_ms", BigInteger, nullable=False),
    Column("reserved_body_bytes", Integer, nullable=False),
    Column("reserved_response_bytes", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("finished_at_ms", BigInteger, nullable=True),
    Column("stop_reason", String(32), nullable=True),
    ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_dispatch_project_id"),
    CheckConstraint("scope = 'dispatch_journal_only'", name="ck_evaluation_dispatch_scope"),
    CheckConstraint("status IN ('recording', 'recording_finished', 'interrupted')", name="ck_evaluation_dispatch_status"),
    CheckConstraint("request_count BETWEEN 1 AND 10000 AND concurrency BETWEEN 1 AND 64 AND timeout_ms BETWEEN 100 AND 300000", name="ck_evaluation_dispatch_limits"),
    CheckConstraint(
        "max_total_body_bytes BETWEEN 1 AND 67108864 AND max_response_bytes BETWEEN 1 AND 1048576 AND max_total_response_bytes BETWEEN 2 AND 67108864 AND "
        "max_total_response_bytes >= max_response_bytes + 1 AND lease_grace_ms BETWEEN 100 AND 30000",
        name="ck_evaluation_dispatch_budgets",
    ),
    CheckConstraint("reserved_body_bytes BETWEEN 0 AND max_total_body_bytes AND reserved_response_bytes BETWEEN 0 AND max_total_response_bytes", name="ck_evaluation_dispatch_reserved"),
    CheckConstraint("revision >= 1 AND started_at_ms > 0 AND deadline_ms > started_at_ms", name="ck_evaluation_dispatch_clock"),
)
dispatches = Table(
    "evaluation_dispatches",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("sample_id", String(80), nullable=False),
    Column("state", String(32), nullable=False),
    Column("ticket_hash", String(64), nullable=True),
    Column("dispatched_at_ms", BigInteger, nullable=True),
    Column("lease_expires_at_ms", BigInteger, nullable=True),
    Column("kind", String(32), nullable=True),
    Column("http_status", Integer, nullable=True),
    Column("body_bytes", Integer, nullable=True),
    Column("elapsed_ms", Float, nullable=True),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    CheckConstraint("ordinal BETWEEN 1 AND 10000", name="ck_evaluation_dispatch_ordinal"),
    CheckConstraint("state IN ('pending','dispatched','observed','delivery_unknown','not_dispatched')", name="ck_evaluation_dispatch_state"),
)
Index("ix_evaluation_dispatch_state_lease", dispatches.c.run_id, dispatches.c.state, dispatches.c.lease_expires_at_ms)
dispatch_audit = Table(
    "evaluation_dispatch_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("action", String(40), nullable=False),
    Column("ordinal", Integer, nullable=True),
    Column("at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    UniqueConstraint("run_id", "sequence", name="uq_evaluation_dispatch_audit_sequence"),
)

# Append-only extracted text evidence and human-review revisions; no execution admission.
output_evidence = Table(
    "evaluation_output_evidence",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("encrypted_payload", Text, nullable=False),
    Column("protected_hash", String(64), nullable=False),
    Column("observation_hash", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
    CheckConstraint("ordinal BETWEEN 1 AND 10000 AND created_at_ms > 0", name="ck_evaluation_output_bounds"),
)
case_reviews = Table(
    "evaluation_case_reviews",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("ordinal", Integer, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("case_hash", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("reviewer_id", String(64), nullable=False),
    Column("encrypted_payload", Text, nullable=False),
    Column("protected_hash", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
    CheckConstraint("ordinal BETWEEN 1 AND 10000 AND revision BETWEEN 1 AND 100 AND created_at_ms > 0", name="ck_evaluation_review_bounds"),
    CheckConstraint("decision IN ('pass','fail','uncertain')", name="ck_evaluation_review_decision"),
)
