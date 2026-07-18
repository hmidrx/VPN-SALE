"""Milestone 6-A2B provider mutation operations

Revision ID: 0018_m6a2b
Revises: 0017_m6a2a
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_m6a2b"
down_revision: str = "0017_m6a2a"
branch_labels: None = None
depends_on: None = None

UUID_TYPE = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (
        UUID("62a2b000-0000-4000-8000-000000000001"),
        "providers.canary.read",
        "Read provider write-canary state",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000002"),
        "providers.canary.execute",
        "Execute staging provider write canary",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000003"),
        "providers.canary.cancel",
        "Cancel provider write canary",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000004"),
        "providers.write_enablement.read",
        "Read provider write enablement",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000005"),
        "providers.write_enablement.request",
        "Request provider write enablement",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000006"),
        "providers.write_enablement.approve",
        "Approve provider write enablement",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000007"),
        "providers.write_enablement.revoke",
        "Revoke provider write enablement",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000008"),
        "providers.operations.read",
        "Read provider operation history",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000009"),
        "providers.operations.review",
        "Review provider uncertain operations",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000010"),
        "providers.reconciliation.read",
        "Read provider reconciliation issues",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000011"),
        "providers.reconciliation.manage",
        "Manage provider reconciliation",
    ),
    (
        UUID("62a2b000-0000-4000-8000-000000000012"),
        "providers.compensation.approve",
        "Approve provider compensation",
    ),
)


def _seed_permissions() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", UUID_TYPE),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    grant = sa.text(
        "insert into role_permissions (role_id, permission_id) "
        "select roles.id, :permission_id from roles "
        "where roles.machine_name = 'super_admin' on conflict do nothing"
    ).bindparams(sa.bindparam("permission_id", type_=UUID_TYPE))
    conn = op.get_bind()
    for permission_id, code, description in PERMISSIONS:
        conn.execute(
            postgresql.insert(permissions)
            .values(id=permission_id, code=code, description=description)
            .on_conflict_do_update(
                index_elements=[permissions.c.code], set_={"description": description}
            )
        )
        conn.execute(grant, {"permission_id": permission_id})


def upgrade() -> None:
    op.create_table(
        "provider_write_enablements",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("panel_reference", sa.String(80), nullable=False, unique=True),
        sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("write_mode", sa.String(40), nullable=False, server_default="READ_ONLY"),
        sa.Column("detected_version", sa.String(40)),
        sa.Column("contract_digest", sa.String(96)),
        sa.Column("canary_report_digest", sa.String(96)),
        sa.Column("approved_capabilities", JSONB, nullable=False, server_default="[]"),
        sa.Column("requested_by", sa.String(120)),
        sa.Column("approved_by", sa.String(120)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("optimistic_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "write_mode in ('READ_ONLY','CANARY_ONLY','WRITE_PENDING_APPROVAL',"
            "'WRITE_ENABLED','WRITE_SUSPENDED','RECERTIFICATION_REQUIRED')",
            name="ck_provider_write_enablements_mode",
        ),
        sa.CheckConstraint(
            "requested_by is null or approved_by is null or requested_by <> approved_by",
            name="ck_provider_write_no_self_approval",
        ),
    )
    op.create_table(
        "provider_operations",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("operation_id", UUID_TYPE, nullable=False, unique=True),
        sa.Column("panel_reference", sa.String(80), nullable=False),
        sa.Column("provider_kind", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("capability", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("idempotency_scope", sa.String(220), nullable=False),
        sa.Column("request_digest", sa.String(96), nullable=False),
        sa.Column("plan_digest", sa.String(96), nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_snapshot_digest", sa.String(96)),
        sa.Column("desired_state", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "panel_reference", "idempotency_scope", name="uq_provider_operations_idempotency_scope"
        ),
        sa.Index("ix_provider_operations_panel_status", "panel_reference", "status"),
    )
    op.create_table(
        "provider_operation_attempts",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("operation_id", UUID_TYPE, nullable=False),
        sa.Column("status_before_transport", sa.String(40), nullable=False),
        sa.Column("sanitized_endpoint_identifier", sa.String(160), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["provider_operations.operation_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "provider_operation_verifications",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("operation_id", UUID_TYPE, nullable=False),
        sa.Column("outcome", sa.String(60), nullable=False),
        sa.Column("observed_snapshot_digest", sa.String(96)),
        sa.Column("safe_reason", sa.String(240), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["provider_operations.operation_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "provider_reconciliation_issues",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("operation_id", UUID_TYPE, nullable=False),
        sa.Column("outcome", sa.String(80), nullable=False),
        sa.Column("safe_summary", sa.String(300), nullable=False),
        sa.Column("destructive_repair_requires_approval", sa.Boolean, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["operation_id"], ["provider_operations.operation_id"], ondelete="CASCADE"
        ),
        sa.Index("ix_provider_reconciliation_outcome", "outcome"),
    )
    op.create_table(
        "provider_credential_materials",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("material_id", UUID_TYPE, nullable=False, unique=True),
        sa.Column("credential_kind", sa.String(60), nullable=False),
        sa.Column("encrypted_reference", sa.String(240), nullable=False),
        sa.Column("fingerprint_algorithm", sa.String(40), nullable=False),
        sa.Column("fingerprint_value", sa.String(96), nullable=False),
        sa.Column("fingerprint_version", sa.Integer, nullable=False),
        sa.Column("supersedes_material_id", UUID_TYPE),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    _seed_permissions()


def downgrade() -> None:
    for table in (
        "provider_credential_materials",
        "provider_reconciliation_issues",
        "provider_operation_verifications",
        "provider_operation_attempts",
        "provider_operations",
        "provider_write_enablements",
    ):
        op.drop_table(table)
    permission_codes = tuple(code for _, code, _ in PERMISSIONS)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "delete from role_permissions where permission_id in "
            "(select id from permissions where code = any(:codes))"
        ),
        {"codes": list(permission_codes)},
    )
    conn.execute(
        sa.text("delete from permissions where code = any(:codes)"),
        {"codes": list(permission_codes)},
    )
