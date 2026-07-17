"""Milestone 5-A configuration and branding platform."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_milestone_5a_config"
down_revision: str = "0010_milestone_4a2b2_recovery"
branch_labels = None
depends_on = None

PERMISSIONS = (
    (
        "configuration.read",
        "Read configuration center",
        UUID("5a000000-0000-4000-8000-000000000001"),
    ),
    (
        "configuration.manage",
        "Manage configuration drafts",
        UUID("5a000000-0000-4000-8000-000000000002"),
    ),
    (
        "configuration.preview",
        "Create configuration previews",
        UUID("5a000000-0000-4000-8000-000000000003"),
    ),
    (
        "configuration.publish",
        "Publish configuration releases",
        UUID("5a000000-0000-4000-8000-000000000004"),
    ),
    (
        "configuration.schedule",
        "Schedule configuration releases",
        UUID("5a000000-0000-4000-8000-000000000005"),
    ),
    (
        "configuration.rollback",
        "Rollback configuration releases",
        UUID("5a000000-0000-4000-8000-000000000006"),
    ),
    ("branding.read", "Read branding", UUID("5a000000-0000-4000-8000-000000000007")),
    ("branding.manage", "Manage branding", UUID("5a000000-0000-4000-8000-000000000008")),
    ("themes.read", "Read themes", UUID("5a000000-0000-4000-8000-000000000009")),
    ("themes.manage", "Manage themes", UUID("5a000000-0000-4000-8000-000000000010")),
    (
        "content_templates.read",
        "Read content templates",
        UUID("5a000000-0000-4000-8000-000000000011"),
    ),
    (
        "content_templates.manage",
        "Manage content templates",
        UUID("5a000000-0000-4000-8000-000000000012"),
    ),
    ("feature_flags.read", "Read feature flags", UUID("5a000000-0000-4000-8000-000000000013")),
    ("feature_flags.manage", "Manage feature flags", UUID("5a000000-0000-4000-8000-000000000014")),
    ("navigation.read", "Read navigation", UUID("5a000000-0000-4000-8000-000000000015")),
    ("navigation.manage", "Manage navigation", UUID("5a000000-0000-4000-8000-000000000016")),
    ("telegram_menus.read", "Read Telegram menus", UUID("5a000000-0000-4000-8000-000000000017")),
    (
        "telegram_menus.manage",
        "Manage Telegram menus",
        UUID("5a000000-0000-4000-8000-000000000018"),
    ),
    ("media_assets.read", "Read media assets", UUID("5a000000-0000-4000-8000-000000000019")),
    ("media_assets.manage", "Manage media assets", UUID("5a000000-0000-4000-8000-000000000020")),
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "configuration_definitions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("namespace", sa.String(48), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "namespace", "code", "schema_version", name="uq_config_definitions_code_version"
        ),
    )
    op.create_table(
        "configuration_drafts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False, server_default="global"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("snapshot", jsonb, nullable=False),
        sa.Column("created_by_admin_id", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_configuration_drafts_version"),
        sa.UniqueConstraint("reference", name="uq_configuration_drafts_reference"),
    )
    op.create_index("ix_configuration_drafts_status", "configuration_drafts", ["status"])
    op.create_table(
        "configuration_releases",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False, server_default="global"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("immutable_snapshot", jsonb, nullable=False),
        sa.Column("draft_id", uuid, sa.ForeignKey("configuration_drafts.id", ondelete="RESTRICT")),
        sa.Column("published_by_admin_id", uuid),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column(
            "superseded_by_release_id",
            uuid,
            sa.ForeignKey("configuration_releases.id", ondelete="RESTRICT"),
        ),
        sa.Column("is_effective", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_configuration_releases_reference"),
        sa.UniqueConstraint("scope", "version", name="uq_configuration_releases_scope_version"),
    )
    op.create_index(
        "uq_configuration_one_effective",
        "configuration_releases",
        ["scope"],
        unique=True,
        postgresql_where=sa.text("is_effective"),
    )
    op.create_index(
        "ix_configuration_releases_status_dates",
        "configuration_releases",
        ["status", "scheduled_for", "published_at"],
    )
    op.create_table(
        "configuration_release_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "release_id",
            uuid,
            sa.ForeignKey("configuration_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(48), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payload", jsonb, nullable=False),
        sa.UniqueConstraint(
            "release_id", "namespace", name="uq_configuration_release_items_namespace"
        ),
    )
    op.create_table(
        "configuration_validation_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "draft_id",
            uuid,
            sa.ForeignKey("configuration_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("issues", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "configuration_preview_sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("opaque_reference_hash", sa.String(96), nullable=False),
        sa.Column(
            "draft_id",
            uuid,
            sa.ForeignKey("configuration_drafts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("created_by_admin_id", uuid, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("opaque_reference_hash", name="uq_configuration_preview_hash"),
    )
    op.create_table(
        "runtime_configuration_snapshots",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "release_id",
            uuid,
            sa.ForeignKey("configuration_releases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(96), nullable=False),
        sa.Column("public_snapshot", jsonb, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "media_assets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("public_reference", sa.String(64), nullable=False),
        sa.Column("role", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("digest", sa.String(96), nullable=False),
        sa.Column("alt_text", sa.String(240)),
        sa.Column("storage_key", sa.String(180), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("public_reference", name="uq_media_assets_public_reference"),
        sa.UniqueConstraint("digest", "role", name="uq_media_assets_digest_role"),
    )
    op.create_index("ix_media_assets_status_role", "media_assets", ["status", "role"])
    for code, desc, pid in PERMISSIONS:
        op.execute(
            sa.text(
                "insert into permissions (id, code, description) values "
                "(:id, :code, :description) on conflict (code) do update set "
                "description = excluded.description"
            ).bindparams(id=pid, code=code, description=desc)
        )
        op.execute(
            sa.text(
                "insert into role_permissions (role_id, permission_id) "
                "select r.id, p.id from roles r join permissions p on p.code=:code "
                "where r.machine_name='super_admin' on conflict do nothing"
            ).bindparams(code=code)
        )


def downgrade() -> None:
    for code, _, _ in reversed(PERMISSIONS):
        op.execute(
            sa.text(
                "delete from role_permissions where permission_id in "
                "(select id from permissions where code=:code)"
            ).bindparams(code=code)
        )
        op.execute(sa.text("delete from permissions where code=:code").bindparams(code=code))
    op.drop_index("ix_media_assets_status_role", table_name="media_assets")
    op.drop_table("media_assets")
    op.drop_table("runtime_configuration_snapshots")
    op.drop_table("configuration_preview_sessions")
    op.drop_table("configuration_validation_runs")
    op.drop_table("configuration_release_items")
    op.drop_index("ix_configuration_releases_status_dates", table_name="configuration_releases")
    op.drop_index("uq_configuration_one_effective", table_name="configuration_releases")
    op.drop_table("configuration_releases")
    op.drop_index("ix_configuration_drafts_status", table_name="configuration_drafts")
    op.drop_table("configuration_drafts")
    op.drop_table("configuration_definitions")
