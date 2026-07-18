"""Milestone 6-D1 service usage and lifecycle automation

Revision ID: 0023_m6d1_usage_lifecycle
Revises: 0022_m6c2_migrations
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_m6d1_usage_lifecycle"
down_revision: str = "0022_m6c2_migrations"
branch_labels: None = None
depends_on: None = None

UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (
        UUID("62d10000-0000-4000-8000-000000000001"),
        "service_usage.read",
        "Read service usage summaries",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000002"),
        "service_usage.read_sensitive",
        "Read sensitive usage diagnostics",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000003"),
        "service_usage.sync",
        "Run service usage synchronization",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000004"),
        "service_usage.manage_policies",
        "Manage usage policies",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000005"),
        "service_usage.publish_policies",
        "Publish usage policies",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000006"),
        "service_usage.manage_thresholds",
        "Manage usage thresholds",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000007"),
        "service_usage.read_anomalies",
        "Read usage anomalies",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000008"),
        "service_usage.manage_anomalies",
        "Manage usage anomalies",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000009"),
        "service_usage.correct",
        "Create append-only usage corrections",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000010"),
        "service_usage.approve_correction",
        "Approve high-risk usage corrections",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000011"),
        "lifecycle_automation.read",
        "Read lifecycle automation state",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000012"),
        "lifecycle_automation.manage",
        "Manage lifecycle automation",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000013"),
        "lifecycle_automation.retry",
        "Retry lifecycle automation safely",
    ),
    (
        UUID("62d10000-0000-4000-8000-000000000014"),
        "usage_notifications.read",
        "Read usage notification events",
    ),
)


def _seed_permissions() -> None:
    table = sa.table(
        "permissions",
        sa.column("id", UUID_T),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    for pid, code, description in PERMISSIONS:
        op.execute(
            postgresql.insert(table)
            .values(id=pid, code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def upgrade() -> None:
    _seed_permissions()
    op.create_table(
        "service_usage_accounts",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False, unique=True),
        sa.Column("allowance_bytes", sa.BigInteger, nullable=True),
        sa.Column("is_unlimited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("aggregation_policy_version", sa.Integer, nullable=False),
        sa.Column("lifetime_baseline_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "allowance_bytes is null or allowance_bytes >= 0",
            name="ck_usage_accounts_allowance_nonnegative",
        ),
        sa.CheckConstraint(
            "lifetime_baseline_bytes >= 0", name="ck_usage_accounts_lifetime_nonnegative"
        ),
        sa.CheckConstraint(
            "not (is_unlimited and allowance_bytes is not null)",
            name="ck_usage_accounts_unlimited_distinct",
        ),
    )
    op.create_table(
        "service_usage_cycles",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("cycle_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("start_reason", sa.String(80), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allowance_snapshot", JSONB, nullable=False),
        sa.Column("lifetime_baseline_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("aggregation_policy_version", sa.Integer, nullable=False),
        sa.Column("service_operation_id", UUID_T, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "lifetime_baseline_bytes >= 0", name="ck_usage_cycles_lifetime_baseline_nonnegative"
        ),
    )
    op.create_index(
        "ix_usage_cycles_account_status", "service_usage_cycles", ["usage_account_id", "status"]
    )
    op.create_table(
        "service_usage_counter_generations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("attachment_id", UUID_T, sa.ForeignKey("service_attachments.id"), nullable=False),
        sa.Column("counter_scope_key", sa.String(160), nullable=False),
        sa.Column("generation_number", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_reason", sa.String(80), nullable=False),
        sa.Column("source_operation_id", UUID_T, nullable=True),
        sa.UniqueConstraint(
            "attachment_id",
            "counter_scope_key",
            "generation_number",
            name="uq_usage_counter_generation",
        ),
    )
    op.create_table(
        "service_usage_observations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("attachment_id", UUID_T, sa.ForeignKey("service_attachments.id"), nullable=False),
        sa.Column(
            "counter_generation_id",
            UUID_T,
            sa.ForeignKey("service_usage_counter_generations.id"),
            nullable=True,
        ),
        sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("provider_contract_code", sa.String(80), nullable=False),
        sa.Column("adapter_version", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counter_scope_key", sa.String(160), nullable=False),
        sa.Column("upload_bytes", sa.BigInteger, nullable=True),
        sa.Column("download_bytes", sa.BigInteger, nullable=True),
        sa.Column("combined_bytes", sa.BigInteger, nullable=True),
        sa.Column("remote_limit_bytes", sa.BigInteger, nullable=True),
        sa.Column("remote_expiry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("remote_enabled", sa.Boolean, nullable=True),
        sa.Column("online_state", sa.Boolean, nullable=True),
        sa.Column("confidence", sa.String(24), nullable=False),
        sa.Column("anomaly_flags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("idempotency_key_hash", sa.String(96), nullable=False),
        sa.CheckConstraint(
            "upload_bytes is null or upload_bytes >= 0", name="ck_usage_obs_upload_nonnegative"
        ),
        sa.CheckConstraint(
            "download_bytes is null or download_bytes >= 0",
            name="ck_usage_obs_download_nonnegative",
        ),
        sa.CheckConstraint(
            "combined_bytes is null or combined_bytes >= 0",
            name="ck_usage_obs_combined_nonnegative",
        ),
        sa.CheckConstraint(
            "remote_limit_bytes is null or remote_limit_bytes >= 0",
            name="ck_usage_obs_limit_nonnegative",
        ),
        sa.UniqueConstraint("idempotency_key_hash", name="uq_usage_observation_idempotency"),
    )
    op.create_index(
        "ix_usage_obs_service_time", "service_usage_observations", ["service_id", "observed_at"]
    )
    op.create_table(
        "service_usage_deltas",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("cycle_id", UUID_T, sa.ForeignKey("service_usage_cycles.id"), nullable=False),
        sa.Column(
            "observation_id", UUID_T, sa.ForeignKey("service_usage_observations.id"), nullable=True
        ),
        sa.Column(
            "counter_generation_id",
            UUID_T,
            sa.ForeignKey("service_usage_counter_generations.id"),
            nullable=True,
        ),
        sa.Column("delta_bytes", sa.BigInteger, nullable=False),
        sa.Column("delta_kind", sa.String(40), nullable=False),
        sa.Column("confidence", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("approved_by_admin_id", UUID_T, nullable=True),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.CheckConstraint("delta_bytes >= 0", name="ck_usage_delta_nonnegative"),
    )
    op.create_table(
        "service_usage_aggregates",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("cycle_id", UUID_T, sa.ForeignKey("service_usage_cycles.id"), nullable=False),
        sa.Column("used_bytes", sa.BigInteger, nullable=True),
        sa.Column("remaining_bytes", sa.BigInteger, nullable=True),
        sa.Column("overage_bytes", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("consumed_percent", sa.Integer, nullable=True),
        sa.Column("quota_state", sa.String(48), nullable=False),
        sa.Column("expiry_state", sa.String(48), nullable=False),
        sa.Column("confidence", sa.String(24), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("explanation_code", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint(
            "used_bytes is null or used_bytes >= 0", name="ck_usage_agg_used_nonnegative"
        ),
        sa.CheckConstraint(
            "remaining_bytes is null or remaining_bytes >= 0",
            name="ck_usage_agg_remaining_nonnegative",
        ),
        sa.CheckConstraint("overage_bytes >= 0", name="ck_usage_agg_overage_nonnegative"),
    )
    op.create_index(
        "ix_usage_agg_state_time",
        "service_usage_aggregates",
        ["quota_state", "expiry_state", "calculated_at"],
    )
    op.create_table(
        "service_usage_anomalies",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column(
            "observation_id", UUID_T, sa.ForeignKey("service_usage_observations.id"), nullable=True
        ),
        sa.Column("anomaly_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("safe_detail", sa.String(240), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_usage_anomalies_status_type", "service_usage_anomalies", ["status", "anomaly_type"]
    )
    op.create_table(
        "service_usage_threshold_events",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("cycle_id", UUID_T, sa.ForeignKey("service_usage_cycles.id"), nullable=False),
        sa.Column("policy_id", UUID_T, nullable=False),
        sa.Column("policy_version", sa.Integer, nullable=False),
        sa.Column("threshold_code", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("deduplication_key", sa.String(240), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("deduplication_key", name="uq_usage_threshold_dedupe"),
    )
    op.create_table(
        "service_usage_sync_runs",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("worker_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_summary", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_table(
        "service_usage_first_use_states",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id",
            UUID_T,
            sa.ForeignKey("service_usage_accounts.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calculated_expiry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_observation_id", UUID_T, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_table(
        "service_usage_rollups",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "usage_account_id", UUID_T, sa.ForeignKey("service_usage_accounts.id"), nullable=False
        ),
        sa.Column("window_kind", sa.String(16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_bytes", sa.BigInteger, nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("used_bytes >= 0", name="ck_usage_rollup_used_nonnegative"),
        sa.UniqueConstraint(
            "usage_account_id", "window_kind", "window_start", name="uq_usage_rollup_window"
        ),
    )


def downgrade() -> None:
    for table in (
        "service_usage_rollups",
        "service_usage_first_use_states",
        "service_usage_sync_runs",
        "service_usage_threshold_events",
        "service_usage_anomalies",
        "service_usage_aggregates",
        "service_usage_deltas",
        "service_usage_observations",
        "service_usage_counter_generations",
        "service_usage_cycles",
        "service_usage_accounts",
    ):
        op.drop_table(table)
    permissions = sa.table("permissions", sa.column("code", sa.String))
    for _, code, _ in PERMISSIONS:
        op.execute(permissions.delete().where(permissions.c.code == code))
