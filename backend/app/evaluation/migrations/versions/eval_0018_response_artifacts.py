"""Add response artifact manifests for bounded encrypted QA evidence."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "eval_0018"
down_revision = "eval_0017"
branch_labels = None
depends_on = None


def _request_body_sha256_constraint():
    cleaned = "request_body_sha256"
    for character in "0123456789abcdef":
        cleaned = f"replace({cleaned}, '{character}', '')"
    return f"request_body_sha256 IS NOT NULL AND length(request_body_sha256) = 64 AND request_body_sha256 = lower(request_body_sha256) AND length({cleaned}) = 0"


def upgrade():
    op.create_table(
        "evaluation_response_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("hash_scope", sa.String(8), nullable=False),
        sa.Column("request_body_sha256", sa.String(64), nullable=True),
        sa.Column("request_body_bytes", sa.Integer, nullable=True),
        sa.Column("request_contract_version", sa.String(32), nullable=True),
        sa.Column("response_sha256", sa.String(64), nullable=True),
        sa.Column("captured_prefix_sha256", sa.String(64), nullable=True),
        sa.Column("captured_bytes", sa.Integer, nullable=False),
        sa.Column("observed_bytes", sa.Integer, nullable=False),
        sa.Column("content_type", sa.String(127), nullable=True),
        sa.Column("content_encoding", sa.String(16), nullable=True),
        sa.Column("key_version", sa.String(16), nullable=True),
        sa.Column("sealed_sha256", sa.String(64), nullable=True),
        sa.Column("sealed_bytes", sa.Integer, nullable=True),
        sa.Column("receipt_hash", sa.String(64), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("updated_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["evaluation_projects.id"], name="fk_evaluation_response_artifact_project"),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"], name="fk_evaluation_response_artifact_run"),
        sa.ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"], name="fk_evaluation_response_artifact_dispatch"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_evaluation_response_artifact_dispatch"),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10000", name="ck_evaluation_response_artifact_ordinal"),
        sa.CheckConstraint(
            "status IN ('pending','complete','partial','truncated','policy_skipped','not_received','write_failed','write_unknown','unavailable_legacy')",
            name="ck_evaluation_response_artifact_status",
        ),
        sa.CheckConstraint("hash_scope IN ('none','full','prefix')", name="ck_evaluation_response_artifact_hash_scope"),
        sa.CheckConstraint(
            "((request_body_sha256 IS NULL AND request_body_bytes IS NULL AND request_contract_version IS NULL) OR "
            f"({_request_body_sha256_constraint()} AND request_body_bytes BETWEEN 0 AND 262144 AND request_contract_version IS NOT NULL AND length(request_contract_version) BETWEEN 1 AND 32))",
            name="ck_evaluation_response_artifact_request_identity",
        ),
        sa.CheckConstraint(
            "((hash_scope = 'none' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NULL) OR "
            "(hash_scope = 'full' AND response_sha256 IS NOT NULL AND length(response_sha256) = 64 AND captured_prefix_sha256 IS NULL) OR "
            "(hash_scope = 'prefix' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NOT NULL AND length(captured_prefix_sha256) = 64))",
            name="ck_evaluation_response_artifact_hash",
        ),
        sa.CheckConstraint(
            "((sealed_sha256 IS NULL AND sealed_bytes IS NULL AND key_version IS NULL AND receipt_hash IS NULL) OR "
            "(sealed_sha256 IS NOT NULL AND length(sealed_sha256) = 64 "
            "AND sealed_bytes BETWEEN captured_bytes + 28 AND captured_bytes + 2113 "
            "AND key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 16 "
            "AND receipt_hash IS NOT NULL AND length(receipt_hash) = 64))",
            name="ck_evaluation_response_artifact_sealed_receipt",
        ),
        sa.CheckConstraint(
            "captured_bytes BETWEEN 0 AND 1048576 AND observed_bytes BETWEEN 0 AND 1048577 AND observed_bytes >= captured_bytes",
            name="ck_evaluation_response_artifact_bytes",
        ),
        sa.CheckConstraint("content_type IS NULL OR length(content_type) BETWEEN 1 AND 127", name="ck_evaluation_response_artifact_content_type"),
        sa.CheckConstraint("content_encoding IS NULL OR content_encoding IN ('identity','gzip','deflate','br','zstd','compress','other')", name="ck_evaluation_response_artifact_content_encoding"),
        sa.CheckConstraint(
            "((status = 'pending' AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
            "(status = 'complete' AND hash_scope = 'full' AND sealed_sha256 IS NOT NULL AND captured_bytes = observed_bytes) OR "
            "(status IN ('partial','truncated') AND hash_scope = 'prefix' AND sealed_sha256 IS NOT NULL) OR "
            "(status IN ('policy_skipped','not_received','unavailable_legacy') AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
            "status IN ('write_failed','write_unknown'))",
            name="ck_evaluation_response_artifact_state",
        ),
        sa.CheckConstraint(
            "status NOT IN ('complete','partial','truncated','not_received') OR (request_body_sha256 IS NOT NULL AND request_body_bytes IS NOT NULL AND request_contract_version IS NOT NULL)",
            name="ck_evaluation_response_artifact_request_recorded",
        ),
        sa.CheckConstraint(
            "status != 'write_failed' OR request_body_sha256 IS NOT NULL OR (request_body_bytes IS NULL AND request_contract_version IS NULL AND hash_scope = 'none' AND captured_bytes = 0 AND observed_bytes = 0)",
            name="ck_evaluation_response_artifact_write_failed_identity",
        ),
        sa.CheckConstraint("created_at_ms > 0 AND updated_at_ms >= created_at_ms AND updated_at_ms <= 253402300799000", name="ck_evaluation_response_artifact_clock"),
    )
    connection = op.get_bind()
    legacy_rows = connection.execute(
        sa.text("SELECT d.project_id, d.run_id, d.ordinal, r.started_at_ms FROM evaluation_dispatches AS d JOIN evaluation_dispatch_runs AS r ON r.project_id = d.project_id AND r.id = d.run_id ORDER BY d.run_id, d.ordinal")
    ).mappings()
    insert_artifact = sa.text(
        "INSERT INTO evaluation_response_artifacts "
        "(id, project_id, run_id, ordinal, status, hash_scope, captured_bytes, observed_bytes, created_at_ms, updated_at_ms) "
        "VALUES (:id, :project_id, :run_id, :ordinal, 'unavailable_legacy', 'none', 0, 0, :at_ms, :at_ms)"
    )
    while batch := legacy_rows.fetchmany(500):
        connection.execute(
            insert_artifact,
            [
                {
                    "id": uuid4().hex,
                    "project_id": row["project_id"],
                    "run_id": row["run_id"],
                    "ordinal": row["ordinal"],
                    "at_ms": row["started_at_ms"],
                }
                for row in batch
            ],
        )
    op.create_index("ix_evaluation_response_artifact_status_time", "evaluation_response_artifacts", ["status", "updated_at_ms"])


def downgrade():
    op.drop_index("ix_evaluation_response_artifact_status_time", table_name="evaluation_response_artifacts")
    op.drop_table("evaluation_response_artifacts")
