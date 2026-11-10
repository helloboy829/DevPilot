"""Recipient-bound immutable configuration export receipts and encrypted bundles."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0013"
down_revision = "eval_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_authorized_exports",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("receipt_hash", sa.String(64), nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.Column("encrypted_bundle", sa.Text, nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_export_project_id"),
        sa.CheckConstraint("created_at_ms > 0", name="ck_evaluation_export_time"),
    )
    op.create_index("ix_evaluation_export_project_time", "evaluation_authorized_exports", ["project_id", "created_at_ms"])
    op.create_table(
        "evaluation_export_audit",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("export_id", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "export_id"], ["evaluation_authorized_exports.project_id", "evaluation_authorized_exports.id"]),
        sa.UniqueConstraint("export_id", "sequence", name="uq_evaluation_export_audit_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_evaluation_export_audit_sequence"),
        sa.CheckConstraint("action IN ('export_created', 'bundle_opened') AND at_ms > 0", name="ck_evaluation_export_audit"),
    )
    op.create_index("ix_evaluation_export_audit_export", "evaluation_export_audit", ["project_id", "export_id"])


def downgrade():
    op.drop_index("ix_evaluation_export_audit_export", table_name="evaluation_export_audit")
    op.drop_table("evaluation_export_audit")
    op.drop_index("ix_evaluation_export_project_time", table_name="evaluation_authorized_exports")
    op.drop_table("evaluation_authorized_exports")
