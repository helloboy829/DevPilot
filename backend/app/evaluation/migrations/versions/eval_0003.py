"""Add append-only encrypted request definitions, independent of Harness.

Revision ID: eval_0003
Revises: eval_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "eval_0003"
down_revision = "eval_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_request_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("component_id", sa.String(64), nullable=False),
        sa.Column("version_label", sa.String(80), nullable=False),
        sa.Column("label_key", sa.String(240), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("request_template", sa.JSON(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("protected_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "component_id"], ["evaluation_project_components.project_id", "evaluation_project_components.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_request_project_id"),
        sa.UniqueConstraint("component_id", "label_key", name="uq_evaluation_request_label"),
        sa.CheckConstraint("scope = 'request_definition_only'", name="ck_evaluation_request_scope"),
    )
    op.create_table(
        "evaluation_request_version_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("request_version_id", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "request_version_id"], ["evaluation_request_versions.project_id", "evaluation_request_versions.id"]),
    )


def downgrade():
    op.drop_table("evaluation_request_version_audit")
    op.drop_table("evaluation_request_versions")
