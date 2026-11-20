"""Index owner-scoped run pages by project and stable descending time."""

from alembic import op

revision = "eval_0020"
down_revision = "eval_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_evaluation_dispatch_run_project_started_id",
        "evaluation_dispatch_runs",
        ["project_id", "started_at_ms", "id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_evaluation_dispatch_run_project_started_id", table_name="evaluation_dispatch_runs")
