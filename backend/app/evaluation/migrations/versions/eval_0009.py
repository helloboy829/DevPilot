"""Append immutable QA retest comparisons without modifying old data or ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0009"
down_revision = "eval_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_retest_archives",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("baseline_run_id", sa.String(64), nullable=False),
        sa.Column("retest_run_id", sa.String(64), nullable=False),
        sa.Column("baseline_label", sa.String(80), nullable=False),
        sa.Column("retest_label", sa.String(80), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("archive_hash", sa.String(64), nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
        sa.ForeignKeyConstraint(["project_id", "baseline_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.ForeignKeyConstraint(["project_id", "retest_run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.UniqueConstraint("project_id", "baseline_run_id", "retest_run_id", name="uq_evaluation_retest_pair"),
        sa.CheckConstraint("baseline_run_id <> retest_run_id AND created_at_ms > 0", name="ck_evaluation_retest_bounds"),
    )
    op.create_index("ix_evaluation_retest_project_time", "evaluation_retest_archives", ["project_id", "created_at_ms"])


def downgrade():
    op.drop_index("ix_evaluation_retest_project_time", table_name="evaluation_retest_archives")
    op.drop_table("evaluation_retest_archives")
