"""Distinguish synthetic ledger validation from target performance runs."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0030"
down_revision = "eval_0029"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_performance_runs") as batch:
        batch.add_column(sa.Column("execution_mode", sa.String(24), nullable=False, server_default="target"))
        batch.create_check_constraint(
            "ck_evaluation_performance_run_execution_mode",
            "execution_mode IN ('target','synthetic_only')",
        )
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','run_admitted','dispatch_claimed','dispatch_acknowledged',"
            "'dispatch_started','measurement_window_closed','observation_recorded','run_interrupted',"
            "'run_finished','response_access_granted','response_access_read','synthetic_mode_selected')",
        )


def downgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','run_admitted','dispatch_claimed','dispatch_acknowledged',"
            "'dispatch_started','measurement_window_closed','observation_recorded','run_interrupted',"
            "'run_finished','response_access_granted','response_access_read')",
        )
    with op.batch_alter_table("evaluation_performance_runs") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_execution_mode", type_="check")
        batch.drop_column("execution_mode")
