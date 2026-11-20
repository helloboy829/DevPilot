"""Add actor-bound response evidence grants and access audit."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0021"
down_revision = "eval_0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_evidence_access_grants",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("artifact_id", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("evidence_kind", sa.String(16), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at_ms", sa.BigInteger, nullable=False),
        sa.Column("expires_at_ms", sa.BigInteger, nullable=False),
        sa.Column("consumed_at_ms", sa.BigInteger),
        sa.Column("revoked_at_ms", sa.BigInteger),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
        sa.ForeignKeyConstraint(["artifact_id"], ["evaluation_response_artifacts.id"]),
        sa.CheckConstraint("length(token_hash) = 64 AND token_hash = lower(token_hash)", name="ck_evaluation_evidence_grant_token_hash"),
        sa.CheckConstraint("evidence_kind = 'response' AND length(evidence_hash) = 64", name="ck_evaluation_evidence_grant_evidence"),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 10000 AND length(actor_id) BETWEEN 1 AND 64", name="ck_evaluation_evidence_grant_subject"),
        sa.CheckConstraint("created_at_ms > 0 AND expires_at_ms > created_at_ms AND expires_at_ms - created_at_ms <= 300000", name="ck_evaluation_evidence_grant_expiry"),
        sa.CheckConstraint("consumed_at_ms IS NULL OR consumed_at_ms >= created_at_ms", name="ck_evaluation_evidence_grant_consumed"),
        sa.CheckConstraint("revoked_at_ms IS NULL OR revoked_at_ms >= created_at_ms", name="ck_evaluation_evidence_grant_revoked"),
    )
    op.create_table(
        "evaluation_evidence_access_audit",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("evidence_kind", sa.String(16), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("authorization_basis", sa.String(32), nullable=False),
        sa.Column("at_ms", sa.BigInteger, nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_dispatch_runs.project_id", "evaluation_dispatch_runs.id"]),
        sa.ForeignKeyConstraint(["run_id", "ordinal"], ["evaluation_dispatches.run_id", "evaluation_dispatches.ordinal"]),
        sa.UniqueConstraint("run_id", "sequence", name="uq_evaluation_evidence_audit_sequence"),
        sa.CheckConstraint("sequence BETWEEN 1 AND 10000000 AND ordinal BETWEEN 1 AND 10000", name="ck_evaluation_evidence_audit_sequence"),
        sa.CheckConstraint("evidence_kind = 'response' AND length(evidence_hash) = 64", name="ck_evaluation_evidence_audit_evidence"),
        sa.CheckConstraint("action IN ('granted','read') AND authorization_basis = 'project_member'", name="ck_evaluation_evidence_audit_action"),
        sa.CheckConstraint("length(actor_id) BETWEEN 1 AND 64 AND at_ms > 0", name="ck_evaluation_evidence_audit_actor_clock"),
    )


def downgrade():
    op.drop_table("evaluation_evidence_access_audit")
    op.drop_table("evaluation_evidence_access_grants")
