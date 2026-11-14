"""Append-only formal approvals; additive over eval_0014 and the Harness ledger."""

from alembic import op
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, ForeignKeyConstraint, Integer, String, UniqueConstraint

revision = "eval_0015"
down_revision = "eval_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_run_approvals",
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
    op.create_index("ix_evaluation_approval_run_revision", "evaluation_run_approvals", ["run_id", "revision"])
    op.create_table(
        "evaluation_approval_audit",
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
    op.create_index("ix_evaluation_approval_audit_run", "evaluation_approval_audit", ["run_id", "sequence"])


def downgrade():
    op.drop_index("ix_evaluation_approval_audit_run", table_name="evaluation_approval_audit")
    op.drop_table("evaluation_approval_audit")
    op.drop_index("ix_evaluation_approval_run_revision", table_name="evaluation_run_approvals")
    op.drop_table("evaluation_run_approvals")
