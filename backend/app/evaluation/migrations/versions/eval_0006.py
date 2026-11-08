"""Append-only encrypted QA output and human reviews, separate from Harness."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0006"
down_revision = "eval_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_output_evidence",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("ordinal", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("encrypted_payload", sa.Text, nullable=False),
        sa.Column("protected_hash", sa.String(64), nullable=False),
        sa.Column("observation_hash", sa.String(64), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10000 AND created_at_ms > 0", name="ck_evaluation_output_bounds"),
    )
    op.create_table(
        "evaluation_case_reviews",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("ordinal", sa.Integer, primary_key=True),
        sa.Column("revision", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("case_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reviewer_id", sa.String(64), nullable=False),
        sa.Column("encrypted_payload", sa.Text, nullable=False),
        sa.Column("protected_hash", sa.String(64), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10000 AND revision BETWEEN 1 AND 100 AND created_at_ms > 0", name="ck_evaluation_review_bounds"),
        sa.CheckConstraint("decision IN ('pass','fail','uncertain')", name="ck_evaluation_review_decision"),
    )


def downgrade():
    op.drop_table("evaluation_case_reviews")
    op.drop_table("evaluation_output_evidence")
