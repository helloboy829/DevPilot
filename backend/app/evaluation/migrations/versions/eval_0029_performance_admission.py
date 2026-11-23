"""Allow the durable performance run admission audit event."""

from alembic import op

revision = "eval_0029"
down_revision = "eval_0028"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ("
            "'run_created','run_admitted','dispatch_claimed','dispatch_acknowledged',"
            "'dispatch_started','measurement_window_closed','observation_recorded',"
            "'run_interrupted','run_finished','response_access_granted','response_access_read')",
        )


def downgrade():
    with op.batch_alter_table("evaluation_performance_run_audit") as batch:
        batch.drop_constraint("ck_evaluation_performance_run_audit_action", type_="check")
        batch.create_check_constraint(
            "ck_evaluation_performance_run_audit_action",
            "action IN ('run_created','dispatch_claimed','dispatch_acknowledged','dispatch_started','measurement_window_closed','observation_recorded','run_interrupted','run_finished','response_access_granted','response_access_read')",
        )
