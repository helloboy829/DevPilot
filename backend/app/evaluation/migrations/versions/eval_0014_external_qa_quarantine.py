"""Immutable external technical metadata quarantine; never platform evidence."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0014"
down_revision = "eval_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_external_qa_intakes",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("export_id", sa.String(32), nullable=False),
        sa.Column("original_run_id", sa.String(36), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("archive_hash", sa.String(64), nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column("canonical_receipt", sa.Text, nullable=False),
        sa.Column("canonical_reconciliation", sa.Text, nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "export_id"], ["evaluation_authorized_exports.project_id", "evaluation_authorized_exports.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_external_intake_project_id"),
        sa.UniqueConstraint("export_id", "original_run_id", "snapshot_hash", name="uq_evaluation_external_intake_snapshot"),
        sa.CheckConstraint("created_at_ms > 0 AND created_at_ms <= 253402300799000", name="ck_evaluation_external_intake_time"),
        sa.CheckConstraint("length(canonical_receipt) BETWEEN 1 AND 8192 AND length(canonical_reconciliation) BETWEEN 1 AND 8192", name="ck_evaluation_external_intake_size"),
    )
    op.create_index("ix_evaluation_external_intake_project_time", "evaluation_external_qa_intakes", ["project_id", "created_at_ms"])
    op.create_table(
        "evaluation_external_qa_intake_audit",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("intake_id", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "intake_id"], ["evaluation_external_qa_intakes.project_id", "evaluation_external_qa_intakes.id"]),
        sa.UniqueConstraint("intake_id", "sequence", name="uq_evaluation_external_intake_audit_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_evaluation_external_intake_audit_sequence"),
        sa.CheckConstraint("action = 'metadata_quarantined' AND at_ms > 0", name="ck_evaluation_external_intake_audit"),
    )
    op.create_index("ix_evaluation_external_intake_audit_intake", "evaluation_external_qa_intake_audit", ["project_id", "intake_id"])


def downgrade():
    op.drop_index("ix_evaluation_external_intake_audit_intake", table_name="evaluation_external_qa_intake_audit")
    op.drop_table("evaluation_external_qa_intake_audit")
    op.drop_index("ix_evaluation_external_intake_project_time", table_name="evaluation_external_qa_intakes")
    op.drop_table("evaluation_external_qa_intakes")
