"""Assigned human approval requests, immutable events and explicit summary views."""

from alembic import op
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint

revision = "eval_0017"
down_revision = "eval_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_approval_requests",
        Column("id", String(32), primary_key=True),
        Column("owner_id", String(64), nullable=False),
        Column("project_id", String(64), nullable=False),
        Column("run_id", String(64), nullable=False),
        Column("assessment_id", String(32), nullable=False),
        Column("assessment_hash", String(64), nullable=False),
        Column("approver_id", String(64), nullable=False),
        Column("created_at_ms", BigInteger, nullable=False),
        Column("expires_at_ms", BigInteger, nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("subject_hash", String(64), nullable=False),
        Column("definition", JSON, nullable=False),
        Column("revision", Integer, nullable=False),
        Column("status", String(16), nullable=False),
        Column("latest_approval_id", String(32), ForeignKey("evaluation_run_approvals.id"), nullable=True),
        ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        ForeignKeyConstraint(["assessment_id"], ["evaluation_run_assessments.id"]),
        CheckConstraint("owner_id <> approver_id", name="ck_evaluation_approval_request_independent"),
        CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms <= 253402300799000", name="ck_evaluation_approval_request_time"),
        CheckConstraint(
            "(status = 'pending' AND revision = 1 AND latest_approval_id IS NULL) OR "
            "(status = 'cancelled' AND revision = 2 AND latest_approval_id IS NULL) OR "
            "(status = 'approved' AND revision = 2 AND latest_approval_id IS NOT NULL) OR "
            "(status = 'revoked' AND revision = 3 AND latest_approval_id IS NOT NULL)",
            name="ck_evaluation_approval_request_state",
        ),
    )
    op.create_index("ix_evaluation_approval_request_inbox", "evaluation_approval_requests", ["approver_id", "created_at_ms"])
    op.create_index("ix_evaluation_approval_request_run", "evaluation_approval_requests", ["run_id"])
    op.create_table(
        "evaluation_approval_request_events",
        Column("request_id", String(32), ForeignKey("evaluation_approval_requests.id"), primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("operation_id", String(32), nullable=False),
        Column("actor", String(64), nullable=False),
        Column("action", String(16), nullable=False),
        Column("at_ms", BigInteger, nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("receipt", JSON, nullable=False),
        Column("previous_hash", String(64), nullable=True),
        Column("event_hash", String(64), nullable=False),
        UniqueConstraint("request_id", "operation_id", name="uq_evaluation_approval_request_operation"),
        CheckConstraint("revision BETWEEN 1 AND 3 AND at_ms > 0", name="ck_evaluation_approval_request_event_bounds"),
        CheckConstraint("action IN ('requested','approved','revoked','cancelled')", name="ck_evaluation_approval_request_event_action"),
    )
    op.create_table(
        "evaluation_approval_request_views",
        Column("id", String(32), primary_key=True),
        Column("request_id", String(32), ForeignKey("evaluation_approval_requests.id"), nullable=False),
        Column("actor", String(64), nullable=False),
        Column("request_revision", Integer, nullable=False),
        Column("request_hash", String(64), nullable=False),
        Column("summary_hash", String(64), nullable=False),
        Column("expires_at_ms", BigInteger, nullable=False),
        Column("document", JSON, nullable=False),
        Column("view_hash", String(64), nullable=False),
        CheckConstraint("request_revision = 1 AND expires_at_ms > 0 AND expires_at_ms <= 253402300799000", name="ck_evaluation_approval_request_view_bounds"),
    )
    op.create_index("ix_evaluation_approval_request_view_request", "evaluation_approval_request_views", ["request_id"])


def downgrade():
    op.drop_table("evaluation_approval_request_views")
    op.drop_table("evaluation_approval_request_events")
    op.drop_table("evaluation_approval_requests")
