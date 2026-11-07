"""Add immutable QA JSON plan definitions without changing deployed revisions.

Revision ID: eval_0004
Revises: eval_0003
"""

import sqlalchemy as sa
from alembic import op

revision = "eval_0004"
down_revision = "eval_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_evaluation_request_component_id", "evaluation_request_versions", ["project_id", "component_id", "id"], unique=True)
    op.create_table(
        "evaluation_plans",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("request_version_id", sa.String(64), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("version_label", sa.String(80), nullable=False),
        sa.Column("label_key", sa.String(240), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
        sa.ForeignKeyConstraint(["project_id", "component_id", "request_version_id"], ["evaluation_request_versions.project_id", "evaluation_request_versions.component_id", "evaluation_request_versions.id"]),
        sa.ForeignKeyConstraint(["project_id", "dataset_id"], ["evaluation_datasets.project_id", "evaluation_datasets.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_plan_project_id"),
        sa.UniqueConstraint("component_id", "label_key", name="uq_evaluation_plan_label"),
        sa.CheckConstraint("scope = 'frozen_definition_only'", name="ck_evaluation_plan_scope"),
    )
    op.create_table(
        "evaluation_plan_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "plan_id"], ["evaluation_plans.project_id", "evaluation_plans.id"]),
    )


def downgrade():
    op.drop_table("evaluation_plan_audit")
    op.drop_table("evaluation_plans")
    op.drop_index("uq_evaluation_request_component_id", table_name="evaluation_request_versions")
