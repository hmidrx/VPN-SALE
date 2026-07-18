"""Milestone 5-E omnichannel support platform."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_milestone_5e_support"
down_revision: str = "0013_milestone_5c_resellers"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("support.read", "Read support conversations", UUID("5e000000-0000-4000-8000-000000000001")),
    (
        "support.reply",
        "Reply to support conversations",
        UUID("5e000000-0000-4000-8000-000000000002"),
    ),
    (
        "support.assign",
        "Assign support conversations",
        UUID("5e000000-0000-4000-8000-000000000003"),
    ),
    (
        "support.manage_status",
        "Manage support statuses",
        UUID("5e000000-0000-4000-8000-000000000004"),
    ),
    (
        "support.manage_priority",
        "Manage support priorities",
        UUID("5e000000-0000-4000-8000-000000000005"),
    ),
    (
        "support.internal_notes.read",
        "Read support internal notes",
        UUID("5e000000-0000-4000-8000-000000000006"),
    ),
    (
        "support.internal_notes.manage",
        "Manage support internal notes",
        UUID("5e000000-0000-4000-8000-000000000007"),
    ),
    (
        "support.attachments.read",
        "Read support attachments",
        UUID("5e000000-0000-4000-8000-000000000008"),
    ),
    (
        "support.attachments.manage",
        "Manage support attachments",
        UUID("5e000000-0000-4000-8000-000000000009"),
    ),
    ("support.queues.read", "Read support queues", UUID("5e000000-0000-4000-8000-000000000010")),
    (
        "support.queues.manage",
        "Manage support queues",
        UUID("5e000000-0000-4000-8000-000000000011"),
    ),
    (
        "support.categories.read",
        "Read support categories",
        UUID("5e000000-0000-4000-8000-000000000012"),
    ),
    (
        "support.categories.manage",
        "Manage support categories",
        UUID("5e000000-0000-4000-8000-000000000013"),
    ),
    ("support.sla.read", "Read support SLA", UUID("5e000000-0000-4000-8000-000000000014")),
    ("support.sla.manage", "Manage support SLA", UUID("5e000000-0000-4000-8000-000000000015")),
    (
        "support.canned_responses.read",
        "Read support canned responses",
        UUID("5e000000-0000-4000-8000-000000000016"),
    ),
    (
        "support.canned_responses.manage",
        "Manage support canned responses",
        UUID("5e000000-0000-4000-8000-000000000017"),
    ),
    ("support.macros.read", "Read support macros", UUID("5e000000-0000-4000-8000-000000000018")),
    (
        "support.macros.manage",
        "Manage support macros",
        UUID("5e000000-0000-4000-8000-000000000019"),
    ),
    (
        "support.merge",
        "Merge duplicate support conversations",
        UUID("5e000000-0000-4000-8000-000000000020"),
    ),
    (
        "support.escalate",
        "Escalate support conversations",
        UUID("5e000000-0000-4000-8000-000000000021"),
    ),
    ("support.csat.read", "Read support CSAT", UUID("5e000000-0000-4000-8000-000000000022")),
    (
        "support.telegram_bridge.manage",
        "Manage Telegram support bridge",
        UUID("5e000000-0000-4000-8000-000000000023"),
    ),
    (
        "support.reporting.read",
        "Read support reporting",
        UUID("5e000000-0000-4000-8000-000000000024"),
    ),
)


def _seed_permissions() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    permissions = sa.table(
        "permissions",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    grant = sa.text(
        "insert into role_permissions (role_id, permission_id) "
        "select roles.id, :permission_id from roles "
        "where machine_name = 'super_admin' on conflict do nothing"
    ).bindparams(sa.bindparam("permission_id", type_=uuid))
    for code, description, permission_id in PERMISSIONS:
        op.get_bind().execute(
            sa.dialects.postgresql.insert(permissions)
            .values(id=permission_id, code=code, description=description)
            .on_conflict_do_update(
                index_elements=[permissions.c.code], set_={"description": description}
            )
        )
        op.get_bind().execute(grant, {"permission_id": permission_id})


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "support_categories",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("parent_id", uuid, sa.ForeignKey("support_categories.id", ondelete="RESTRICT")),
        sa.Column("label_fa", sa.String(160), nullable=False),
        sa.Column("label_en", sa.String(160)),
        sa.Column("routing_code", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("code", name="uq_support_categories_code"),
    )
    op.create_table(
        "support_business_calendars",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("weekdays", jsonb, nullable=False),
        sa.Column("holidays", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("emergency_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("code", name="uq_support_business_calendars_code"),
    )
    op.create_table(
        "support_sla_policies",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column(
            "calendar_id",
            uuid,
            sa.ForeignKey("support_business_calendars.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("first_response_minutes", sa.Integer(), nullable=False),
        sa.Column("next_response_minutes", sa.Integer(), nullable=False),
        sa.Column("resolution_minutes", sa.Integer(), nullable=False),
        sa.Column("pause_on_customer_wait", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "first_response_minutes > 0 and next_response_minutes > 0 and resolution_minutes > 0",
            name="ck_support_sla_positive",
        ),
        sa.UniqueConstraint("code", "version", name="uq_support_sla_policy_code_version"),
    )
    op.create_table(
        "support_teams",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("code", name="uq_support_teams_code"),
    )
    op.create_table(
        "support_queues",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("team_id", uuid, sa.ForeignKey("support_teams.id", ondelete="RESTRICT")),
        sa.Column(
            "sla_policy_id", uuid, sa.ForeignKey("support_sla_policies.id", ondelete="RESTRICT")
        ),
        sa.Column("allowed_requester_types", jsonb, nullable=False),
        sa.Column("supported_channels", jsonb, nullable=False),
        sa.Column("default_priority", sa.String(16), nullable=False),
        sa.Column("assignment_strategy", sa.String(32), nullable=False),
        sa.Column("maintenance", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("code", name="uq_support_queues_code"),
    )
    op.create_table(
        "support_conversations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(32), nullable=False),
        sa.Column("requester_type", sa.String(24), nullable=False),
        sa.Column("requester_user_id", uuid, nullable=False),
        sa.Column("tenant_id", uuid),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column(
            "category_id",
            uuid,
            sa.ForeignKey("support_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "queue_id",
            uuid,
            sa.ForeignKey("support_queues.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(240), nullable=False),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assigned_team_id", uuid, sa.ForeignKey("support_teams.id", ondelete="RESTRICT")),
        sa.Column("assigned_agent_id", uuid, sa.ForeignKey("admins.id", ondelete="RESTRICT")),
        sa.Column("related_order_reference", sa.String(64)),
        sa.Column("related_invoice_reference", sa.String(64)),
        sa.Column("related_payment_reference", sa.String(64)),
        sa.Column("related_wallet_transaction_reference", sa.String(64)),
        sa.Column(
            "sla_policy_snapshot", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("first_response_deadline", sa.DateTime(timezone=True)),
        sa.Column("next_response_deadline", sa.DateTime(timezone=True)),
        sa.Column("resolution_deadline", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("reference", name="uq_support_conversations_reference"),
    )
    op.create_index(
        "ix_support_conversations_requester",
        "support_conversations",
        ["requester_type", "requester_user_id", "tenant_id"],
    )
    op.create_index(
        "ix_support_conversations_queue_status_sla",
        "support_conversations",
        ["queue_id", "status", "first_response_deadline", "resolution_deadline"],
    )
    op.create_table(
        "support_messages",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("sender_type", sa.String(24), nullable=False),
        sa.Column("sender_id", uuid, nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("message_type", sa.String(32), nullable=False),
        sa.Column("visibility", sa.String(24), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("client_idempotency_key", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("redacted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("conversation_id", "sequence", name="uq_support_messages_sequence"),
        sa.UniqueConstraint(
            "conversation_id", "client_idempotency_key", name="uq_support_messages_idempotency"
        ),
    )
    op.create_table(
        "support_message_revisions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "message_id",
            uuid,
            sa.ForeignKey("support_messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("previous_body_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("message_id", "revision", name="uq_support_message_revisions_revision"),
    )
    op.create_table(
        "support_message_deliveries",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "message_id",
            uuid,
            sa.ForeignKey("support_messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("participant_type", sa.String(24), nullable=False),
        sa.Column("participant_id", uuid, nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "message_id",
            "participant_type",
            "participant_id",
            name="uq_support_message_deliveries_participant",
        ),
    )
    op.create_table(
        "support_assignments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_agent_id", uuid),
        sa.Column("to_agent_id", uuid),
        sa.Column("from_queue_id", uuid),
        sa.Column("to_queue_id", uuid),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "support_status_history",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(32), nullable=False),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "support_attachments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("message_id", uuid, sa.ForeignKey("support_messages.id", ondelete="RESTRICT")),
        sa.Column("asset_reference", sa.String(64), nullable=False),
        sa.Column("normalized_filename", sa.String(180), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("asset_reference", name="uq_support_attachments_asset_reference"),
    )
    op.create_table(
        "support_canned_responses",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False),
        sa.Column("queue_id", uuid),
        sa.Column("category_id", uuid),
        sa.Column("placeholders", jsonb, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("code", "locale", "version", name="uq_support_canned_response_version"),
    )
    op.create_table(
        "support_macros",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("actions", jsonb, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("code", "version", name="uq_support_macros_version"),
    )
    op.create_table(
        "support_tags",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.UniqueConstraint("code", name="uq_support_tags_code"),
    )
    op.create_table(
        "support_merges",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "primary_conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "secondary_conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_by", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("secondary_conversation_id", name="uq_support_merges_secondary"),
    )
    op.create_table(
        "support_csat",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resolution_cycle", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("feedback", sa.String(800)),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("score between 1 and 5", name="ck_support_csat_score"),
        sa.UniqueConstraint("conversation_id", "resolution_cycle", name="uq_support_csat_cycle"),
    )
    op.create_table(
        "support_telegram_mappings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "telegram_account_id", uuid, sa.ForeignKey("telegram_accounts.id", ondelete="RESTRICT")
        ),
        sa.Column("bridge_kind", sa.String(32), nullable=False),
        sa.Column("chat_id_hash", sa.String(96)),
        sa.Column("thread_id", sa.BigInteger()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "conversation_id", "bridge_kind", name="uq_support_telegram_mapping_kind"
        ),
    )
    op.create_table(
        "support_idempotency_records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(96), nullable=False),
        sa.Column("resource_reference", sa.String(80)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("scope", "key_hash", name="uq_support_idempotency_scope_key"),
    )
    op.create_table(
        "support_notifications",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "conversation_id", uuid, sa.ForeignKey("support_conversations.id", ondelete="RESTRICT")
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("safe_payload", jsonb, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    _seed_permissions()


def downgrade() -> None:
    for table in (
        "support_notifications",
        "support_idempotency_records",
        "support_telegram_mappings",
        "support_csat",
        "support_merges",
        "support_tags",
        "support_macros",
        "support_canned_responses",
        "support_attachments",
        "support_status_history",
        "support_assignments",
        "support_message_deliveries",
        "support_message_revisions",
        "support_messages",
        "support_conversations",
        "support_queues",
        "support_teams",
        "support_sla_policies",
        "support_business_calendars",
        "support_categories",
    ):
        op.drop_table(table)
    codes = [code for code, _, _ in PERMISSIONS]
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "delete from role_permissions where permission_id in "
            "(select id from permissions where code = any(:codes))"
        ).bindparams(sa.bindparam("codes", type_=postgresql.ARRAY(sa.String()))),
        {"codes": codes},
    )
    bind.execute(
        sa.text("delete from permissions where code = any(:codes)").bindparams(
            sa.bindparam("codes", type_=postgresql.ARRAY(sa.String()))
        ),
        {"codes": codes},
    )
