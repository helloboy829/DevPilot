"""Add an atomic owner-visible project result fence."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0019"
down_revision = "eval_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_projects", sa.Column("result_revision", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("evaluation_projects", "result_revision")
