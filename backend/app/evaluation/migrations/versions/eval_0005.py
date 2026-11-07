"""Add technical dispatch journals without changing deployed revisions.

Revision ID: eval_0005
Revises: eval_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "eval_0005"
down_revision = "eval_0004"
branch_labels = None
depends_on = None


def upgrade():

    # Technical dispatch metadata only: not admission, output evidence or quality verdicts.
    op.create_table(
        "evaluation_dispatch_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_count", sa.Integer, nullable=False),
        sa.Column("concurrency", sa.Integer, nullable=False),
        sa.Column("timeout_ms", sa.Integer, nullable=False),
        sa.Column("max_total_body_bytes", sa.Integer, nullable=False),
        sa.Column("max_response_bytes", sa.Integer, nullable=False),
        sa.Column("max_total_response_bytes", sa.Integer, nullable=False),
        sa.Column("lease_grace_ms", sa.Integer, nullable=False),
        sa.Column("started_at_ms", sa.BigInteger, nullable=False),
        sa.Column("deadline_ms", sa.BigInteger, nullable=False),
        sa.Column("reserved_body_bytes", sa.Integer, nullable=False),
        sa.Column("reserved_response_bytes", sa.Integer, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("finished_at_ms", sa.BigInteger, nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_dispatch_project_id"),
        sa.CheckConstraint("scope = 'dispatch_journal_only'", name="ck_evaluation_dispatch_scope"),
        sa.CheckConstraint("status IN ('recording', 'recording_finished', 'interrupted')", name="ck_evaluation_dispatch_status"),
        sa.CheckConstraint("request_count BETWEEN 1 AND 10000 AND concurrency BETWEEN 1 AND 64 AND timeout_ms BETWEEN 100 AND 300000", name="ck_evaluation_dispatch_limits"),
        sa.CheckConstraint(
            "max_total_body_bytes BETWEEN 1 AND 67108864 AND max_response_bytes BETWEEN 1 AND 1048576 AND max_total_response_bytes BETWEEN 2 AND 67108864 AND "
            "max_total_response_bytes >= max_response_bytes + 1 AND lease_grace_ms BETWEEN 100 AND 30000",
            name="ck_evaluation_dispatch_budgets",
        ),
        sa.CheckConstraint("reserved_body_bytes BETWEEN 0 AND max_total_body_bytes AND reserved_response_bytes BETWEEN 0 AND max_total_response_bytes", name="ck_evaluation_dispatch_reserved"),
        sa.CheckConstraint("revision >= 1 AND started_at_ms > 0 AND deadline_ms > started_at_ms", name="ck_evaluation_dispatch_clock"),
    )
    op.create_table(
        "evaluation_dispatches",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("ordinal", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("sample_id", sa.String(80), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("ticket_hash", sa.String(64), nullable=True),
        sa.Column("dispatched_at_ms", sa.BigInteger, nullable=True),
        sa.Column("lease_expires_at_ms", sa.BigInteger, nullable=True),
        sa.Column("kind", sa.String(32), nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("body_bytes", sa.Integer, nullable=True),
        sa.Column("elapsed_ms", sa.Float, nullable=True),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10000", name="ck_evaluation_dispatch_ordinal"),
        sa.CheckConstraint("state IN ('pending','dispatched','observed','delivery_unknown','not_dispatched')", name="ck_evaluation_dispatch_state"),
    )
    op.create_index("ix_evaluation_dispatch_state_lease", "evaluation_dispatches", ["run_id", "state", "lease_expires_at_ms"])
    op.create_table(
        "evaluation_dispatch_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=True),
        sa.Column("at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.UniqueConstraint("run_id", "sequence", name="uq_evaluation_dispatch_audit_sequence"),
    )


def downgrade():
    op.drop_table("evaluation_dispatch_audit")
    op.drop_table("evaluation_dispatches")
    op.drop_table("evaluation_dispatch_runs")
