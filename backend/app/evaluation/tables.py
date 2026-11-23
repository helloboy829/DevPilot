"""App-owned evaluation tables, intentionally separate from Harness metadata."""

from sqlalchemy import JSON, BigInteger, Boolean, CheckConstraint, Column, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, MetaData, String, Table, Text, UniqueConstraint

metadata = MetaData()
projects = Table(
    "evaluation_projects",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False, index=True),
    Column("name", String(160), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("result_revision", Integer, nullable=False, server_default="0"),
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
Index("ix_evaluation_dispatch_run_project_started_id", dispatch_runs.c.project_id, dispatch_runs.c.started_at_ms.desc(), dispatch_runs.c.id.asc())


def _request_body_sha256_constraint():
    cleaned = "request_body_sha256"
    for character in "0123456789abcdef":
        cleaned = f"replace({cleaned}, '{character}', '')"
    return f"request_body_sha256 IS NOT NULL AND length(request_body_sha256) = 64 AND request_body_sha256 = lower(request_body_sha256) AND length({cleaned}) = 0"


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

# Raw response bytes live in encrypted object storage; this row is the durable
# manifest and receipt, not a queryable copy of the response body.
response_artifacts = Table(
    "evaluation_response_artifacts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("hash_scope", String(8), nullable=False),
    Column("request_body_sha256", String(64), nullable=True),
    Column("request_body_bytes", Integer, nullable=True),
    Column("request_contract_version", String(32), nullable=True),
    Column("response_sha256", String(64), nullable=True),
    Column("captured_prefix_sha256", String(64), nullable=True),
    Column("captured_bytes", Integer, nullable=False),
    Column("observed_bytes", Integer, nullable=False),
    Column("content_type", String(127), nullable=True),
    Column("content_encoding", String(16), nullable=True),
    Column("key_version", String(16), nullable=True),
    Column("sealed_sha256", String(64), nullable=True),
    Column("sealed_bytes", Integer, nullable=True),
    Column("receipt_hash", String(64), nullable=True),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("updated_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id"], ["evaluation_projects.id"], name="fk_evaluation_response_artifact_project"),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"], name="fk_evaluation_response_artifact_run"),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"], name="fk_evaluation_response_artifact_dispatch"),
    UniqueConstraint("run_id", "ordinal", name="uq_evaluation_response_artifact_dispatch"),
    CheckConstraint("ordinal BETWEEN 1 AND 10000", name="ck_evaluation_response_artifact_ordinal"),
    CheckConstraint(
        "status IN ('pending','complete','partial','truncated','policy_skipped','not_received','write_failed','write_unknown','unavailable_legacy')",
        name="ck_evaluation_response_artifact_status",
    ),
    CheckConstraint("hash_scope IN ('none','full','prefix')", name="ck_evaluation_response_artifact_hash_scope"),
    CheckConstraint(
        "((request_body_sha256 IS NULL AND request_body_bytes IS NULL AND request_contract_version IS NULL) OR "
        f"({_request_body_sha256_constraint()} AND request_body_bytes BETWEEN 0 AND 262144 AND request_contract_version IS NOT NULL AND length(request_contract_version) BETWEEN 1 AND 32))",
        name="ck_evaluation_response_artifact_request_identity",
    ),
    CheckConstraint(
        "((hash_scope = 'none' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NULL) OR "
        "(hash_scope = 'full' AND response_sha256 IS NOT NULL AND length(response_sha256) = 64 AND captured_prefix_sha256 IS NULL) OR "
        "(hash_scope = 'prefix' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NOT NULL AND length(captured_prefix_sha256) = 64))",
        name="ck_evaluation_response_artifact_hash",
    ),
    CheckConstraint(
        "((sealed_sha256 IS NULL AND sealed_bytes IS NULL AND key_version IS NULL AND receipt_hash IS NULL) OR "
        "(sealed_sha256 IS NOT NULL AND length(sealed_sha256) = 64 "
        "AND sealed_bytes BETWEEN captured_bytes + 28 AND captured_bytes + 2113 "
        "AND key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 16 "
        "AND receipt_hash IS NOT NULL AND length(receipt_hash) = 64))",
        name="ck_evaluation_response_artifact_sealed_receipt",
    ),
    CheckConstraint(
        "captured_bytes BETWEEN 0 AND 1048576 AND observed_bytes BETWEEN 0 AND 1048577 AND observed_bytes >= captured_bytes",
        name="ck_evaluation_response_artifact_bytes",
    ),
    CheckConstraint("content_type IS NULL OR length(content_type) BETWEEN 1 AND 127", name="ck_evaluation_response_artifact_content_type"),
    CheckConstraint("content_encoding IS NULL OR content_encoding IN ('identity','gzip','deflate','br','zstd','compress','other')", name="ck_evaluation_response_artifact_content_encoding"),
    CheckConstraint(
        "((status = 'pending' AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
        "(status = 'complete' AND hash_scope = 'full' AND sealed_sha256 IS NOT NULL AND captured_bytes = observed_bytes) OR "
        "(status IN ('partial','truncated') AND hash_scope = 'prefix' AND sealed_sha256 IS NOT NULL) OR "
        "(status IN ('policy_skipped','not_received','unavailable_legacy') AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
        "status IN ('write_failed','write_unknown'))",
        name="ck_evaluation_response_artifact_state",
    ),
    CheckConstraint(
        "status NOT IN ('complete','partial','truncated','not_received') OR (request_body_sha256 IS NOT NULL AND request_body_bytes IS NOT NULL AND request_contract_version IS NOT NULL)",
        name="ck_evaluation_response_artifact_request_recorded",
    ),
    CheckConstraint(
        "status != 'write_failed' OR request_body_sha256 IS NOT NULL OR (request_body_bytes IS NULL AND request_contract_version IS NULL AND hash_scope = 'none' AND captured_bytes = 0 AND observed_bytes = 0)",
        name="ck_evaluation_response_artifact_write_failed_identity",
    ),
    CheckConstraint("created_at_ms > 0 AND updated_at_ms >= created_at_ms AND updated_at_ms <= 253402300799000", name="ck_evaluation_response_artifact_clock"),
)
Index("ix_evaluation_response_artifact_status_time", response_artifacts.c.status, response_artifacts.c.updated_at_ms)

