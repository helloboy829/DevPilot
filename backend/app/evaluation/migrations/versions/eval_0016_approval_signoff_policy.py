"""Append-only advisory approval sign-off policy; additive over eval_0015."""

from alembic import op
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, ForeignKeyConstraint, Integer, String, UniqueConstraint

revision = "eval_0016"
down_revision = "eval_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_approval_signoff_policies",
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
        UniqueConstraint("project_id", "revision", name="uq_evaluation_signoff_policy_revision"),
    )


def downgrade():
    op.drop_table("evaluation_approval_signoff_policies")
