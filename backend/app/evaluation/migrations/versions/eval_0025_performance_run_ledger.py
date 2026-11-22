"""Add durable performance-run and per-dispatch ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "eval_0025"
down_revision = "eval_0024"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_performance_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("scenario_hash", sa.String(64), nullable=False),
        sa.Column("profile_hash", sa.String(64), nullable=False),
        sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("population_count", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("window_start_ns", sa.BigInteger),
        sa.Column("window_end_ns", sa.BigInteger),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("finished_at", sa.String(40)),
        sa.ForeignKeyConstraint(["project_id"], ["evaluation_projects.id"]),
        sa.ForeignKeyConstraint(["project_id", "scenario_id"], ["evaluation_performance_scenarios.project_id", "evaluation_performance_scenarios.id"]),
        sa.UniqueConstraint("project_id", "id", name="uq_evaluation_performance_run_project_id"),
        sa.CheckConstraint("length(owner_id) BETWEEN 1 AND 64", name="ck_evaluation_performance_run_owner"),
        sa.CheckConstraint("length(scenario_hash) = 64 AND scenario_hash = lower(scenario_hash)", name="ck_evaluation_performance_run_scenario_hash"),
        sa.CheckConstraint("length(profile_hash) = 64 AND profile_hash = lower(profile_hash)", name="ck_evaluation_performance_run_profile_hash"),
        sa.CheckConstraint("length(manifest_hash) = 64 AND manifest_hash = lower(manifest_hash)", name="ck_evaluation_performance_run_manifest_hash"),
        sa.CheckConstraint("population_count BETWEEN 1 AND 11000", name="ck_evaluation_performance_run_population"),
        sa.CheckConstraint("status IN ('created','running','completed','interrupted','failed')", name="ck_evaluation_performance_run_status"),
        sa.CheckConstraint("(window_start_ns IS NULL AND window_end_ns IS NULL) OR (window_start_ns >= 0 AND window_end_ns >= window_start_ns)", name="ck_evaluation_performance_run_window"),
    )
    op.create_index("ix_evaluation_performance_run_owner_created", "evaluation_performance_runs", ["owner_id", "created_at", "id"])

    op.create_table(
        "evaluation_performance_dispatches",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("case_id", sa.String(80), nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False),
        sa.Column("dispatch_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("request_bytes", sa.Integer),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_bytes", sa.Integer),
        sa.Column("response_hash", sa.String(64)),
        sa.Column("evidence_ref", sa.String(128)),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("token_source", sa.String(40)),
        sa.Column("send_started_ns", sa.BigInteger),
        sa.Column("finished_ns", sa.BigInteger),
        sa.Column("elapsed_ms", sa.Float),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_evaluation_performance_dispatch_ordinal"),
        sa.UniqueConstraint("run_id", "dispatch_id", name="uq_evaluation_performance_dispatch_id"),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 10999 AND iteration >= 0", name="ck_evaluation_performance_dispatch_ordinal"),
        sa.CheckConstraint("phase IN ('warmup','measurement')", name="ck_evaluation_performance_dispatch_phase"),
        sa.CheckConstraint("state IN ('pending','dispatched','succeeded','failed','timeout','unknown','not_dispatched')", name="ck_evaluation_performance_dispatch_state"),
        sa.CheckConstraint("request_bytes IS NULL OR request_bytes BETWEEN 0 AND 1048576", name="ck_evaluation_performance_dispatch_request_bytes"),
        sa.CheckConstraint("response_bytes IS NULL OR response_bytes BETWEEN 0 AND 1048576", name="ck_evaluation_performance_dispatch_response_bytes"),
        sa.CheckConstraint("request_hash IS NULL OR (length(request_hash) = 64 AND request_hash = lower(request_hash))", name="ck_evaluation_performance_dispatch_request_hash"),
        sa.CheckConstraint("response_hash IS NULL OR (length(response_hash) = 64 AND response_hash = lower(response_hash))", name="ck_evaluation_performance_dispatch_response_hash"),
        sa.CheckConstraint("response_status IS NULL OR response_status BETWEEN 100 AND 599", name="ck_evaluation_performance_dispatch_response_status"),
        sa.CheckConstraint("output_tokens IS NULL OR (output_tokens >= 0 AND state = 'succeeded')", name="ck_evaluation_performance_dispatch_tokens"),
        sa.CheckConstraint("token_source IS NULL OR length(token_source) BETWEEN 1 AND 40", name="ck_evaluation_performance_dispatch_token_source"),
        sa.CheckConstraint(
            "(state IN ('pending','not_dispatched') AND send_started_ns IS NULL AND finished_ns IS NULL AND elapsed_ms IS NULL) OR "
            "(state = 'dispatched' AND send_started_ns >= 0 AND finished_ns IS NULL AND elapsed_ms IS NULL) OR "
            "(state = 'unknown' AND send_started_ns >= 0 AND ((finished_ns IS NULL AND elapsed_ms IS NULL) OR (finished_ns >= send_started_ns AND elapsed_ms >= 0))) OR "
            "(state IN ('succeeded','failed','timeout') AND send_started_ns >= 0 AND finished_ns >= send_started_ns AND elapsed_ms >= 0)",
            name="ck_evaluation_performance_dispatch_timing",
        ),
    )
    op.create_index("ix_evaluation_performance_dispatch_run_state", "evaluation_performance_dispatches", ["project_id", "run_id", "state"])
    op.create_index("ix_evaluation_performance_dispatch_evidence", "evaluation_performance_dispatches", ["evidence_ref"])

    op.create_table(
        "evaluation_performance_run_audit",
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("sequence", sa.Integer, primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["project_id", "run_id"], ["evaluation_performance_runs.project_id", "evaluation_performance_runs.id"]),
        sa.CheckConstraint("sequence >= 1", name="ck_evaluation_performance_run_audit_sequence"),
        sa.CheckConstraint("action IN ('run_created','dispatch_acknowledged','measurement_window_closed','observation_recorded','run_interrupted','run_finished')", name="ck_evaluation_performance_run_audit_action"),
    )


def downgrade():
    op.drop_table("evaluation_performance_run_audit")
    op.drop_index("ix_evaluation_performance_dispatch_evidence", table_name="evaluation_performance_dispatches")
    op.drop_index("ix_evaluation_performance_dispatch_run_state", table_name="evaluation_performance_dispatches")
    op.drop_table("evaluation_performance_dispatches")
    op.drop_index("ix_evaluation_performance_run_owner_created", table_name="evaluation_performance_runs")
    op.drop_table("evaluation_performance_runs")
