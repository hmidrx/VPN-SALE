"""Milestone 6-A2A provider write safety gate

Revision ID: 0017_m6a2a
Revises: 0016_milestone_6a1_providers
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_m6a2a"
down_revision: str = "0016_milestone_6a1_providers"
branch_labels: None = None
depends_on: None = None

UUID_TYPE = postgresql.UUID(as_uuid=True)
PERMISSIONS = (
    (
        UUID("61a20000-0000-4000-8000-000000000001"),
        "providers.write_contracts.read",
        "Read sanitized provider write contracts",
    ),
    (
        UUID("61a20000-0000-4000-8000-000000000002"),
        "providers.write_preflight",
        "Run provider write preflight without mutation",
    ),
    (
        UUID("61a20000-0000-4000-8000-000000000003"),
        "providers.write_plans.read",
        "Read sanitized provider dry-run plans",
    ),
    (
        UUID("61a20000-0000-4000-8000-000000000004"),
        "providers.write_certification.prepare",
        "Prepare provider write certification reports",
    ),
    (
        UUID("61a20000-0000-4000-8000-000000000005"),
        "providers.write_certification.review",
        "Review provider write certification reports",
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
    op.add_column(
        "provider_definitions",
        sa.Column(
            "write_state",
            sa.String(40),
            nullable=False,
            server_default="LIVE_WRITE_CANARY_REQUIRED",
        ),
    )
    op.add_column("provider_definitions", sa.Column("write_contract_digest", sa.String(96)))
    op.execute(
        "update provider_definitions set certified_tag = 'v4.0.2', "
        "certified_commit_sha = '0b0ddaa9a5a9a3d7402f5f5a274a1a77f743d4bf', "
        "contract_digest = 'sha256:pasarguard-v4.0.2-read-write-a2a-corrected-contract', "
        "certification_status = 'CONTRACT_MISMATCH' where provider_kind = 'pasarguard'"
    )
    op.execute(
        "update provider_connection_tests set status = 'CONTRACT_MISMATCH', "
        "safe_error_code = 'pasarguard_v510_contract_invalidated' "
        "where contract_digest = 'sha256:pasarguard-v5.1.0-read-only-contract'"
    )
    op.create_table(
        "provider_operation_records",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("operation_id", UUID_TYPE, nullable=False, unique=True),
        sa.Column(
            "panel_instance_id",
            UUID_TYPE,
            sa.ForeignKey("panel_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("idempotency_scope", sa.String(160), nullable=False),
        sa.Column("remote_identity", sa.String(256)),
        sa.Column("plan_digest", sa.String(96)),
        sa.Column("safe_reasons", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "panel_instance_id", "idempotency_scope", name="uq_provider_operation_idempotency"
        ),
    )
    op.create_index(
        "ix_provider_operation_locks",
        "provider_operation_records",
        ["panel_instance_id", "remote_identity", "state"],
    )
    _seed_permissions()


def downgrade() -> None:
    op.drop_index("ix_provider_operation_locks", table_name="provider_operation_records")
    op.drop_table("provider_operation_records")
    conn = op.get_bind()
    delete_role = sa.text(
        "delete from role_permissions where permission_id = :permission_id"
    ).bindparams(sa.bindparam("permission_id", type_=UUID_TYPE))
    delete_permission = sa.text("delete from permissions where id = :permission_id").bindparams(
        sa.bindparam("permission_id", type_=UUID_TYPE)
    )
    for permission_id, _code, _description in PERMISSIONS:
        conn.execute(delete_role, {"permission_id": permission_id})
        conn.execute(delete_permission, {"permission_id": permission_id})
    op.drop_column("provider_definitions", "write_contract_digest")
    op.drop_column("provider_definitions", "write_state")
