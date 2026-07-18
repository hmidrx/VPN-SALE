"""Milestone 6-B2 configuration delivery platform

Revision ID: 0020_m6b2_delivery
Revises: 0019_m6b1_services
Create Date: 2026-07-18
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_m6b2_delivery"
down_revision: str = "0019_m6b1_services"
branch_labels: None = None
depends_on: None = None

UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)

PERMISSIONS = (
    (
        UUID("62b20000-0000-4000-8000-000000000001"),
        "delivery_profiles.read",
        "Read delivery profiles",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000002"),
        "delivery_profiles.manage",
        "Manage delivery profile drafts",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000003"),
        "delivery_profiles.publish",
        "Publish delivery profiles",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000004"),
        "delivery_profiles.rollback",
        "Rollback delivery profiles",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000005"),
        "delivery_profiles.preview",
        "Preview delivery profiles",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000006"),
        "delivery_compatibility.read",
        "Read delivery compatibility",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000007"),
        "service_delivery.read",
        "Read service delivery metadata",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000008"),
        "service_delivery.read_credentials",
        "Reveal service delivery credentials",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000009"),
        "service_delivery.refresh",
        "Refresh delivery revisions",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000010"),
        "subscriptions.read",
        "Read subscription metadata",
    ),
    (UUID("62b20000-0000-4000-8000-000000000011"), "subscriptions.manage", "Manage subscriptions"),
    (
        UUID("62b20000-0000-4000-8000-000000000012"),
        "subscriptions.rotate",
        "Rotate subscription tokens",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000013"),
        "subscriptions.revoke",
        "Revoke subscription tokens",
    ),
    (
        UUID("62b20000-0000-4000-8000-000000000014"),
        "delivery_access_events.read",
        "Read delivery access events",
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
        "delivery_profiles",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("public_reference", sa.String(48), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("current_version_id", UUID_T),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("public_reference", name="uq_delivery_profiles_public_reference"),
    )
    op.create_index(
        "ix_delivery_profiles_status_updated", "delivery_profiles", ["status", "updated_at"]
    )
    op.create_table(
        "delivery_profile_versions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "profile_id",
            UUID_T,
            sa.ForeignKey("delivery_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("protocol", sa.String(32), nullable=False),
        sa.Column("transport", sa.String(32), nullable=False),
        sa.Column("security", sa.String(32), nullable=False),
        sa.Column("address_source", sa.String(48), nullable=False),
        sa.Column("public_address", sa.String(255), nullable=False),
        sa.Column("public_port", sa.Integer(), nullable=False),
        sa.Column("display_location", sa.String(120), nullable=False),
        sa.Column("remark_template", sa.String(160), nullable=False),
        sa.Column("tls_settings", JSONB),
        sa.Column("reality_settings", JSONB),
        sa.Column("transport_settings", JSONB, nullable=False),
        sa.Column("protocol_settings", JSONB, nullable=False),
        sa.Column("compatibility_tags", JSONB, nullable=False),
        sa.Column("validation_errors", JSONB, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "public_port between 1 and 65535", name="ck_delivery_profile_versions_port"
        ),
        sa.UniqueConstraint(
            "profile_id", "version_number", name="uq_delivery_profile_versions_number"
        ),
    )
    op.create_index(
        "ix_delivery_profile_versions_status", "delivery_profile_versions", ["status", "created_at"]
    )
    op.create_table(
        "delivery_profile_assignments",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "profile_version_id",
            UUID_T,
            sa.ForeignKey("delivery_profile_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(48), nullable=False),
        sa.Column("target_value", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "target_type", "target_value", "active", name="uq_delivery_assignments_active_target"
        ),
    )
    op.create_index(
        "ix_delivery_assignments_profile", "delivery_profile_assignments", ["profile_version_id"]
    )
    op.create_table(
        "delivery_renderer_versions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("format_code", sa.String(48), nullable=False),
        sa.Column("renderer_version", sa.String(80), nullable=False),
        sa.Column("contract_source", sa.String(240), nullable=False),
        sa.Column("supported_matrix", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "format_code", "renderer_version", name="uq_delivery_renderer_versions"
        ),
    )
    op.create_table(
        "delivery_revisions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attachment_snapshot", JSONB, nullable=False),
        sa.Column("renderer_versions", JSONB, nullable=False),
        sa.Column("credential_fingerprints", JSONB, nullable=False),
        sa.Column("compatibility_state", JSONB, nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("correlation_reference", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "service_id", "revision_number", name="uq_delivery_revisions_service_number"
        ),
    )
    op.create_index(
        "ix_delivery_revisions_service_created", "delivery_revisions", ["service_id", "created_at"]
    )
    op.create_table(
        "delivery_subscriptions",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column("public_reference", sa.String(48), nullable=False),
        sa.Column(
            "service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("active_token_hash", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("public_reference", name="uq_delivery_subscriptions_public_reference"),
        sa.UniqueConstraint("service_id", "scope", name="uq_delivery_subscriptions_service_scope"),
    )
    op.create_index(
        "ix_delivery_subscriptions_token_hash", "delivery_subscriptions", ["active_token_hash"]
    )
    op.create_table(
        "delivery_subscription_tokens",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "subscription_id",
            UUID_T,
            sa.ForeignKey("delivery_subscriptions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(96), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("grace_expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash", name="uq_delivery_subscription_tokens_hash"),
    )
    op.create_index(
        "ix_delivery_subscription_tokens_status",
        "delivery_subscription_tokens",
        ["status", "issued_at"],
    )
    op.create_table(
        "delivery_access_events",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "subscription_id",
            UUID_T,
            sa.ForeignKey("delivery_subscriptions.id", ondelete="RESTRICT"),
        ),
        sa.Column("service_id", UUID_T, sa.ForeignKey("services.id", ondelete="RESTRICT")),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("safe_metadata", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_delivery_access_events_service_created",
        "delivery_access_events",
        ["service_id", "created_at"],
    )
    op.create_index(
        "ix_delivery_access_events_action_outcome", "delivery_access_events", ["action", "outcome"]
    )


def downgrade() -> None:
    op.drop_index("ix_delivery_access_events_action_outcome", table_name="delivery_access_events")
    op.drop_index("ix_delivery_access_events_service_created", table_name="delivery_access_events")
    op.drop_table("delivery_access_events")
    op.drop_index(
        "ix_delivery_subscription_tokens_status", table_name="delivery_subscription_tokens"
    )
    op.drop_table("delivery_subscription_tokens")
    op.drop_index("ix_delivery_subscriptions_token_hash", table_name="delivery_subscriptions")
    op.drop_table("delivery_subscriptions")
    op.drop_index("ix_delivery_revisions_service_created", table_name="delivery_revisions")
    op.drop_table("delivery_revisions")
    op.drop_table("delivery_renderer_versions")
    op.drop_index("ix_delivery_assignments_profile", table_name="delivery_profile_assignments")
    op.drop_table("delivery_profile_assignments")
    op.drop_index("ix_delivery_profile_versions_status", table_name="delivery_profile_versions")
    op.drop_table("delivery_profile_versions")
    op.drop_index("ix_delivery_profiles_status_updated", table_name="delivery_profiles")
    op.drop_table("delivery_profiles")
