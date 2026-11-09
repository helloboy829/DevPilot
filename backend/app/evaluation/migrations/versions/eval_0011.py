"""Append-only independent assessments; preserve deployed tables and Harness ledger."""

from alembic import op
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, ForeignKeyConstraint, Integer, String, UniqueConstraint

revision = "eval_0011"
down_revision = "eval_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_run_assessments",
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
    op.create_index("ix_evaluation_assessment_run_revision", "evaluation_run_assessments", ["run_id", "revision"])


def downgrade():
    op.drop_index("ix_evaluation_assessment_run_revision", table_name="evaluation_run_assessments")
    op.drop_table("evaluation_run_assessments")
