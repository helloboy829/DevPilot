"""Add actor-bound, one-time performance response evidence access."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0027"
down_revision = "eval_0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_performance_evidence_access_grants",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("dispatch_id", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("expires_at_ms", sa.BigInteger, nullable=False),
        sa.Column("consumed_at_ms", sa.BigInteger),
        sa.Column("revoked_at_ms", sa.BigInteger),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
        sa.ForeignKeyConstraint(
            ["project_id", "run_id", "ordinal", "dispatch_id"],
            ["evaluation_performance_dispatches.project_id", "evaluation_performance_dispatches.run_id", "evaluation_performance_dispatches.ordinal", "evaluation_performance_dispatches.dispatch_id"],
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["evaluation_performance_response_artifacts.id"]),
        sa.CheckConstraint("length(token_hash) = 64 AND token_hash = lower(token_hash)", name="ck_evaluation_performance_evidence_grant_token_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64 AND evidence_hash = lower(evidence_hash)", name="ck_evaluation_performance_evidence_grant_hash"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 10999 AND length(actor_id) BETWEEN 1 AND 64", name="ck_evaluation_performance_evidence_grant_subject"),
        sa.CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms - created_at_ms <= 300000", name="ck_evaluation_performance_evidence_grant_expiry"),
        sa.CheckConstraint("consumed_at_ms IS NULL OR consumed_at_ms >= created_at_ms", name="ck_evaluation_performance_evidence_grant_consumed"),
        sa.CheckConstraint("revoked_at_ms IS NULL OR revoked_at_ms >= created_at_ms", name="ck_evaluation_performance_evidence_grant_revoked"),
    )
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','dispatch_acknowledged','measurement_window_closed','observation_recorded','run_interrupted','run_finished','response_access_granted','response_access_read')",
        )


def downgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','dispatch_acknowledged','measurement_window_closed','observation_recorded','run_interrupted','run_finished')",
        )
    op.drop_table("evaluation_performance_evidence_access_grants")
