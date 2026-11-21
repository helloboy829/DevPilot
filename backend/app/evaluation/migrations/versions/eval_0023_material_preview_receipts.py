"""Add bounded material parse metadata and content-free preview receipts."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0023"
down_revision = "eval_0022"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("evaluation_material_artifacts") as batch:
        batch.add_column(sa.Column("parse_status", sa.String(16), server_default="pending", nullable=False))
        batch.add_column(sa.Column("parser_version", sa.String(32)))
        batch.add_column(sa.Column("parse_result_hash", sa.String(64)))
        batch.add_column(sa.Column("parse_block_count", sa.Integer))
        batch.add_column(sa.Column("parse_reason", sa.String(500)))
        batch.add_column(sa.Column("parsed_at", sa.String(40)))
        batch.create_check_constraint("ck_evaluation_material_artifact_parse_status", "parse_status IN ('pending','parsed','blocked')")
        batch.create_check_constraint("ck_evaluation_material_artifact_parse_hash", "parse_result_hash IS NULL OR (length(parse_result_hash) = 64 AND parse_result_hash = lower(parse_result_hash))")
        batch.create_check_constraint("ck_evaluation_material_artifact_parse_blocks", "parse_block_count IS NULL OR parse_block_count BETWEEN 0 AND 20000")

    op.create_table(
        "evaluation_material_preview_receipts",
        sa.Column("operation_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("batch_id", sa.String(32), nullable=False),
        sa.Column("artifact_id", sa.String(64), nullable=False),
        sa.Column("parse_status", sa.String(16), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("block_count", sa.Integer, nullable=False),
        sa.Column("reason", sa.String(500)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["batch_id", "artifact_id"], ["evaluation_material_artifacts.batch_id", "evaluation_material_artifacts.id"], ondelete="CASCADE"),
        sa.CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_material_preview_owner"),
        sa.CheckConstraint("parse_status IN ('parsed','blocked')", name="ck_evaluation_material_preview_status"),
        sa.CheckConstraint("length(result_hash) = 64 AND result_hash = lower(result_hash)", name="ck_evaluation_material_preview_hash"),
        sa.CheckConstraint("block_count BETWEEN 0 AND 20000", name="ck_evaluation_material_preview_blocks"),
    )
    op.create_index("ix_evaluation_material_preview_owner_created", "evaluation_material_preview_receipts", ["owner_id", "created_at"])


def downgrade():
    op.drop_index("ix_evaluation_material_preview_owner_created", table_name="evaluation_material_preview_receipts")
    op.drop_table("evaluation_material_preview_receipts")
    with op.batch_alter_table("evaluation_material_artifacts") as batch:
        batch.drop_constraint("ck_evaluation_material_artifact_parse_blocks", type_="check")
        batch.drop_constraint("ck_evaluation_material_artifact_parse_hash", type_="check")
        batch.drop_constraint("ck_evaluation_material_artifact_parse_status", type_="check")
        batch.drop_column("parsed_at")
        batch.drop_column("parse_reason")
        batch.drop_column("parse_block_count")
        batch.drop_column("parse_result_hash")
        batch.drop_column("parser_version")
        batch.drop_column("parse_status")
