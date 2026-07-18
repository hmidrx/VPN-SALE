"""Milestone 6-B1 service provisioning core

Revision ID: 0019_m6b1_services
Revises: 0018_m6a2b
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_m6b1_services"
down_revision: str = "0018_m6a2b"
branch_labels: None = None
depends_on: None = None

UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (UUID("62b10000-0000-4000-8000-000000000001"), "services.read", "Read service status"),
    (UUID("62b10000-0000-4000-8000-000000000002"), "services.manage", "Manage services"),
    (
        UUID("62b10000-0000-4000-8000-000000000003"),
        "services.read_sensitive",
        "Read sensitive service operations metadata",
    ),
    (UUID("62b10000-0000-4000-8000-000000000004"), "fulfillment.read", "Read fulfillment requests"),
    (
        UUID("62b10000-0000-4000-8000-000000000005"),
        "fulfillment.manage",
        "Manage fulfillment requests",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000006"),
        "provisioning.read",
        "Read provisioning workflows",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000007"),
        "provisioning.retry",
        "Retry eligible provisioning workflows",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000008"),
        "provisioning.review",
        "Review provisioning workflows",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000009"),
        "allocation.read",
        "Read allocation policies and pools",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000010"),
        "allocation.manage",
        "Manage allocation drafts and pools",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000011"),
        "allocation.publish",
        "Publish allocation policies",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000012"),
        "allocation.simulate",
        "Simulate allocation decisions",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000013"),
        "capacity.read",
        "Read capacity and reservations",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000014"),
        "capacity.manage",
        "Manage capacity reservations",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000015"),
        "service_reconciliation.read",
        "Read service reconciliation",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000016"),
        "service_reconciliation.manage",
        "Manage service reconciliation",
    ),
    (
        UUID("62b10000-0000-4000-8000-000000000017"),
        "service_compensation.approve",
        "Approve service compensation",
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
            sa.dialects.postgresql.insert(table)
            .values(id=pid, code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def upgrade() -> None:
    _seed_permissions()
    op.create_table(
        "services",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("public_reference", sa.String(48), nullable=False),
        sa.Column("lifecycle", sa.String(40), nullable=False),
        sa.Column(
            "beneficiary_customer_id", UUID_T, sa.ForeignKey("identity_users.id"), nullable=False
        ),
        sa.Column("payer_type", sa.String(32), nullable=False),
        sa.Column("payer_reference", sa.String(80), nullable=False),
        sa.Column("reseller_id", UUID_T),
        sa.Column("order_id", UUID_T, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_item_id", UUID_T, sa.ForeignKey("order_items.id"), nullable=False),
        sa.Column("unit_index", sa.Integer, nullable=False),
        sa.Column("entitlement_snapshot", JSONB, nullable=False),
        sa.Column("allocation_policy_snapshot", JSONB),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("public_reference"),
        sa.UniqueConstraint("order_item_id", "unit_index"),
    )
    op.create_index(
        "ix_services_beneficiary_created", "services", ["beneficiary_customer_id", "created_at"]
    )
    op.create_index("ix_services_lifecycle_expiry", "services", ["lifecycle", "expires_at"])
    op.create_table(
        "service_fulfillment_requests",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("deduplication_key", sa.String(160), nullable=False),
        sa.Column("order_id", UUID_T, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("order_item_id", UUID_T, sa.ForeignKey("order_items.id"), nullable=False),
        sa.Column("unit_index", sa.Integer, nullable=False),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id")),
        sa.Column("event_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column("causation_id", sa.String(96), nullable=False),
        sa.Column("lease_owner", sa.String(96)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("result_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("deduplication_key"),
        sa.UniqueConstraint("order_item_id", "unit_index"),
    )
    op.create_index(
        "ix_service_fulfillment_status_lease",
        "service_fulfillment_requests",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "allocation_policies",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID_T),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "allocation_policy_versions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("policy_id", UUID_T, sa.ForeignKey("allocation_policies.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(40), nullable=False),
        sa.Column("success_policy", sa.String(40), nullable=False),
        sa.Column("immutable_snapshot", JSONB, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("policy_id", "version_number"),
    )
    op.create_table(
        "allocation_pools",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "allocation_targets",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("pool_id", UUID_T, sa.ForeignKey("allocation_pools.id"), nullable=False),
        sa.Column("panel_id", UUID_T, nullable=False),
        sa.Column("node_id", UUID_T),
        sa.Column("inbound_id", sa.String(120), nullable=False),
        sa.Column("provider_kind", sa.String(64), nullable=False),
        sa.Column("required_protocol", sa.String(40), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("weight", sa.Integer, nullable=False),
        sa.Column("max_capacity", sa.Integer, nullable=False),
        sa.Column("safety_reserve", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("certification_minimum", sa.String(80), nullable=False),
        sa.Column("safe_diagnostics", JSONB, nullable=False),
        sa.CheckConstraint("weight > 0 and max_capacity >= 0 and safety_reserve >= 0"),
        sa.UniqueConstraint("panel_id", "inbound_id", "provider_kind"),
    )
    op.create_index(
        "ix_allocation_targets_pool_status", "allocation_targets", ["pool_id", "status"]
    )
    op.create_table(
        "service_attachments",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False),
        sa.Column(
            "allocation_target_id", UUID_T, sa.ForeignKey("allocation_targets.id"), nullable=False
        ),
        sa.Column("required", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("verification_status", sa.String(40), nullable=False),
        sa.Column("provider_operation_id", UUID_T),
        sa.Column("remote_identity_reference", sa.String(160)),
        sa.Column("credential_fingerprint", sa.String(120)),
        sa.Column("target_snapshot", JSONB, nullable=False),
        sa.Column("observed_state", JSONB, nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("service_id", "allocation_target_id"),
        sa.UniqueConstraint("allocation_target_id", "remote_identity_reference"),
    )
    op.create_index(
        "ix_service_attachments_service_status", "service_attachments", ["service_id", "status"]
    )
    op.create_table(
        "allocation_reservations",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False),
        sa.Column(
            "allocation_target_id", UUID_T, sa.ForeignKey("allocation_targets.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reserved_units", sa.Integer, nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
        sa.Column("owner_reference", sa.String(96), nullable=False),
        sa.CheckConstraint("reserved_units > 0"),
        sa.UniqueConstraint("service_id", "allocation_target_id", "status"),
    )
    op.create_index(
        "ix_allocation_reservations_status_expiry",
        "allocation_reservations",
        ["status", "expires_at"],
    )
    op.create_table(
        "service_provisioning_workflows",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("current_step", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column("causation_id", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_service_workflows_status_updated",
        "service_provisioning_workflows",
        ["status", "updated_at"],
    )
    op.create_table(
        "service_reconciliation_issues",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id"), nullable=False),
        sa.Column("attachment_id", UUID_T, sa.ForeignKey("service_attachments.id")),
        sa.Column("outcome", sa.String(48), nullable=False),
        sa.Column("severity", sa.String(24), nullable=False),
        sa.Column("safe_reason_code", sa.String(80), nullable=False),
        sa.Column("repair_plan", JSONB),
        sa.Column("compensation_plan", JSONB),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_service_reconciliation_status_created",
        "service_reconciliation_issues",
        ["status", "created_at"],
    )


def downgrade() -> None:
    for table in [
        "service_reconciliation_issues",
        "service_provisioning_workflows",
        "allocation_reservations",
        "service_attachments",
        "allocation_targets",
        "allocation_pools",
        "allocation_policy_versions",
        "allocation_policies",
        "service_fulfillment_requests",
        "services",
    ]:
        op.drop_table(table)
    permissions = sa.table("permissions", sa.column("code", sa.String))
    for _, code, _ in PERMISSIONS:
        op.execute(permissions.delete().where(permissions.c.code == code))
