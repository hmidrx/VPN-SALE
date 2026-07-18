"""Milestone 6-A1 provider core read-only inventory

Revision ID: 0016_milestone_6a1_providers
Revises: 0015_milestone_5f_knowledge
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_milestone_6a1_providers"
down_revision: str = "0015_milestone_5f_knowledge"
branch_labels: None = None
depends_on: None = None

UUID_TYPE = postgresql.UUID(as_uuid=True)
PERMISSIONS = (
    (
        UUID("61a10000-0000-4000-8000-000000000001"),
        "providers.read",
        "Read provider panel metadata",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000002"),
        "providers.manage",
        "Manage provider panel drafts and policies",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000003"),
        "providers.manage_credentials",
        "Replace provider credentials one-way",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000004"),
        "providers.test_connection",
        "Run sanitized provider connection tests",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000005"),
        "providers.sync",
        "Run read-only provider inventory synchronization",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000006"),
        "providers.read_inventory",
        "Read normalized provider inventory",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000007"),
        "providers.read_diagnostics",
        "Read sanitized provider diagnostics",
    ),
    (
        UUID("61a10000-0000-4000-8000-000000000008"),
        "providers.certify",
        "Run explicit live provider certification",
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
        "provider_definitions",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("provider_kind", sa.String(64), nullable=False, unique=True),
        sa.Column("adapter_code", sa.String(96), nullable=False),
        sa.Column("certified_tag", sa.String(32), nullable=False),
        sa.Column("certified_commit_sha", sa.String(64), nullable=False),
        sa.Column("contract_digest", sa.String(96), nullable=False),
        sa.Column("certification_status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "panel_instances",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("public_reference", sa.String(48), nullable=False, unique=True),
        sa.Column("provider_kind", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("endpoint_origin", sa.String(512), nullable=False),
        sa.Column("base_path", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("tls_policy", postgresql.JSONB, nullable=False),
        sa.Column("endpoint_policy", postgresql.JSONB, nullable=False),
        sa.Column("optimistic_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "panel_credentials",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "panel_instance_id",
            UUID_TYPE,
            sa.ForeignKey("panel_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_kind", sa.String(40), nullable=False),
        sa.Column("key_version", sa.String(32), nullable=False),
        sa.Column("nonce_b64", sa.String(64), nullable=False),
        sa.Column("ciphertext_b64", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_table(
        "provider_connection_tests",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "panel_instance_id",
            UUID_TYPE,
            sa.ForeignKey("panel_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("detected_version", sa.String(64)),
        sa.Column("contract_digest", sa.String(96)),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("safe_error_code", sa.String(64)),
        sa.Column(
            "tested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_table(
        "provider_sync_runs",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("sync_reference", sa.String(48), nullable=False, unique=True),
        sa.Column(
            "panel_instance_id",
            UUID_TYPE,
            sa.ForeignKey("panel_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("adapter_code", sa.String(96), nullable=False),
        sa.Column("adapter_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for table in (
        "provider_node_snapshots",
        "provider_inbound_snapshots",
        "provider_client_snapshots",
        "provider_host_snapshots",
        "provider_drift_issues",
        "provider_health_checks",
    ):
        op.create_table(
            table,
            sa.Column("id", UUID_TYPE, primary_key=True),
            sa.Column(
                "panel_instance_id",
                UUID_TYPE,
                sa.ForeignKey("panel_instances.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "sync_run_id", UUID_TYPE, sa.ForeignKey("provider_sync_runs.id", ondelete="CASCADE")
            ),
            sa.Column("remote_identifier", sa.String(256)),
            sa.Column("status", sa.String(64)),
            sa.Column("sanitized_payload", postgresql.JSONB, nullable=False),
            sa.Column(
                "observed_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(f"ix_{table}_panel_status", table, ["panel_instance_id", "status"])
    op.create_index(
        "ix_panel_instances_provider_status", "panel_instances", ["provider_kind", "status"]
    )
    op.create_index(
        "ix_provider_sync_runs_panel_status", "provider_sync_runs", ["panel_instance_id", "status"]
    )
    _seed_permissions()


def downgrade() -> None:
    for table in (
        "provider_health_checks",
        "provider_drift_issues",
        "provider_host_snapshots",
        "provider_client_snapshots",
        "provider_inbound_snapshots",
        "provider_node_snapshots",
    ):
        op.drop_table(table)
    op.drop_table("provider_sync_runs")
    op.drop_table("provider_connection_tests")
    op.drop_table("panel_credentials")
    op.drop_table("panel_instances")
    op.drop_table("provider_definitions")
    op.execute(
        sa.text(
            "delete from role_permissions where permission_id in "
            "(select id from permissions where code like 'providers.%')"
        )
    )
    op.execute(sa.text("delete from permissions where code like 'providers.%'"))
