"""Independent execution admission and conservative global reservations."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0007"
down_revision = "eval_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_execution_guard",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("policy_hash", sa.String(64), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_evaluation_execution_guard"),
    )
    op.create_table(
        "evaluation_executions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False, unique=True),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("reservation_held", sa.Boolean, nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=True),
        sa.Column("reserved_concurrency", sa.Integer, nullable=False),
        sa.Column("reserved_body_bytes", sa.BigInteger, nullable=False),
        sa.Column("reserved_response_bytes", sa.BigInteger, nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("deadline_ms", sa.BigInteger, nullable=False),
        sa.Column("finished_at_ms", sa.BigInteger, nullable=True),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.CheckConstraint("scope = 'admitted_qa_json'", name="ck_evaluation_execution_scope"),
        sa.CheckConstraint("state IN ('queued','running','cancel_requested','collected','interrupted')", name="ck_evaluation_execution_state"),
        sa.CheckConstraint("reserved_concurrency BETWEEN 1 AND 64 AND reserved_body_bytes BETWEEN 1 AND 67108864 AND reserved_response_bytes BETWEEN 2 AND 67108864", name="ck_evaluation_execution_reserved"),
        sa.CheckConstraint("created_at_ms > 0 AND deadline_ms > created_at_ms", name="ck_evaluation_execution_clock"),
    )
    op.create_index("ix_evaluation_execution_queue", "evaluation_executions", ["reservation_held", "state", "created_at_ms"])


def downgrade():
    op.drop_index("ix_evaluation_execution_queue", table_name="evaluation_executions")
    op.drop_table("evaluation_executions")
    op.drop_table("evaluation_execution_guard")
