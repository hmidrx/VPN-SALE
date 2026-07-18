"""Milestone 6-D2 fleet operations

Revision ID: 0024_m6d2_fleet_operations
Revises: 0023_m6d1_usage_lifecycle
Create Date: 2026-07-18 00:00:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_m6d2_fleet_operations"
down_revision: str = "0023_m6d1_usage_lifecycle"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "fleet_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_type", sa.String(length=40), nullable=False),
        sa.Column("safe_label", sa.String(length=160), nullable=False),
        sa.Column("provider_kind", sa.String(length=80), nullable=True),
        sa.Column("parent_resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("allocation_target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operational_state", sa.String(length=40), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("optimistic_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("optimistic_version >= 1", name="ck_fleet_resources_version_positive"),
        sa.ForeignKeyConstraint(["parent_resource_id"], ["fleet_resources.id"]),
    )
    op.create_index(
        "ix_fleet_resources_type_state", "fleet_resources", ["resource_type", "operational_state"]
    )
    op.create_table(
        "fleet_health_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "fleet_health_policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("minimum_confidence", sa.Integer(), nullable=False),
        sa.Column("consecutive_failure_count", sa.Integer(), nullable=False),
        sa.Column("consecutive_recovery_count", sa.Integer(), nullable=False),
        sa.Column("freshness_seconds", sa.Integer(), nullable=False),
        sa.Column("required_signals", postgresql.ARRAY(sa.String(length=80)), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "minimum_confidence between 0 and 100", name="ck_fleet_policy_confidence"
        ),
        sa.ForeignKeyConstraint(["policy_id"], ["fleet_health_policies.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("policy_id", "version_number", name="uq_fleet_policy_version"),
    )
    op.create_table(
        "fleet_health_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_seconds", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=160), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint("confidence between 0 and 100", name="ck_fleet_observation_confidence"),
        sa.ForeignKeyConstraint(["resource_id"], ["fleet_resources.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_fleet_health_resource_signal_time",
        "fleet_health_observations",
        ["resource_id", "signal_type", "observed_at"],
    )
    op.create_table(
        "fleet_health_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("stale_signal_count", sa.Integer(), nullable=False),
        sa.Column("failing_signal_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("confidence between 0 and 100", name="ck_fleet_evaluation_confidence"),
        sa.ForeignKeyConstraint(["resource_id"], ["fleet_resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_version_id"], ["fleet_health_policy_versions.id"]),
    )
    op.create_table(
        "fleet_capacity_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hard_capacity", sa.Integer(), nullable=False),
        sa.Column("active_allocations", sa.Integer(), nullable=False),
        sa.Column("pending_reservations", sa.Integer(), nullable=False),
        sa.Column("migration_reservations", sa.Integer(), nullable=False),
        sa.Column("dual_active_consumption", sa.Integer(), nullable=False),
        sa.Column("safety_reserve", sa.Integer(), nullable=False),
        sa.Column("maintenance_reserve", sa.Integer(), nullable=False),
        sa.Column("uncertain_identities", sa.Integer(), nullable=False),
        sa.Column("stale_inventory_penalty", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            " AND ".join(
                (
                    "hard_capacity >= 0",
                    "active_allocations >= 0",
                    "pending_reservations >= 0",
                    "migration_reservations >= 0",
                    "dual_active_consumption >= 0",
                    "safety_reserve >= 0",
                    "maintenance_reserve >= 0",
                    "uncertain_identities >= 0",
                    "stale_inventory_penalty >= 0",
                )
            ),
            name="ck_fleet_capacity_non_negative",
        ),
    )
    op.create_index(
        "ix_fleet_capacity_target_time", "fleet_capacity_snapshots", ["target_id", "observed_at"]
    )
    for name in (
        "maintenance_windows",
        "drain_plans",
        "evacuation_plans",
        "evacuation_batches",
        "failover_proposals",
        "recovery_proposals",
        "bulk_operations",
        "bulk_operation_items",
        "runbooks",
        "runbook_versions",
        "runbook_executions",
        "manual_reviews",
    ):
        op.create_table(
            f"fleet_{name}",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("state", sa.String(length=40), nullable=False),
            sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("digest", sa.String(length=128), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("optimistic_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.CheckConstraint("optimistic_version >= 1", name=f"ck_fleet_{name}_version_positive"),
        )
        op.create_index(
            f"ix_fleet_{name}_state_deadline", f"fleet_{name}", ["state", "deadline_at"]
        )


def downgrade() -> None:
    for name in reversed(
        (
            "maintenance_windows",
            "drain_plans",
            "evacuation_plans",
            "evacuation_batches",
            "failover_proposals",
            "recovery_proposals",
            "bulk_operations",
            "bulk_operation_items",
            "runbooks",
            "runbook_versions",
            "runbook_executions",
            "manual_reviews",
        )
    ):
        op.drop_index(f"ix_fleet_{name}_state_deadline", table_name=f"fleet_{name}")
        op.drop_table(f"fleet_{name}")
    op.drop_index("ix_fleet_capacity_target_time", table_name="fleet_capacity_snapshots")
    op.drop_table("fleet_capacity_snapshots")
    op.drop_table("fleet_health_evaluations")
    op.drop_index("ix_fleet_health_resource_signal_time", table_name="fleet_health_observations")
    op.drop_table("fleet_health_observations")
    op.drop_table("fleet_health_policy_versions")
    op.drop_table("fleet_health_policies")
    op.drop_index("ix_fleet_resources_type_state", table_name="fleet_resources")
    op.drop_table("fleet_resources")
