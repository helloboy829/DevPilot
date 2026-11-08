"""Append-only platform-derived project report drafts; preserve existing ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0008"
down_revision = "eval_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_report_archives",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), sa.ForeignKey("evaluation_projects.id"), nullable=False),
        sa.Column("root_id", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("supersedes_id", sa.String(32), nullable=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("template_id", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("archive_hash", sa.String(64), nullable=False),
        sa.Column("document", sa.JSON, nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_archive_project_id"),
        sa.UniqueConstraint("project_id", "supersedes_id", name="uq_evaluation_archive_successor"),
        sa.UniqueConstraint("root_id", "revision", name="uq_evaluation_archive_revision"),
        sa.ForeignKeyConstraint(["project_id", "supersedes_id"], ["evaluation_report_archives.project_id", "evaluation_report_archives.id"]),
        sa.CheckConstraint("revision BETWEEN 1 AND 1000 AND created_at_ms > 0", name="ck_evaluation_archive_bounds"),
    )
    op.create_index("ix_evaluation_archive_project_time", "evaluation_report_archives", ["project_id", "created_at_ms"])


def downgrade():
    op.drop_index("ix_evaluation_archive_project_time", table_name="evaluation_report_archives")
    op.drop_table("evaluation_report_archives")
