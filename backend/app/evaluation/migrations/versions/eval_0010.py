"""Add independently assigned human tasks without editing deployed revisions."""

from alembic import op
from sqlalchemy import JSON, BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint

revision = "eval_0010"
down_revision = "eval_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_review_tasks",
        Column("id", String(32), primary_key=True),
        Column("owner_id", String(64), nullable=False),
        Column("project_id", String(64), nullable=False),
        Column("run_id", String(64), nullable=False),
        Column("ordinal", Integer, nullable=False),
        Column("case_hash", String(64), nullable=False),
        Column("subject_hash", String(64), nullable=False),
        Column("definition", JSON, nullable=False),
        Column("round", Integer, nullable=False),
        Column("revision", Integer, nullable=False),
        Column("status", String(16), nullable=False),
        Column("created_at_ms", BigInteger, nullable=False),
        ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
        CheckConstraint("ordinal BETWEEN 1 AND 10000 AND round BETWEEN 1 AND 10 AND revision BETWEEN 1 AND 10000 AND created_at_ms > 0", name="ck_evaluation_task_bounds"),
        CheckConstraint("status IN ('queued','in_review','escalated','resolved','cancelled')", name="ck_evaluation_task_state"),
    )
    op.create_table(
        "evaluation_review_task_assignments",
        Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
        Column("round", Integer, primary_key=True),
        Column("role", String(16), primary_key=True),
        Column("actor_id", String(64), nullable=False),
        Column("status", String(16), nullable=False),
        Column("lease_until_ms", BigInteger, nullable=True),
        Column("viewed_revision", Integer, nullable=True),
        UniqueConstraint("task_id", "round", "actor_id", name="uq_evaluation_task_actor"),
        CheckConstraint("round BETWEEN 1 AND 10 AND role IN ('reviewer_1','reviewer_2','arbitrator')", name="ck_evaluation_assignment_role"),
        CheckConstraint("status IN ('offered','active','submitted','released')", name="ck_evaluation_assignment_status"),
    )
    op.create_table(
        "evaluation_review_task_decisions",
        Column("task_id", String(32), primary_key=True),
        Column("round", Integer, primary_key=True),
        Column("role", String(16), primary_key=True),
        Column("actor_id", String(64), nullable=False),
        Column("decision", String(16), nullable=False),
        Column("encrypted_payload", Text, nullable=False),
        Column("protected_hash", String(64), nullable=False),
        Column("created_at_ms", BigInteger, nullable=False),
        ForeignKeyConstraint(["task_id", "round", "role"], ["evaluation_review_task_assignments.task_id", "evaluation_review_task_assignments.round", "evaluation_review_task_assignments.role"]),
        CheckConstraint("decision IN ('pass','fail','uncertain') AND created_at_ms > 0", name="ck_evaluation_task_decision"),
    )
    op.create_table(
        "evaluation_review_task_resolutions",
        Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
        Column("round", Integer, primary_key=True),
        Column("revision", Integer, primary_key=True),
        Column("document", JSON, nullable=False),
        Column("resolution_hash", String(64), nullable=False),
        CheckConstraint("round BETWEEN 1 AND 10 AND revision BETWEEN 1 AND 2", name="ck_evaluation_resolution_bounds"),
    )
    op.create_table(
        "evaluation_review_task_audit",
        Column("task_id", String(32), ForeignKey("evaluation_review_tasks.id"), primary_key=True),
        Column("sequence", Integer, primary_key=True),
        Column("round", Integer, nullable=False),
        Column("actor", String(64), nullable=False),
        Column("action", String(32), nullable=False),
        Column("subject_hash", String(64), nullable=False),
        Column("at_ms", BigInteger, nullable=False),
        Column("encrypted_reason", Text, nullable=True),
        Column("protected_hash", String(64), nullable=True),
    )
    op.create_index("ix_evaluation_review_task_project", "evaluation_review_tasks", ["project_id", "created_at_ms"])
    op.create_index("ix_evaluation_review_assignment_actor", "evaluation_review_task_assignments", ["actor_id", "task_id"])


def downgrade():
    op.drop_index("ix_evaluation_review_assignment_actor", table_name="evaluation_review_task_assignments")
    op.drop_index("ix_evaluation_review_task_project", table_name="evaluation_review_tasks")
    for table in ("evaluation_review_task_audit", "evaluation_review_task_resolutions", "evaluation_review_task_decisions", "evaluation_review_task_assignments", "evaluation_review_tasks"):
        op.drop_table(table)
