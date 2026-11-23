"""Add performance-specific response artifact receipts."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0026"
down_revision = "eval_0025"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_performance_dispatches") as batch:
        batch.drop_constraint("ck_evaluation_performance_dispatch_response_bytes", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_dispatch_response_bytes",
            "response_bytes IS NULL OR response_bytes BETWEEN 0 AND 10000001",
        )
        batch.create_unique_constraint(
            "uq_evaluation_performance_dispatch_binding",
            ["project_id", "run_id", "ordinal", "dispatch_id"],
        )
    op.create_table(
        "evaluation_performance_response_artifacts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("dispatch_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("hash_scope", sa.String(8), nullable=False),
        sa.Column("response_sha256", sa.String(64)),
        sa.Column("captured_prefix_sha256", sa.String(64)),
        sa.Column("captured_bytes", sa.Integer, nullable=False),
        sa.Column("observed_bytes", sa.Integer, nullable=False),
        sa.Column("content_type", sa.String(127)),
        sa.Column("content_encoding", sa.String(16)),
        sa.Column("key_version", sa.String(16)),
        sa.Column("sealed_sha256", sa.String(64)),
        sa.Column("sealed_bytes", sa.Integer),
        sa.Column("receipt_hash", sa.String(64)),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("updated_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "run_id", "ordinal", "dispatch_id"],
            ["evaluation_performance_dispatches.project_id", "evaluation_performance_dispatches.run_id", "evaluation_performance_dispatches.ordinal", "evaluation_performance_dispatches.dispatch_id"],
            name="fk_evaluation_performance_response_artifact_dispatch",
        ),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_evaluation_performance_response_artifact_dispatch"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 10999", name="ck_evaluation_performance_response_artifact_ordinal"),
        sa.CheckConstraint("status IN ('pending','complete','partial','truncated','policy_skipped','not_received','write_failed','write_unknown')", name="ck_evaluation_performance_response_artifact_status"),
        sa.CheckConstraint("hash_scope IN ('none','full','prefix')", name="ck_evaluation_performance_response_artifact_hash_scope"),
        sa.CheckConstraint(
            "((hash_scope = 'none' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NULL) OR "
            "(hash_scope = 'full' AND response_sha256 IS NOT NULL AND length(response_sha256) = 64 AND captured_prefix_sha256 IS NULL) OR "
            "(hash_scope = 'prefix' AND response_sha256 IS NULL AND captured_prefix_sha256 IS NOT NULL AND length(captured_prefix_sha256) = 64))",
            name="ck_evaluation_performance_response_artifact_hash",
        ),
        sa.CheckConstraint("captured_bytes BETWEEN 0 AND 1048576 AND observed_bytes BETWEEN 0 AND 10000001 AND observed_bytes >= captured_bytes", name="ck_evaluation_performance_response_artifact_bytes"),
        sa.CheckConstraint(
            "((sealed_sha256 IS NULL AND sealed_bytes IS NULL AND key_version IS NULL AND receipt_hash IS NULL) OR "
            "(sealed_sha256 IS NOT NULL AND length(sealed_sha256) = 64 AND sealed_bytes BETWEEN captured_bytes + 28 AND captured_bytes + 2113 "
            "AND key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 16 AND receipt_hash IS NOT NULL AND length(receipt_hash) = 64))",
            name="ck_evaluation_performance_response_artifact_receipt",
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR "
            "(status = 'complete' AND hash_scope = 'full' AND sealed_sha256 IS NOT NULL AND captured_bytes = observed_bytes) OR "
            "(status IN ('partial','truncated') AND hash_scope = 'prefix' AND sealed_sha256 IS NOT NULL) OR "
            "(status IN ('policy_skipped','not_received','write_failed') AND hash_scope = 'none' AND sealed_sha256 IS NULL) OR status = 'write_unknown')",
            name="ck_evaluation_performance_response_artifact_state",
        ),
        sa.CheckConstraint("content_type IS NULL OR length(content_type) BETWEEN 1 AND 127", name="ck_evaluation_performance_response_artifact_content_type"),
        sa.CheckConstraint("content_encoding IS NULL OR content_encoding IN ('identity','gzip','deflate','br','zstd','compress','other')", name="ck_evaluation_performance_response_artifact_content_encoding"),
        sa.CheckConstraint("created_at_ms > 0 AND updated_at_ms >= created_at_ms AND updated_at_ms <= 253402300799000", name="ck_evaluation_performance_response_artifact_clock"),
    )
    op.create_index(
        "ix_evaluation_performance_response_artifact_status_time",
        "evaluation_performance_response_artifacts",
        ["status", "updated_at_ms"],
    )


def downgrade():
    op.drop_index("ix_evaluation_performance_response_artifact_status_time", table_name="evaluation_performance_response_artifacts")
    op.drop_table("evaluation_performance_response_artifacts")
    with op.batch_alter_table("evaluation_performance_dispatches") as batch:
        batch.drop_constraint("uq_evaluation_performance_dispatch_binding", type_="unique")
        batch.drop_constraint("ck_evaluation_performance_dispatch_response_bytes", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_dispatch_response_bytes",
            "response_bytes IS NULL OR response_bytes BETWEEN 0 AND 1048576",
        )
