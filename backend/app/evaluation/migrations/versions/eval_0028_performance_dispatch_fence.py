"""Add durable worker lease and send-start fence metadata."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0028"
down_revision = "eval_0027"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_performance_dispatches") as batch:
        batch.add_column(sa.Column("lease_worker_id", sa.String(64)))
        batch.add_column(sa.Column("lease_epoch", sa.Integer, server_default="0", nullable=False))
        batch.add_column(sa.Column("lease_expires_at_ms", sa.BigInteger))
        batch.create_check_constraint("ck_evaluation_performance_dispatch_lease_epoch", "lease_epoch >= 0")
        batch.create_check_constraint(
            "ck_evaluation_performance_dispatch_lease_worker",
            "lease_worker_id IS NULL OR length(lease_worker_id) BETWEEN 1 AND 64",
        )
        batch.create_check_constraint(
            "ck_evaluation_performance_dispatch_lease_expiry",
            "lease_expires_at_ms IS NULL OR lease_expires_at_ms >= 0",
        )
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','dispatch_claimed','dispatch_acknowledged','dispatch_started','measurement_window_closed','observation_recorded','run_interrupted','run_finished','response_access_granted','response_access_read')",
        )


def downgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','dispatch_acknowledged','measurement_window_closed','observation_recorded','run_interrupted','run_finished','response_access_granted','response_access_read')",
        )
    with op.batch_alter_table("evaluation_performance_dispatches") as batch:
        batch.drop_constraint("ck_evaluation_performance_dispatch_lease_expiry", type_="check")
        batch.drop_constraint("ck_evaluation_performance_dispatch_lease_worker", type_="check")
        batch.drop_constraint("ck_evaluation_performance_dispatch_lease_epoch", type_="check")
        batch.drop_column("lease_expires_at_ms")
        batch.drop_column("lease_epoch")
        batch.drop_column("lease_worker_id")