# Short-lived, actor-bound grants and metadata-only access audit. Raw tokens and
# response bytes never enter either table.
evidence_access_grants = Table(
    "evaluation_evidence_access_grants",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("artifact_id", String(32), nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("evidence_kind", String(16), nullable=False),
    Column("evidence_hash", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("expires_at_ms", BigInteger, nullable=False),
    Column("consumed_at_ms", BigInteger, nullable=True),
    Column("revoked_at_ms", BigInteger, nullable=True),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
    ForeignKeyConstraint(["artifact_id"], ["evaluation_response_artifacts.id"]),
    CheckConstraint("length(token_hash) = 64 AND token_hash = lower(token_hash)", name="ck_evaluation_evidence_grant_token_hash"),
    CheckConstraint("evidence_kind = 'response' AND length(evidence_hash) = 64", name="ck_evaluation_evidence_grant_evidence"),
    CheckConstraint("ordinal BETWEEN 1 AND 10000 AND length(actor_id) BETWEEN 1 AND 64", name="ck_evaluation_evidence_grant_subject"),
    CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms - created_at_ms <= 300000", name="ck_evaluation_evidence_grant_expiry"),
    CheckConstraint("consumed_at_ms IS NULL OR consumed_at_ms >= created_at_ms", name="ck_evaluation_evidence_grant_consumed"),
    CheckConstraint("revoked_at_ms IS NULL OR revoked_at_ms >= created_at_ms", name="ck_evaluation_evidence_grant_revoked"),
)
evidence_access_audit = Table(
    "evaluation_evidence_access_audit",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("evidence_kind", String(16), nullable=False),
    Column("evidence_hash", String(64), nullable=False),
    Column("action", String(16), nullable=False),
    Column("authorization_basis", String(32), nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
    UniqueConstraint("run_id", "sequence", name="uq_evaluation_evidence_audit_sequence"),
    CheckConstraint("sequence BETWEEN 1 AND 10000000 AND ordinal BETWEEN 1 AND 10000", name="ck_evaluation_evidence_audit_sequence"),
    CheckConstraint("evidence_kind = 'response' AND length(evidence_hash) = 64", name="ck_evaluation_evidence_audit_evidence"),
    CheckConstraint("action IN ('granted','read') AND authorization_basis = 'project_member'", name="ck_evaluation_evidence_audit_action"),
    CheckConstraint("length(actor_id) BETWEEN 1 AND 64 AND at_ms > 0", name="ck_evaluation_evidence_audit_actor_clock"),
)

# Independent human execution admission; journal scope remains metadata-only.
execution_guard = Table(
    "evaluation_execution_guard",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("policy_hash", String(64), nullable=True),
    CheckConstraint("id = 1", name="ck_evaluation_execution_guard"),
)
executions = Table(
    "evaluation_executions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False, unique=True),
    Column("plan_hash", String(64), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("state", String(32), nullable=False),
    Column("reservation_held", Boolean, nullable=False),
    Column("claim_hash", String(64), nullable=True),
    Column("reserved_concurrency", Integer, nullable=False),
    Column("reserved_body_bytes", BigInteger, nullable=False),
    Column("reserved_response_bytes", BigInteger, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("deadline_ms", BigInteger, nullable=False),
    Column("finished_at_ms", BigInteger, nullable=True),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    CheckConstraint("scope = 'admitted_qa_json'", name="ck_evaluation_execution_scope"),
    CheckConstraint("state IN ('queued','running','cancel_requested','collected','interrupted')", name="ck_evaluation_execution_state"),
    CheckConstraint("reserved_concurrency BETWEEN 1 AND 64 AND reserved_body_bytes BETWEEN 1 AND 67108864 AND reserved_response_bytes BETWEEN 2 AND 67108864", name="ck_evaluation_execution_reserved"),
    CheckConstraint("created_at_ms > 0 AND deadline_ms > created_at_ms", name="ck_evaluation_execution_clock"),
)
Index("ix_evaluation_execution_queue", executions.c.reservation_held, executions.c.state, executions.c.created_at_ms)

# Append-only report drafts; source summaries and exact templates are frozen in JSON.
report_archives = Table(
    "evaluation_report_archives",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False),
    Column("root_id", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("supersedes_id", String(32), nullable=True),
    Column("title", String(160), nullable=False),
    Column("template_id", String(64), nullable=False),
    Column("template_version", String(32), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("archive_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    UniqueConstraint("project_id", "id", name="uq_evaluation_archive_project_id"),
    UniqueConstraint("project_id", "supersedes_id", name="uq_evaluation_archive_successor"),
    UniqueConstraint("root_id", "revision", name="uq_evaluation_archive_revision"),
    ForeignKeyConstraint(["project_id", "supersedes_id"], ["evaluation_report_archives.project_id", "evaluation_report_archives.id"]),
    CheckConstraint("revision BETWEEN 1 AND 1000 AND created_at_ms > 0", name="ck_evaluation_archive_bounds"),
)
Index("ix_evaluation_archive_project_time", report_archives.c.project_id, report_archives.c.created_at_ms)

# Immutable human retest comparisons, no raw Q/A or automatic acceptance.
retest_archives = Table(
    "evaluation_retest_archives",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("baseline_run_id", String(64), nullable=False),
    Column("retest_run_id", String(64), nullable=False),
    Column("baseline_label", String(80), nullable=False),
    Column("retest_label", String(80), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("archive_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    ForeignKeyConstraint(["project_id", "baseline_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["project_id", "retest_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    UniqueConstraint("project_id", "baseline_run_id", "retest_run_id", name="uq_evaluation_retest_pair"),
    CheckConstraint("baseline_run_id <> retest_run_id AND created_at_ms > 0", name="ck_evaluation_retest_bounds"),
)
Index("ix_evaluation_retest_project_time", retest_archives.c.project_id, retest_archives.c.created_at_ms)

# Explicitly granted independent human review. Never replaces owner decisions or approval.
review_tasks = Table(
    "evaluation_review_tasks",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("case_hash", String(64), nullable=False),
    Column("subject_hash", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("round", Integer, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
    CheckConstraint("ordinal BETWEEN 1 AND 10000 AND round BETWEEN 1 AND 10 AND revision BETWEEN 1 AND 10000 AND created_at_ms > 0", name="ck_evaluation_task_bounds"),
    CheckConstraint("status IN ('queued','in_review','escalated','resolved','cancelled')", name="ck_evaluation_task_state"),
)
review_task_assignments = Table(
    "evaluation_review_task_assignments",
    metadata,
    Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
    Column("round", Integer, primary_key=True),
    Column("role", String(16), primary_key=True),
    Column("actor_id", String(64), nullable=False),
    Column("status", String(16), nullable=False),
    Column("lease_until_ms", BigInteger, nullable=True),
    Column("viewed_revision", Integer, nullable=True),
    UniqueConstraint("task_id", "round", "actor_id", name="uq_evaluation_task_actor"),
    CheckConstraint("round BETWEEN 1 AND 10 AND role IN ('reviewer_1','reviewer_2','arbitrator')", name="ck_evaluation_assignment_role"),
    CheckConstraint("status IN ('offered','active','submitted','released')", name="ck_evaluation_assignment_status"),
)
review_task_decisions = Table(
    "evaluation_review_task_decisions",
    metadata,
    Column("task_id", String(32), primary_key=True),
    Column("round", Integer, primary_key=True),
    Column("role", String(16), primary_key=True),
    Column("actor_id", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("encrypted_payload", Text, nullable=False),
    Column("protected_hash", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["task_id", "round", "role"], ["evaluation_review_task_assignments.task_id", "evaluation_review_task_assignments.round", "evaluation_review_task_assignments.role"]),
    CheckConstraint("decision IN ('pass','fail','uncertain') AND created_at_ms > 0", name="ck_evaluation_task_decision"),
)
review_task_resolutions = Table(
    "evaluation_review_task_resolutions",
    metadata,
    Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
    Column("round", Integer, primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("document", JSON, nullable=False),
    Column("resolution_hash", String(64), nullable=False),
    CheckConstraint("round BETWEEN 1 AND 10 AND revision BETWEEN 1 AND 2", name="ck_evaluation_resolution_bounds"),
)
review_task_audit = Table(
    "evaluation_review_task_audit",
    metadata,
    Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("round", Integer, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(32), nullable=False),
    Column("subject_hash", String(64), nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    Column("encrypted_reason", Text, nullable=True),
    Column("protected_hash", String(64), nullable=True),
)
Index("ix_evaluation_review_task_project", review_tasks.c.project_id, review_tasks.c.created_at_ms)
Index("ix_evaluation_review_assignment_actor", review_task_assignments.c.actor_id, review_task_assignments.c.task_id)

# Append-only post-collection independent assessments; no publication/approval pointer.
run_assessments = Table(
    "evaluation_run_assessments",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("summary_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    Column("assessment_hash", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    UniqueConstraint("run_id", "revision", name="uq_evaluation_assessment_revision"),
    CheckConstraint("revision BETWEEN 1 AND 1000 AND created_at_ms > 0", name="ck_evaluation_assessment_bounds"),
)
Index("ix_evaluation_assessment_run_revision", run_assessments.c.run_id, run_assessments.c.revision)

# Explicit independent historical sources; legacy owner archives stay separate.
independent_report_archives = Table(
    "evaluation_independent_report_archives",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", ForeignKey("evaluation_projects.id"), nullable=False),
    Column("root_id", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("supersedes_id", String(32), nullable=True),
    Column("title", String(160), nullable=False),
    Column("template_id", String(64), nullable=False),
    Column("template_version", String(32), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("archive_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    UniqueConstraint("project_id", "id", name="uq_evaluation_ind_report_project_id"),
    UniqueConstraint("project_id", "supersedes_id", name="uq_evaluation_ind_report_successor"),
    UniqueConstraint("root_id", "revision", name="uq_evaluation_ind_report_revision"),
    ForeignKeyConstraint(["project_id", "supersedes_id"], ["evaluation_independent_report_archives.project_id", "evaluation_independent_report_archives.id"]),
    CheckConstraint("revision BETWEEN 1 AND 1000 AND created_at_ms > 0", name="ck_evaluation_ind_report_bounds"),
)
Index("ix_evaluation_ind_report_project_time", independent_report_archives.c.project_id, independent_report_archives.c.created_at_ms)

independent_retest_archives = Table(
    "evaluation_independent_retest_archives",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("baseline_run_id", String(64), nullable=False),
    Column("retest_run_id", String(64), nullable=False),
    Column("baseline_assessment_id", String(32), ForeignKey("evaluation_run_assessments.id"), nullable=False),
    Column("retest_assessment_id", String(32), ForeignKey("evaluation_run_assessments.id"), nullable=False),
    Column("baseline_label", String(80), nullable=False),
    Column("retest_label", String(80), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("archive_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    ForeignKeyConstraint(["project_id", "baseline_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["project_id", "retest_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    UniqueConstraint("project_id", "baseline_assessment_id", "retest_assessment_id", name="uq_evaluation_ind_retest_pair"),
    CheckConstraint("baseline_run_id <> retest_run_id AND created_at_ms > 0", name="ck_evaluation_ind_retest_bounds"),
)
Index("ix_evaluation_ind_retest_project_time", independent_retest_archives.c.project_id, independent_retest_archives.c.created_at_ms)

# Explicit recipient-bound external configuration; ciphertext never metadata.
exports = Table(
    "evaluation_authorized_exports",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("plan_id", String(64), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("receipt_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    Column("encrypted_bundle", Text, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_export_project_id"),
    CheckConstraint("created_at_ms > 0", name="ck_evaluation_export_time"),
)
Index("ix_evaluation_export_project_time", exports.c.project_id, exports.c.created_at_ms)
export_audit = Table(
    "evaluation_export_audit",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("export_id", String(32), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(32), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "export_id"], ["evaluation_authorized_exports.project_id", "evaluation_authorized_exports.id"]),
    UniqueConstraint("export_id", "sequence", name="uq_evaluation_export_audit_sequence"),
    CheckConstraint("sequence > 0", name="ck_evaluation_export_audit_sequence"),
    CheckConstraint("action IN ('export_created', 'bundle_opened') AND at_ms > 0", name="ck_evaluation_export_audit"),
)
Index("ix_evaluation_export_audit_export", export_audit.c.project_id, export_audit.c.export_id)

# Technical-only quarantine: no platform-run/evidence/review/approval foreign key.
external_qa_intakes = Table(
    "evaluation_external_qa_intakes",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("export_id", String(32), nullable=False),
    Column("original_run_id", String(36), nullable=False),
    Column("snapshot_hash", String(64), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("archive_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    Column("canonical_receipt", Text, nullable=False),
    Column("canonical_reconciliation", Text, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "export_id"], ["evaluation_authorized_exports.project_id", "evaluation_authorized_exports.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_external_intake_project_id"),
    UniqueConstraint("export_id", "original_run_id", "snapshot_hash", name="uq_evaluation_external_intake_snapshot"),
    CheckConstraint("created_at_ms > 0 AND created_at_ms <= 253402300799000", name="ck_evaluation_external_intake_time"),
    CheckConstraint("length(canonical_receipt) BETWEEN 1 AND 8192 AND length(canonical_reconciliation) BETWEEN 1 AND 8192", name="ck_evaluation_external_intake_size"),
)
Index("ix_evaluation_external_intake_project_time", external_qa_intakes.c.project_id, external_qa_intakes.c.created_at_ms)
external_qa_intake_audit = Table(
    "evaluation_external_qa_intake_audit",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("intake_id", String(32), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(32), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "intake_id"], ["evaluation_external_qa_intakes.project_id", "evaluation_external_qa_intakes.id"]),
    UniqueConstraint("intake_id", "sequence", name="uq_evaluation_external_intake_audit_sequence"),
    CheckConstraint("sequence > 0", name="ck_evaluation_external_intake_audit_sequence"),
    CheckConstraint("action = 'metadata_quarantined' AND at_ms > 0", name="ck_evaluation_external_intake_audit"),
)
Index("ix_evaluation_external_intake_audit_intake", external_qa_intake_audit.c.project_id, external_qa_intake_audit.c.intake_id)

# Explicit human formal approval over an immutable independent assessment.
# Decision is always supplied by the approver; case outcomes and threshold
# arithmetic never write an approval. Revocation appends a new revision.
run_approvals = Table(
    "evaluation_run_approvals",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("assessment_id", String(32), nullable=False),
    Column("assessment_hash", String(64), nullable=False),
    Column("approver_id", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("document", JSON, nullable=False),
    Column("approval_hash", String(64), nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["assessment_id"], ["evaluation_run_assessments.id"]),
    UniqueConstraint("run_id", "revision", name="uq_evaluation_approval_revision"),
    CheckConstraint("revision BETWEEN 1 AND 1000 AND created_at_ms > 0", name="ck_evaluation_approval_bounds"),
    CheckConstraint("decision IN ('approved','revoked')", name="ck_evaluation_approval_decision"),
)
Index("ix_evaluation_approval_run_revision", run_approvals.c.run_id, run_approvals.c.revision)
# The composite primary key owns revision uniqueness; a duplicate UNIQUE
# declaration does not round-trip through PostgreSQL/Alembic reflection.
approval_signoff_policies = Table(
    "evaluation_approval_signoff_policies",
    metadata,
    Column("project_id", String(64), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("required_distinct_approvers", Integer, nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("document", JSON, nullable=False),
    Column("policy_hash", String(64), nullable=False),
    ForeignKeyConstraint(["project_id"], ["evaluation_projects.id"]),
    CheckConstraint("revision BETWEEN 1 AND 1000 AND required_distinct_approvers BETWEEN 1 AND 10 AND created_at_ms > 0", name="ck_evaluation_signoff_policy_bounds"),
)

approval_audit = Table(
    "evaluation_approval_audit",
    metadata,
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("approval_id", String(32), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(16), nullable=False),
    Column("subject_hash", String(64), nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    CheckConstraint("sequence > 0 AND revision BETWEEN 1 AND 1000 AND at_ms > 0", name="ck_evaluation_approval_audit_bounds"),
    CheckConstraint("action IN ('approved','revoked')", name="ck_evaluation_approval_audit_action"),
)
Index("ix_evaluation_approval_audit_run", approval_audit.c.run_id, approval_audit.c.sequence)

# Assigned aggregate-only signatures. Request events are durable operation
# receipts and in-app notifications; no background delivery or external outbox.
approval_requests = Table(
    "evaluation_approval_requests",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("assessment_id", String(32), nullable=False),
    Column("assessment_hash", String(64), nullable=False),
    Column("approver_id", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("expires_at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("subject_hash", String(64), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("latest_approval_id", String(32), ForeignKey("evaluation_run_approvals.id"), nullable=True),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
    ForeignKeyConstraint(["assessment_id"], ["evaluation_run_assessments.id"]),
    CheckConstraint("owner_id <> approver_id", name="ck_evaluation_approval_request_independent"),
    CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms <= 253402300799000", name="ck_evaluation_approval_request_time"),
    CheckConstraint(
        "(status = 'pending' AND revision = 1 AND latest_approval_id IS NULL) OR "
        "(status = 'cancelled' AND revision = 2 AND latest_approval_id IS NULL) OR "
        "(status = 'approved' AND revision = 2 AND latest_approval_id IS NOT NULL) OR "
        "(status = 'revoked' AND revision = 3 AND latest_approval_id IS NOT NULL)",
        name="ck_evaluation_approval_request_state",
    ),
)

# Material intake remains separate from project datasets until explicit archival.
material_batches = Table(
    "evaluation_material_batches",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("name", String(160), nullable=False),
    Column("status", String(16), nullable=False, server_default="open"),
    Column("component_count", Integer, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("archived_at", String(40)),
    CheckConstraint("status IN ('open','archived')", name="ck_evaluation_material_batch_status"),
    CheckConstraint("component_count BETWEEN 1 AND 10000", name="ck_evaluation_material_batch_component_count"),
    CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_material_batch_owner"),
    Index("ix_evaluation_material_batch_owner_created", "owner_id", "created_at", "id"),
)
material_components = Table(
    "evaluation_material_components",
    metadata,
    Column("batch_id", String(32), ForeignKey("evaluation_material_batches.id", ondelete="CASCADE"), primary_key=True),
    Column("component_id", String(80), primary_key=True),
    Column("name", String(160), nullable=False),
    Column("kind", String(16), nullable=False),
    Column("purpose", String(500), nullable=False),
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("reason", String(500)),
    CheckConstraint("kind IN ('llm','cv','agent','model')", name="ck_evaluation_material_component_kind"),
    CheckConstraint("status IN ('pending','parsed','blocked','excluded','candidate','archived')", name="ck_evaluation_material_component_status"),
)
material_artifacts = Table(
    "evaluation_material_artifacts",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("batch_id", String(32), ForeignKey("evaluation_material_batches.id", ondelete="CASCADE"), nullable=False),
    Column("file_name", String(255), nullable=False),
    Column("authorization_basis", String(32), nullable=False),
    Column("purpose", String(500), nullable=False),
    Column("sensitivity", String(16), nullable=False),
    Column("retention_until", String(40), nullable=False),
    Column("status", String(16), nullable=False, server_default="pending_upload"),
    Column("storage_key", String(128)),
    Column("sha256", String(64)),
    Column("size_bytes", BigInteger),
    Column("created_at", String(40), nullable=False),
    Column("uploaded_at", String(40)),
    Column("parse_status", String(16), nullable=False, server_default="pending"),
    Column("parser_version", String(32)),
    Column("parse_result_hash", String(64)),
    Column("parse_block_count", Integer),
    Column("parse_reason", String(500)),
    Column("parsed_at", String(40)),
    UniqueConstraint("batch_id", "id", name="uq_evaluation_material_artifact_batch_id"),
    CheckConstraint("authorization_basis IN ('user_provided','public_domain','license','contract','explicit_consent')", name="ck_evaluation_material_artifact_authorization"),
    CheckConstraint("sensitivity IN ('public','internal','confidential','restricted')", name="ck_evaluation_material_artifact_sensitivity"),
    CheckConstraint("status IN ('pending_upload','uploaded','write_failed','write_unknown')", name="ck_evaluation_material_artifact_status"),
    CheckConstraint("size_bytes IS NULL OR size_bytes BETWEEN 0 AND 104857600", name="ck_evaluation_material_artifact_size"),
    CheckConstraint("sha256 IS NULL OR (length(sha256) = 64 AND sha256 = lower(sha256))", name="ck_evaluation_material_artifact_sha256"),
    CheckConstraint("parse_status IN ('pending','parsed','blocked')", name="ck_evaluation_material_artifact_parse_status"),
    CheckConstraint("parse_result_hash IS NULL OR (length(parse_result_hash) = 64 AND parse_result_hash = lower(parse_result_hash))", name="ck_evaluation_material_artifact_parse_hash"),
    CheckConstraint("parse_block_count IS NULL OR parse_block_count BETWEEN 0 AND 20000", name="ck_evaluation_material_artifact_parse_blocks"),
)
material_artifact_components = Table(
    "evaluation_material_artifact_components",
    metadata,
    Column("batch_id", String(32), primary_key=True),
    Column("artifact_id", String(64), primary_key=True),
    Column("component_id", String(80), primary_key=True),
    ForeignKeyConstraint(["batch_id", "artifact_id"], ["evaluation_material_artifacts.batch_id", "evaluation_material_artifacts.id"], ondelete="CASCADE"),
    ForeignKeyConstraint(["batch_id", "component_id"], ["evaluation_material_components.batch_id", "evaluation_material_components.component_id"], ondelete="CASCADE"),
)
material_preview_receipts = Table(
    "evaluation_material_preview_receipts",
    metadata,
    Column("operation_id", String(36), primary_key=True),
    Column("owner_id", String(64), nullable=False),
    Column("batch_id", String(32), nullable=False),
    Column("artifact_id", String(64), nullable=False),
    Column("parse_status", String(16), nullable=False),
    Column("parser_version", String(32), nullable=False),
    Column("result_hash", String(64), nullable=False),
    Column("block_count", Integer, nullable=False),
    Column("reason", String(500)),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["batch_id", "artifact_id"], ["evaluation_material_artifacts.batch_id", "evaluation_material_artifacts.id"], ondelete="CASCADE"),
    CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_material_preview_owner"),
    CheckConstraint("parse_status IN ('parsed','blocked')", name="ck_evaluation_material_preview_status"),
    CheckConstraint("length(result_hash) = 64 AND result_hash = lower(result_hash)", name="ck_evaluation_material_preview_hash"),
    CheckConstraint("block_count BETWEEN 0 AND 20000", name="ck_evaluation_material_preview_blocks"),
)
Index("ix_evaluation_material_preview_owner_created", material_preview_receipts.c.owner_id, material_preview_receipts.c.created_at)
Index("ix_evaluation_approval_request_inbox", approval_requests.c.approver_id, approval_requests.c.created_at_ms)
Index("ix_evaluation_approval_request_run", approval_requests.c.run_id)

approval_request_events = Table(
    "evaluation_approval_request_events",
    metadata,
    Column("request_id", String(32), ForeignKey("evaluation_approval_requests.id"), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("operation_id", String(32), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(16), nullable=False),
    Column("at_ms", BigInteger, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("receipt", JSON, nullable=False),
    Column("previous_hash", String(64), nullable=True),
    Column("event_hash", String(64), nullable=False),
    UniqueConstraint("request_id", "operation_id", name="uq_evaluation_approval_request_operation"),
    CheckConstraint("revision BETWEEN 1 AND 3 AND at_ms > 0", name="ck_evaluation_approval_request_event_bounds"),
    CheckConstraint("action IN ('requested','approved','revoked','cancelled')", name="ck_evaluation_approval_request_event_action"),
)

approval_request_views = Table(
    "evaluation_approval_request_views",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("request_id", String(32), ForeignKey("evaluation_approval_requests.id"), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("request_revision", Integer, nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("summary_hash", String(64), nullable=False),
    Column("expires_at_ms", BigInteger, nullable=False),
    Column("document", JSON, nullable=False),
    Column("view_hash", String(64), nullable=False),
    CheckConstraint("request_revision = 1 AND expires_at_ms > 0 AND expires_at_ms <= 253402300799000", name="ck_evaluation_approval_request_view_bounds"),
)
Index("ix_evaluation_approval_request_view_request", approval_request_views.c.request_id)

performance_scenarios = Table(
    "evaluation_performance_scenarios",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("component_id", String(64), nullable=False),
    Column("plan_id", String(64), nullable=False),
    Column("version", Integer, nullable=False),
    Column("definition", JSON, nullable=False),
    Column("definition_hash", String(64), nullable=False),
    Column("created_by", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
    ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_performance_scenario_project_id"),
    CheckConstraint("version = 1", name="ck_evaluation_performance_scenario_version"),
    CheckConstraint("length(definition_hash) = 64 AND definition_hash = lower(definition_hash)", name="ck_evaluation_performance_scenario_hash"),
)
Index("ix_evaluation_performance_scenario_component", performance_scenarios.c.project_id, performance_scenarios.c.component_id, performance_scenarios.c.created_at, performance_scenarios.c.id)
performance_scenario_audit = Table(
    "evaluation_performance_scenario_audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("scenario_id", String(64), nullable=False),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "scenario_id"], ["evaluation_performance_scenarios.project_id", "evaluation_performance_scenarios.id"]),
    CheckConstraint("action = 'scenario_frozen'", name="ck_evaluation_performance_scenario_audit_action"),
)

performance_runs = Table(
    "evaluation_performance_runs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("scenario_id", String(64), nullable=False),
    Column("owner_id", String(64), nullable=False),
    Column("scenario_hash", String(64), nullable=False),
    Column("profile_hash", String(64), nullable=False),
    Column("manifest_hash", String(64), nullable=False),
    Column("population_count", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("window_start_ns", BigInteger),
    Column("window_end_ns", BigInteger),
    Column("created_at", String(40), nullable=False),
    Column("finished_at", String(40)),
    ForeignKeyConstraint(["project_id"], ["evaluation_projects.id"]),
    ForeignKeyConstraint(["project_id", "scenario_id"], ["evaluation_performance_scenarios.project_id", "evaluation_performance_scenarios.id"]),
    UniqueConstraint("project_id", "id", name="uq_evaluation_performance_run_project_id"),
    CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_performance_run_owner"),
    CheckConstraint("length(scenario_hash) = 64 AND scenario_hash = lower(scenario_hash)", name="ck_evaluation_performance_run_scenario_hash"),
    CheckConstraint("length(profile_hash) = 64 AND profile_hash = lower(profile_hash)", name="ck_evaluation_performance_run_profile_hash"),
    CheckConstraint("length(manifest_hash) = 64 AND manifest_hash = lower(manifest_hash)", name="ck_evaluation_performance_run_manifest_hash"),
    CheckConstraint("population_count BETWEEN 1 AND 11000", name="ck_evaluation_performance_run_population"),
    CheckConstraint("status IN ('created','running','completed','interrupted','failed')", name="ck_evaluation_performance_run_status"),
    CheckConstraint("(window_start_ns IS NULL AND window_end_ns IS NULL) OR (window_start_ns >= 0 AND window_end_ns >= window_start_ns)", name="ck_evaluation_performance_run_window"),
)
Index("ix_evaluation_performance_run_owner_created", performance_runs.c.owner_id, performance_runs.c.created_at, performance_runs.c.id)

performance_dispatches = Table(
    "evaluation_performance_dispatches",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("phase", String(16), nullable=False),
    Column("case_id", String(80), nullable=False),
    Column("iteration", Integer, nullable=False),
    Column("dispatch_id", String(64), nullable=False),
    Column("state", String(16), nullable=False),
    Column("lease_worker_id", String(64)),
    Column("lease_epoch", Integer, nullable=False, server_default="0"),
    Column("lease_expires_at_ms", BigInteger),
    Column("request_bytes", Integer),
    Column("request_hash", String(64)),
    Column("response_status", Integer),
    Column("response_bytes", Integer),
    Column("response_hash", String(64)),
    Column("evidence_ref", String(128)),
    Column("output_tokens", Integer),
    Column("token_source", String(40)),
    Column("send_started_ns", BigInteger),
    Column("finished_ns", BigInteger),
    Column("elapsed_ms", Float),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
    UniqueConstraint("run_id", "ordinal", name="uq_evaluation_performance_dispatch_ordinal"),
    UniqueConstraint("run_id", "dispatch_id", name="uq_evaluation_performance_dispatch_id"),
    UniqueConstraint("project_id", "run_id", "ordinal", "dispatch_id", name="uq_evaluation_performance_dispatch_binding"),
    CheckConstraint("ordinal BETWEEN 0 AND 10999 AND iteration >= 0", name="ck_evaluation_performance_dispatch_ordinal"),
    CheckConstraint("phase IN ('warmup','measurement')", name="ck_evaluation_performance_dispatch_phase"),
    CheckConstraint("state IN ('pending','dispatched','succeeded','failed','timeout','unknown','not_dispatched')", name="ck_evaluation_performance_dispatch_state"),
    CheckConstraint("lease_epoch >= 0", name="ck_evaluation_performance_dispatch_lease_epoch"),
    CheckConstraint("lease_worker_id IS NULL OR length(lease_worker_id) BETWEEN 1 AND 64", name="ck_evaluation_performance_dispatch_lease_worker"),
    CheckConstraint("lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0", name="ck_evaluation_performance_dispatch_lease_expiry"),
    CheckConstraint("request_bytes IS NULL OR request_bytes BETWEEN 0 AND 1048576", name="ck_evaluation_performance_dispatch_request_bytes"),
    CheckConstraint("response_bytes IS NULL OR response_bytes BETWEEN 0 AND 10000001", name="ck_evaluation_performance_dispatch_response_bytes"),
    CheckConstraint("request_hash IS NULL OR (length(request_hash) = 64 AND request_hash = lower(request_hash))", name="ck_evaluation_performance_dispatch_request_hash"),
    CheckConstraint("response_hash IS NULL OR (length(response_hash) = 64 AND response_hash = lower(response_hash))", name="ck_evaluation_performance_dispatch_response_hash"),
    CheckConstraint("response_status IS NULL OR response_status BETWEEN 100 AND 599", name="ck_evaluation_performance_dispatch_response_status"),
    CheckConstraint("output_tokens IS NULL OR (output_tokens >= 0 AND state = 'succeeded')", name="ck_evaluation_performance_dispatch_tokens"),
    CheckConstraint("token_source IS NULL OR length(token_source) BETWEEN 1 AND 40", name="ck_evaluation_performance_dispatch_token_source"),
    CheckConstraint(
        "(state IN ('pending','not_dispatched') AND send_started_ns IS NULL AND finished_ns IS NULL AND elapsed_ms IS NULL) OR "
        "(state = 'dispatched' AND send_started_ns >= 0 AND finished_ns IS NULL AND elapsed_ms IS NULL) OR "
        "(state = 'unknown' AND send_started_ns >= 0 AND ((finished_ns IS NULL AND elapsed_ms IS NULL) OR (finished_ns >= send_started_ns AND elapsed_ms >= 0))) OR "
        "(state IN ('succeeded','failed','timeout') AND send_started_ns >= 0 AND finished_ns >= send_started_ns AND elapsed_ms >= 0)",
        name="ck_evaluation_performance_dispatch_timing",
    ),
)
Index("ix_evaluation_performance_dispatch_run_state", performance_dispatches.c.project_id, performance_dispatches.c.run_id, performance_dispatches.c.state)
Index("ix_evaluation_performance_dispatch_evidence", performance_dispatches.c.evidence_ref)

performance_response_artifacts = Table(
    "evaluation_performance_response_artifacts",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("dispatch_id", String(64), nullable=False),
    Column("status", String(24), nullable=False),
    Column("hash_scope", String(8), nullable=False),
    Column("response_sha256", String(64)),
    Column("captured_prefix_sha256", String(64)),
    Column("captured_bytes", Integer, nullable=False),
    Column("observed_bytes", Integer, nullable=False),
    Column("content_type", String(127)),
    Column("content_encoding", String(16)),
    Column("key_version", String(16)),
    Column("sealed_sha256", String(64)),
    Column("sealed_bytes", Integer),
    Column("receipt_hash", String(64)),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("updated_at_ms", BigInteger, nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
    ForeignKeyConstraint(
        ["project_id", "run_id", "ordinal", "dispatch_id"],
        ["evaluation_performance_dispatches.project_id", "evaluation_performance_dispatches.run_id", "evaluation_performance_dispatches.ordinal", "evaluation_performance_dispatches.dispatch_id"],
        name="fk_evaluation_performance_response_artifact_dispatch",
    ),
    UniqueConstraint("run_id", "ordinal", name="uq_evaluation_performance_response_artifact_dispatch"),
    CheckConstraint("ordinal BETWEEN 0 AND 10999", name="ck_evaluation_performance_response_artifact_ordinal"),
    CheckConstraint("status IN ('pending','complete','partial','truncated','policy_skipped','not_received','write_failed','write_unknown')", name="ck_evaluation_performance_response_artifact_status"),
    CheckConstraint("hash_scope IN ('none','full','prefix')", name="ck_evaluation_performance_response_artifact_hash_scope"),
    CheckConstraint(
        "((hash_scope = 'none' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NULL) OR "
        "(hash_scope = 'full' AND response_sha256 IS NOT NULL AND length(response_sha256) = 64 AND captured_prefix_sha256 IS NULL) OR "
        "(hash_scope = 'prefix' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NOT NULL AND length(captured_prefix_sha256) = 64))",
        name="ck_evaluation_performance_response_artifact_hash",
    ),
    CheckConstraint("captured_bytes BETWEEN 0 AND 1048576 AND observed_bytes BETWEEN 0 AND 10000001 AND observed_bytes >= captured_bytes", name="ck_evaluation_performance_response_artifact_bytes"),
    CheckConstraint(
        "((sealed_sha256 IS NULL AND sealed_bytes IS NULL AND key_version IS NULL AND receipt_hash IS NULL) OR "
        "(sealed_sha256 IS NOT NULL AND length(sealed_sha256) = 64 AND sealed_bytes BETWEEN captured_bytes + 28 AND captured_bytes + 2113 "
        "AND key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 16 AND receipt_hash IS NOT NULL AND length(receipt_hash) = 64))",
        name="ck_evaluation_performance_response_artifact_receipt",
    ),
    CheckConstraint(
        "((status = 'pending' AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
        "(status = 'complete' AND hash_scope = 'full' AND sealed_sha256 IS NOT NULL AND captured_bytes = observed_bytes) OR "
        "(status IN ('partial','truncated') AND hash_scope = 'prefix' AND sealed_sha256 IS NOT NULL) OR "
        "(status IN ('policy_skipped','not_received','write_failed') AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR status = 'write_unknown')",
        name="ck_evaluation_performance_response_artifact_state",
    ),
    CheckConstraint("content_type IS NULL OR length(content_type) BETWEEN 1 AND 127", name="ck_evaluation_performance_response_artifact_content_type"),
    CheckConstraint("content_encoding IS NULL OR content_encoding IN ('identity','gzip','deflate','br','zstd','compress','other')", name="ck_evaluation_performance_response_artifact_content_encoding"),
    CheckConstraint("created_at_ms > 0 AND updated_at_ms >= created_at_ms AND updated_at_ms <= 253402300799000", name="ck_evaluation_performance_response_artifact_clock"),
)
Index("ix_evaluation_performance_response_artifact_status_time", performance_response_artifacts.c.status, performance_response_artifacts.c.updated_at_ms)

performance_run_audit = Table(
    "evaluation_performance_run_audit",
    metadata,
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("actor", String(64), nullable=False),
    Column("action", String(40), nullable=False),
    Column("details", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
    CheckConstraint("sequence >= 1", name="ck_evaluation_performance_run_audit_sequence"),
    CheckConstraint(
        "action IN ('run_created','dispatch_claimed','dispatch_acknowledged','dispatch_started','measurement_window_closed','observation_recorded','run_interrupted','run_finished','response_access_granted','response_access_read')",
        name="ck_evaluation_performance_run_audit_action",
    ),
)

performance_evidence_access_grants = Table(
    "evaluation_performance_evidence_access_grants",
    metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("project_id", String(64), nullable=False),
    Column("run_id", String(64), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("dispatch_id", String(64), nullable=False),
    Column("artifact_id", String(32), nullable=False),
    Column("actor_id", String(64), nullable=False),
    Column("evidence_hash", String(64), nullable=False),
    Column("created_at_ms", BigInteger, nullable=False),
    Column("expires_at_ms", BigInteger, nullable=False),
    Column("consumed_at_ms", BigInteger),
    Column("revoked_at_ms", BigInteger),
    ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
    ForeignKeyConstraint(
        ["project_id", "run_id", "ordinal", "dispatch_id"],
        ["evaluation_performance_dispatches.project_id", "evaluation_performance_dispatches.run_id", "evaluation_performance_dispatches.ordinal", "evaluation_performance_dispatches.dispatch_id"],
    ),
    ForeignKeyConstraint(["artifact_id"], ["evaluation_performance_response_artifacts.id"]),
    CheckConstraint("length(token_hash) = 64 AND token_hash = lower(token_hash)", name="ck_evaluation_performance_evidence_grant_token_hash"),
    CheckConstraint("length(evidence_hash) = 64 AND evidence_hash = lower(evidence_hash)", name="ck_evaluation_performance_evidence_grant_hash"),
    CheckConstraint("ordinal BETWEEN 0 AND 10999 AND length(actor_id) BETWEEN 1 AND 64", name="ck_evaluation_performance_evidence_grant_subject"),
    CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms - created_at_ms <= 300000", name="ck_evaluation_performance_evidence_grant_expiry"),
    CheckConstraint("consumed_at_ms IS NULL OR consumed_at_ms >= created_at_ms", name="ck_evaluation_performance_evidence_grant_consumed"),
    CheckConstraint("revoked_at_ms IS NULL OR revoked_at_ms >= created_at_ms", name="ck_evaluation_performance_evidence_grant_revoked"),
)
