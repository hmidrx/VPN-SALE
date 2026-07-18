"""Milestone 5-F knowledge and status platform."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_milestone_5f_knowledge"
down_revision: str = "0014_milestone_5e_support"
branch_labels = None
depends_on = None

PERMISSIONS = (
    (
        "knowledge.read",
        "Read knowledge administration",
        UUID("5f000000-0000-4000-8000-000000000001"),
    ),
    ("knowledge.manage", "Manage knowledge drafts", UUID("5f000000-0000-4000-8000-000000000002")),
    ("knowledge.preview", "Preview knowledge drafts", UUID("5f000000-0000-4000-8000-000000000003")),
    (
        "knowledge.publish",
        "Publish knowledge content",
        UUID("5f000000-0000-4000-8000-000000000004"),
    ),
    (
        "knowledge.rollback",
        "Rollback knowledge content",
        UUID("5f000000-0000-4000-8000-000000000005"),
    ),
    (
        "knowledge.categories.manage",
        "Manage knowledge categories",
        UUID("5f000000-0000-4000-8000-000000000006"),
    ),
    ("knowledge.faq.manage", "Manage knowledge FAQ", UUID("5f000000-0000-4000-8000-000000000007")),
    (
        "knowledge.troubleshooting.manage",
        "Manage troubleshooting flows",
        UUID("5f000000-0000-4000-8000-000000000008"),
    ),
    (
        "knowledge.media.read",
        "Read educational media",
        UUID("5f000000-0000-4000-8000-000000000009"),
    ),
    (
        "knowledge.media.manage",
        "Manage educational media",
        UUID("5f000000-0000-4000-8000-000000000010"),
    ),
    (
        "knowledge.feedback.read",
        "Read article feedback",
        UUID("5f000000-0000-4000-8000-000000000011"),
    ),
    (
        "knowledge.feedback.manage",
        "Moderate article feedback",
        UUID("5f000000-0000-4000-8000-000000000012"),
    ),
    ("status.read", "Read status administration", UUID("5f000000-0000-4000-8000-000000000013")),
    (
        "status.manage_components",
        "Manage status components",
        UUID("5f000000-0000-4000-8000-000000000014"),
    ),
    ("status.manage_incidents", "Manage incidents", UUID("5f000000-0000-4000-8000-000000000015")),
    (
        "status.publish_updates",
        "Publish incident updates",
        UUID("5f000000-0000-4000-8000-000000000016"),
    ),
    (
        "status.manage_maintenance",
        "Manage scheduled maintenance",
        UUID("5f000000-0000-4000-8000-000000000017"),
    ),
    (
        "status.notifications.read",
        "Read status notification delivery",
        UUID("5f000000-0000-4000-8000-000000000018"),
    ),
)


def upgrade() -> None:
    op.create_table(
        "knowledge_spaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("localized_name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "knowledge_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_spaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("localized_name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("space_id", "code", name="uq_knowledge_categories_space_code"),
    )
    op.create_table(
        "knowledge_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("article_code", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_categories.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("current_published_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "educational_media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_ref", sa.Text(), nullable=False, unique=True),
        sa.Column("content_digest", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("storage_ref", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "knowledge_article_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("optimistic_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "article_id", "version_number", name="uq_knowledge_article_version_number"
        ),
    )
    op.create_table(
        "knowledge_content_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_article_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("block_type", sa.Text(), nullable=False),
        sa.Column("block_order", sa.Integer(), nullable=False),
        sa.Column("localized_content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "media_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("educational_media_assets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("target_ref", sa.Text(), nullable=True),
    )
    op.create_table(
        "knowledge_preview_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_article_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "troubleshooting_flows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_article_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )
    op.create_table(
        "article_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("knowledge_article_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_key_hash", sa.Text(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.UniqueConstraint(
            "version_id", "actor_key_hash", name="uq_article_feedback_actor_version"
        ),
    )
    op.create_table(
        "status_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False, unique=True),
        sa.Column("localized_name", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="UNKNOWN"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "status_incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_ref", sa.Text(), nullable=False, unique=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("title", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "status_incident_updates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "incident_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("status_incidents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("public_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scheduled_maintenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("public_ref", sa.Text(), nullable=False, unique=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("title", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("planned_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("planned_end", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "status_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_key", sa.Text(), nullable=False, unique=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("delivery_state", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_knowledge_versions_public_search",
        "knowledge_article_versions",
        ["state", "audience", "published_at"],
    )
    op.create_index(
        "ix_knowledge_versions_search_text", "knowledge_article_versions", ["search_text"]
    )
    bind = op.get_bind()
    for code, description, permission_id in PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (id, code, description) VALUES "
                "(:id, :code, :description) ON CONFLICT (code) DO NOTHING"
            ).bindparams(sa.bindparam("id", type_=postgresql.UUID(as_uuid=True))),
            {"id": permission_id, "code": code, "description": description},
        )


def downgrade() -> None:
    for table in (
        "status_notifications",
        "scheduled_maintenance",
        "status_incident_updates",
        "status_incidents",
        "status_components",
        "article_feedback",
        "troubleshooting_flows",
        "knowledge_preview_sessions",
        "knowledge_content_blocks",
        "knowledge_article_versions",
        "educational_media_assets",
        "knowledge_articles",
        "knowledge_categories",
        "knowledge_spaces",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for code, _, _ in PERMISSIONS:
        bind.execute(sa.text("DELETE FROM permissions WHERE code = :code"), {"code": code})
