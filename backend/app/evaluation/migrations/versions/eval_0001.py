"""Initial owner-scoped QA data ledger.

Revision ID: eval_0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "eval_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_projects", sa.Column("id", sa.String(64), primary_key=True), sa.Column("owner_id", sa.String(64), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("created_at", sa.String(40), nullable=False)
    )
    op.create_index("ix_evaluation_projects_owner_id", "evaluation_projects", ["owner_id"])
    op.create_table(
        "evaluation_datasets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("evaluation_projects.id"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("source", sa.JSON, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("sample_count", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("frozen_at", sa.String(40)),
        sa.Column("frozen_by", sa.String(64)),
        sa.CheckConstraint("status IN ('draft', 'frozen')", name="ck_evaluation_dataset_status"),
        sa.CheckConstraint("purpose IN ('baseline', 'acceptance')", name="ck_evaluation_dataset_purpose"),
    )
    op.create_index("ix_evaluation_datasets_project_id", "evaluation_datasets", ["project_id"])
    op.create_table(
        "evaluation_samples",
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("evaluation_datasets.id"), primary_key=True),
        sa.Column("sample_id", sa.String(80), primary_key=True),
        sa.Column("input", sa.Text, nullable=False),
        sa.Column("source_ref", sa.String(500), nullable=False),
        sa.Column("slice_tag", sa.String(80), nullable=False),
    )
    op.create_table(
        "evaluation_references",
        sa.Column("dataset_id", sa.String(64), primary_key=True),
        sa.Column("sample_id", sa.String(80), primary_key=True),
        sa.Column("expected", sa.Text, nullable=False),
        sa.ForeignKeyConstraint(["dataset_id", "sample_id"], ["evaluation_samples.dataset_id", "evaluation_samples.sample_id"]),
    )
    op.create_table(
        "evaluation_data_audit",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("evaluation_projects.id"), nullable=False),
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("evaluation_datasets.id"), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
    )
    op.create_index("ix_evaluation_data_audit_dataset_id", "evaluation_data_audit", ["dataset_id"])


def downgrade():
    for table in ("evaluation_data_audit", "evaluation_references", "evaluation_samples", "evaluation_datasets", "evaluation_projects"):
        op.drop_table(table)
