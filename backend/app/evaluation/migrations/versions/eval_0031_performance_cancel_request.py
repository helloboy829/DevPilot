"""Persist owner-requested performance run cancellation."""

from alembic import op

revision = "eval_0031"
down_revision = "eval_0030"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_performance_runs") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_status", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_status",
            "status IN ('created','running','cancel_requested','completed','interrupted','failed')",
        )
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','run_admitted','dispatch_claimed','dispatch_acknowledged',"
            "'dispatch_started','measurement_window_closed','observation_recorded','run_interrupted',"
            "'run_finished','response_access_granted','response_access_read','synthetic_mode_selected',"
            "'run_cancel_requested')",
        )


def downgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','run_admitted','dispatch_claimed','dispatch_acknowledged',"
            "'dispatch_started','measurement_window_closed','observation_recorded','run_interrupted',"
            "'run_finished','response_access_granted','response_access_read','synthetic_mode_selected')",
        )
    with op.batch_alter_table("evaluation_performance_runs") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_status", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_status",
            "status IN ('created','running','completed','interrupted','failed')",
        )
