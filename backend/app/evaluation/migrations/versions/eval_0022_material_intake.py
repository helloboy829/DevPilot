"""Persist owner-scoped material intake manifests and artifact receipts."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0022"
down_revision = "eval_0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_material_batches",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), server_default="open", nullable=False),
        sa.Column("component_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.Column("archived_at", sa.String(40)),
        sa.CheckConstraint("status IN ('open','archived')", name="ck_evaluation_material_batch_status"),
        sa.CheckConstraint("component_count BETWEEN 1 AND 10000", name="ck_evaluation_material_batch_component_count"),
        sa.CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_material_batch_owner"),
    )
    op.create_index(
        "ix_evaluation_material_batch_owner_created",
        "evaluation_material_batches",
        ["owner_id", "created_at", "id"],
    )
    op.create_table(
        "evaluation_material_components",
        sa.Column("batch_id", sa.String(32), sa.ForeignKey("evaluation_material_batches.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("component_id", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.CheckConstraint("kind IN ('llm','cv','agent','model')", name="ck_evaluation_material_component_kind"),
        sa.CheckConstraint("status IN ('pending','parsed','blocked','excluded','candidate','archived')", name="ck_evaluation_material_component_status"),
    )
    op.create_table(
        "evaluation_material_artifacts",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("batch_id", sa.String(32), sa.ForeignKey("evaluation_material_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("authorization_basis", sa.String(32), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("sensitivity", sa.String(16), nullable=False),
        sa.Column("retention_until", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending_upload", nullable=False),
        sa.Column("storage_key", sa.String(128)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("uploaded_at", sa.String(40)),
        sa.UniqueConstraint("batch_id", "id", name="uq_evaluation_material_artifact_batch_id"),
        sa.CheckConstraint("authorization_basis IN ('user_provided','public_domain','license','contract','explicit_consent')", name="ck_evaluation_material_artifact_authorization"),
        sa.CheckConstraint("sensitivity IN ('public','internal','confidential','restricted')", name="ck_evaluation_material_artifact_sensitivity"),
        sa.CheckConstraint("status IN ('pending_upload','uploaded','write_failed','write_unknown')", name="ck_evaluation_material_artifact_status"),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes BETWEEN 0 AND 104857600", name="ck_evaluation_material_artifact_size"),
        sa.CheckConstraint("sha256 IS NULL OR (length(sha256) = 64 AND sha256 = lower(sha256))", name="ck_evaluation_material_artifact_sha256"),
    )
    op.create_table(
        "evaluation_material_artifact_components",
        sa.Column("batch_id", sa.String(32), primary_key=True),
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column("component_id", sa.String(80), primary_key=True),
        sa.ForeignKeyConstraint(
            ["batch_id", "artifact_id"],
            ["evaluation_material_artifacts.batch_id", "evaluation_material_artifacts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id", "component_id"],
            ["evaluation_material_components.batch_id", "evaluation_material_components.component_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade():
    op.drop_table("evaluation_material_artifact_components")
    op.drop_table("evaluation_material_artifacts")
    op.drop_table("evaluation_material_components")
    op.drop_index("ix_evaluation_material_batch_owner_created", table_name="evaluation_material_batches")
    op.drop_table("evaluation_material_batches")
