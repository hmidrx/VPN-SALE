"""Milestone 6-C2 service migrations and controlled failover

Revision ID: 0022_m6c2_migrations
Revises: 0021_m6c1_service_operations
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_m6c2_migrations"
down_revision: str = "0021_m6c1_service_operations"
branch_labels: None = None
depends_on: None = None

UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (
        UUID("62c20000-0000-4000-8000-000000000001"),
        "service_migrations.read",
        "Read service migrations",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000002"),
        "service_migrations.manage",
        "Manage service migration drafts",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000003"),
        "service_migrations.simulate",
        "Simulate service migration targets",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000004"),
        "service_migrations.request",
        "Request service migration approval",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000005"),
        "service_migrations.approve",
        "Approve service migrations",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000006"),
        "service_migrations.execute",
        "Execute service migrations",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000007"),
        "service_migrations.cutover",
        "Cut over verified migrations",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000008"),
        "service_migrations.cleanup",
        "Clean up migrated source identities",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000009"),
        "service_migrations.rollback",
        "Rollback service migrations",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000010"),
        "service_migrations.compensate",
        "Review migration compensation",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000011"),
        "failover_proposals.read",
        "Read controlled failover proposals",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000012"),
        "failover_proposals.manage",
        "Manage controlled failover proposals",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000013"),
        "orphan_identities.read",
        "Read orphan remote identities",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000014"),
        "orphan_identities.manage",
        "Review orphan identity cleanup",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000015"),
        "migration_policies.manage",
        "Manage migration policies",
    ),
    (
        UUID("62c20000-0000-4000-8000-000000000016"),
        "migration_policies.publish",
        "Publish migration policies",
    ),
)


def _seed_permissions() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", UUID_T),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    grant = sa.text(
        "insert into role_permissions (role_id, permission_id) "
        "select roles.id, :permission_id from roles "
        "where roles.machine_name = 'super_admin' on conflict do nothing"
    )
    for pid, code, description in PERMISSIONS:
        op.execute(
            postgresql.insert(permissions)
            .values(id=pid, code=code, description=description)
            .on_conflict_do_update(
                index_elements=[permissions.c.code], set_={"description": description}
            )
        )
        op.execute(grant.bindparams(sa.bindparam("permission_id", pid, type_=UUID_T)))


def upgrade() -> None:
    _seed_permissions()
    op.create_table(
        "service_migration_policies",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID_T),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("name", name="uq_service_migration_policies_name"),
    )
    op.create_table(
        "service_migration_policy_versions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "policy_id",
            UUID_T,
            sa.ForeignKey("service_migration_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("allowed_source_provider_kinds", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("allowed_target_provider_kinds", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("allowed_protocols", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("allow_cross_provider", sa.Boolean(), nullable=False),
        sa.Column("preserve_credentials_when_supported", sa.Boolean(), nullable=False),
        sa.Column("require_rotation_for_security_moves", sa.Boolean(), nullable=False),
        sa.Column("allowed_cutover_strategies", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("allowed_cleanup_strategies", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("dual_active_grace_seconds", sa.Integer(), nullable=False),
        sa.Column("source_cleanup_delay_seconds", sa.Integer(), nullable=False),
        sa.Column("inventory_max_age_seconds", sa.Integer(), nullable=False),
        sa.Column("required_capabilities", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("max_migrations_per_service_window", sa.Integer(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("high_risk_approval_required", sa.Boolean(), nullable=False),
        sa.Column("rollback_window_seconds", sa.Integer(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "policy_id", "version_number", name="uq_service_migration_policy_versions_number"
        ),
    )
    op.create_table(
        "service_migrations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("migration_reference", sa.String(40), nullable=False),
        sa.Column("service_id", UUID_T, nullable=False),
        sa.Column("service_public_reference", sa.String(80), nullable=False),
        sa.Column("requester_id", UUID_T, nullable=False),
        sa.Column("migration_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column(
            "policy_version_id",
            UUID_T,
            sa.ForeignKey("service_migration_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("plan_digest", sa.String(80), nullable=False),
        sa.Column("source_snapshot_id", UUID_T),
        sa.Column("target_snapshot_id", UUID_T),
        sa.Column("cutover_id", UUID_T),
        sa.Column("rollback_id", UUID_T),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("migration_reference", name="uq_service_migrations_reference"),
    )
    op.create_index(
        "ix_service_migrations_status_updated", "service_migrations", ["status", "updated_at"]
    )
    op.create_index(
        "ix_service_migrations_one_active",
        "service_migrations",
        ["service_id"],
        unique=True,
        postgresql_where=sa.text(
            "status not in ('COMPLETED','ROLLED_BACK','CANCELLED','EXPIRED','FAILED')"
        ),
    )
    op.create_table(
        "service_migration_source_snapshots",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id", UUID_T, sa.ForeignKey("service_migrations.id", ondelete="RESTRICT")
        ),
        sa.Column("service_id", UUID_T, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("traffic_limit_bytes", sa.BigInteger()),
        sa.Column("local_lifetime_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("observed_remote_usage_bytes", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("device_limit", sa.Integer()),
        sa.Column("source_uncertain", sa.Boolean(), nullable=False),
        sa.Column("ownership_verified", sa.Boolean(), nullable=False),
        sa.Column("delivery_revision_id", UUID_T),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_migration_target_snapshots",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("all_targets_verified", sa.Boolean(), nullable=False),
        sa.Column("delivery_profiles_compatible", sa.Boolean(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_migration_attachment_plans",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_attachment_id", UUID_T, nullable=False),
        sa.Column("target_id", UUID_T, nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("credential_strategy", sa.String(64), nullable=False),
        sa.Column("cutover_strategy", sa.String(40), nullable=False),
        sa.Column("cleanup_strategy", sa.String(40), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("delivery_profile_version_id", UUID_T, nullable=False),
        sa.Column("target_reservation_id", UUID_T),
        sa.Column("provider_operation_id", UUID_T),
        sa.Column("target_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cleanup_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint(
            "migration_id", "source_attachment_id", name="uq_service_migration_attachment_source"
        ),
    )
    op.create_table(
        "service_migration_approvals",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_id", UUID_T, nullable=False),
        sa.Column("requester_id", UUID_T, nullable=False),
        sa.Column("plan_digest", sa.String(80), nullable=False),
        sa.Column("high_risk", sa.Boolean(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_migration_steps",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leased_until", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "migration_id",
            "name",
            "idempotency_key_digest",
            name="uq_service_migration_step_idempotency",
        ),
    )
    op.create_table(
        "service_migration_attempts",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "step_id",
            UUID_T,
            sa.ForeignKey("service_migration_steps.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_operation_id", UUID_T),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "service_migration_cutovers",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_delivery_revision_id", UUID_T),
        sa.Column("new_delivery_revision_id", UUID_T, nullable=False),
        sa.Column("stable_subscription_token_digest", sa.String(80), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("migration_id", name="uq_service_migration_cutover_once"),
    )
    op.create_table(
        "service_migration_reconciliations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("requires_approval_for_repair", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_migration_rollbacks",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rollback_type", sa.String(32), nullable=False),
        sa.Column("plan_digest", sa.String(80), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "service_migration_compensations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_migration_notifications",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("template", sa.String(80), nullable=False),
        sa.Column("safe_link_path", sa.String(240), nullable=False),
        sa.Column("outbox_key", sa.String(120), nullable=False),
        sa.UniqueConstraint("outbox_key", name="uq_service_migration_notifications_outbox"),
    )
    op.create_table(
        "service_allocation_replacements",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_target_id", UUID_T, nullable=False),
        sa.Column("target_target_id", UUID_T, nullable=False),
        sa.Column("source_released", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("target_active", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_table(
        "failover_proposals",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("source_unreachable", sa.Boolean(), nullable=False),
        sa.Column("evidence_digest", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "converted_migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
        ),
    )
    op.create_table(
        "orphaned_remote_identities",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "migration_id",
            UUID_T,
            sa.ForeignKey("service_migrations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("service_id", UUID_T, nullable=False),
        sa.Column("source_attachment_id", UUID_T, nullable=False),
        sa.Column("remote_identity_reference_digest", sa.String(80), nullable=False),
        sa.Column("possible_active", sa.Boolean(), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cleanup_approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint(
            "migration_id",
            "source_attachment_id",
            "remote_identity_reference_digest",
            name="uq_orphaned_remote_identity_evidence",
        ),
    )
    op.create_index(
        "ix_orphaned_remote_identities_possible_active",
        "orphaned_remote_identities",
        ["possible_active", "detected_at"],
    )


def downgrade() -> None:
    for table in (
        "orphaned_remote_identities",
        "failover_proposals",
        "service_allocation_replacements",
        "service_migration_notifications",
        "service_migration_compensations",
        "service_migration_rollbacks",
        "service_migration_reconciliations",
        "service_migration_cutovers",
        "service_migration_attempts",
        "service_migration_steps",
        "service_migration_approvals",
        "service_migration_attachment_plans",
        "service_migration_target_snapshots",
        "service_migration_source_snapshots",
        "service_migrations",
        "service_migration_policy_versions",
        "service_migration_policies",
    ):
        op.drop_table(table)
    codes = [code for _, code, _ in PERMISSIONS]
    op.execute(
        sa.text(
            "delete from role_permissions where permission_id in "
            "(select id from permissions where code = any(:codes))"
        ).bindparams(sa.bindparam("codes", codes, type_=postgresql.ARRAY(sa.String())))
    )
    op.execute(
        sa.text("delete from permissions where code = any(:codes)").bindparams(
            sa.bindparam("codes", codes, type_=postgresql.ARRAY(sa.String()))
        )
    )
