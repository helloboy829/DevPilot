"""Add component bindings and immutable submission inventory snapshots.

Revision ID: eval_0002
Revises: eval_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "eval_0002"
down_revision = "eval_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_evaluation_dataset_project_id", "evaluation_datasets", ["project_id", "id"], unique=True)
    op.create_table(
        "evaluation_project_components",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("evaluation_projects.id"), nullable=False),
        sa.Column("source_component_id", sa.String(64), nullable=False),
        sa.Column("name_at_link", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_component_project_id"),
        sa.UniqueConstraint("project_id", "source_component_id", name="uq_evaluation_component_source"),
        sa.CheckConstraint("kind IN ('llm','cv','agent','model')", name="ck_evaluation_component_kind"),
    )
    op.create_table(
        "evaluation_submissions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("version_label", sa.String(80), nullable=False),
        sa.Column("label_key", sa.String(240), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("dataset_revision", sa.Integer, nullable=False),
        sa.Column("dataset_hash", sa.String(64), nullable=False),
        sa.Column("dataset_purpose", sa.String(16), nullable=False),
        sa.Column("component_snapshot", sa.JSON, nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("submission_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
        sa.ForeignKeyConstraint(["project_id", "dataset_id"], ["evaluation_datasets.project_id", "evaluation_datasets.id"]),
        sa.UniqueConstraint("component_id", "label_key", name="uq_evaluation_submission_label"),
        sa.CheckConstraint("scope = 'inventory_only'", name="ck_evaluation_submission_scope"),
    )
    op.create_table(
        "evaluation_registry_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("evaluation_projects.id"), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("submission_id", sa.String(64), nullable=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
    )
    op.create_index("ix_evaluation_registry_audit_project_id", "evaluation_registry_audit", ["project_id"])


def downgrade():
    for name in ("evaluation_registry_audit", "evaluation_submissions", "evaluation_project_components"):
        op.drop_table(name)
    op.drop_index("uq_evaluation_dataset_project_id", table_name="evaluation_datasets")
