"""Milestone 6-C1 service operations

Revision ID: 0021_m6c1_service_operations
Revises: 0020_m6b2_delivery
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_m6c1_service_operations"
down_revision: str = "0020_m6b2_delivery"
branch_labels: None = None
depends_on: None = None
UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (
        UUID("62c10000-0000-4000-8000-000000000001"),
        "service_operations.read",
        "Read service operations",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000002"),
        "service_operations.manage",
        "Create and manage service operations",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000003"),
        "service_operations.execute",
        "Execute service operations",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000004"),
        "service_operations.approve",
        "Approve high-risk service operations",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000005"),
        "service_operations.compensate",
        "Review operation compensation",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000006"),
        "service_operations.manage_policies",
        "Manage service operation policy drafts",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000007"),
        "service_operations.publish_policies",
        "Publish service operation policies",
    ),
    (UUID("62c10000-0000-4000-8000-000000000008"), "services.suspend", "Suspend services"),
    (UUID("62c10000-0000-4000-8000-000000000009"), "services.resume", "Resume services"),
    (
        UUID("62c10000-0000-4000-8000-000000000010"),
        "services.reset_traffic",
        "Reset provider traffic counters",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000011"),
        "services.clear_ips",
        "Clear provider client IP records",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000012"),
        "services.rotate_credentials",
        "Rotate service credentials",
    ),
    (
        UUID("62c10000-0000-4000-8000-000000000013"),
        "services.reduce_entitlement",
        "Reduce service entitlement projections",
    ),
)


def _seed_permissions() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", UUID_T),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    for pid, code, description in PERMISSIONS:
        op.execute(
            sa.dialects.postgresql.insert(permissions)
            .values(id=pid, code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def upgrade() -> None:
    _seed_permissions()
    op.create_table(
        "service_operation_policies",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID_T),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("name", name="uq_service_operation_policies_name"),
    )
    op.create_table(
        "service_operation_policy_versions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "policy_id",
            UUID_T,
            sa.ForeignKey("service_operation_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("immutable_snapshot", JSONB, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "policy_id", "version_number", name="uq_service_operation_policy_versions_number"
        ),
    )
    op.create_table(
        "service_operations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("operation_type", sa.String(48), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("requester_type", sa.String(32), nullable=False),
        sa.Column("requester_id", sa.String(96), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(96), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column(
            "policy_version_id",
            UUID_T,
            sa.ForeignKey("service_operation_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("policy_snapshot", JSONB, nullable=False),
        sa.Column("desired_change", JSONB, nullable=False),
        sa.Column("quote_snapshot", JSONB),
        sa.Column("order_id", UUID_T, sa.ForeignKey("orders.id", ondelete="RESTRICT")),
        sa.Column("invoice_id", UUID_T, sa.ForeignKey("invoices.id", ondelete="RESTRICT")),
        sa.Column("payment_id", UUID_T, sa.ForeignKey("wallet_payments.id", ondelete="RESTRICT")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "service_id", "idempotency_key_digest", name="uq_service_operations_service_idempotency"
        ),
    )
    op.create_index(
        "ix_service_operations_status_created", "service_operations", ["status", "created_at"]
    )
    op.create_index(
        "ix_service_operations_service_created", "service_operations", ["service_id", "created_at"]
    )
    op.create_table(
        "service_operation_attachment_plans",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            UUID_T,
            sa.ForeignKey("service_attachments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("provider_operation_id", UUID_T),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("expected_snapshot_digest", sa.String(96), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("uncertain", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("result_snapshot", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "operation_id", "attachment_id", name="uq_service_operation_attachment"
        ),
    )
    op.create_table(
        "service_state_revisions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("desired_state", JSONB, nullable=False),
        sa.Column("previous_revision_id", UUID_T),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "service_id", "revision_number", name="uq_service_state_revisions_number"
        ),
    )
    op.create_table(
        "service_operation_approvals",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("requested_by", sa.String(96), nullable=False),
        sa.Column("decided_by", sa.String(96), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "requested_by <> decided_by", name="ck_service_operation_no_self_approval"
        ),
    )
    op.create_table(
        "service_usage_snapshots",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "operation_id", UUID_T, sa.ForeignKey("service_operations.id", ondelete="RESTRICT")
        ),
        sa.Column("lifetime_used_bytes", sa.BigInteger(), nullable=False),
        sa.Column("provider_counter_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reset_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(48), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "lifetime_used_bytes >= 0 and provider_counter_bytes >= 0",
            name="ck_service_usage_non_negative",
        ),
    )
    op.create_table(
        "service_credential_rotations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("pending_material_id", UUID_T, nullable=False),
        sa.Column("previous_material_id", UUID_T, nullable=False),
        sa.Column("new_fingerprint", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("operation_id", name="uq_service_credential_rotations_operation"),
    )
    op.create_table(
        "service_operation_reconciliations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("safe_reason_code", sa.String(80), nullable=False),
        sa.Column("repair_plan", JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "service_operation_compensations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("safe_reason_code", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "service_operation_compensations",
        "service_operation_reconciliations",
        "service_credential_rotations",
        "service_usage_snapshots",
        "service_operation_approvals",
        "service_state_revisions",
        "service_operation_attachment_plans",
        "service_operations",
        "service_operation_policy_versions",
        "service_operation_policies",
    ):
        op.drop_table(table)
