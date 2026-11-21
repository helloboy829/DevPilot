"""Create immutable frozen performance scenario definitions."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0024"
down_revision = "eval_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_performance_scenarios",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("definition", sa.JSON, nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_performance_scenario_project_id"),
        sa.CheckConstraint("version = 1", name="ck_evaluation_performance_scenario_version"),
        sa.CheckConstraint("length(definition_hash) = 64 AND definition_hash = lower(definition_hash)", name="ck_evaluation_performance_scenario_hash"),
    )
    op.create_index("ix_evaluation_performance_scenario_component", "evaluation_performance_scenarios", ["project_id", "component_id", "created_at", "id"])
    op.create_table(
        "evaluation_performance_scenario_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "scenario_id"], ["evaluation_performance_scenarios.project_id", "evaluation_performance_scenarios.id"]),
        sa.CheckConstraint("action = 'scenario_frozen'", name="ck_evaluation_performance_scenario_audit_action"),
    )


def downgrade():
    op.drop_table("evaluation_performance_scenario_audit")
    op.drop_index("ix_evaluation_performance_scenario_component", table_name="evaluation_performance_scenarios")
    op.drop_table("evaluation_performance_scenarios")
