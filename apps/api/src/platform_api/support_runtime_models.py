"""Focused SQLAlchemy Core mappings for the existing Milestone 5-E support schema."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()
uuid = sa.Uuid(as_uuid=False)
jsonb = postgresql.JSONB(astext_type=sa.Text())

support_categories = sa.Table(
    "support_categories",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("code", sa.String(64), nullable=False),
    sa.Column("label_fa", sa.String(160), nullable=False),
    sa.Column("active", sa.Boolean(), nullable=False),
)

support_queues = sa.Table(
    "support_queues",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("code", sa.String(64), nullable=False),
    sa.Column("default_priority", sa.String(16), nullable=False),
    sa.Column("maintenance", sa.Boolean(), nullable=False),
    sa.Column("active", sa.Boolean(), nullable=False),
)

support_conversations = sa.Table(
    "support_conversations",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("reference", sa.String(32), nullable=False),
    sa.Column("requester_type", sa.String(24), nullable=False),
    sa.Column("requester_user_id", uuid, nullable=False),
    sa.Column("tenant_id", uuid),
    sa.Column("channel", sa.String(40), nullable=False),
    sa.Column("category_id", uuid, nullable=False),
    sa.Column("queue_id", uuid, nullable=False),
    sa.Column("subject", sa.String(240), nullable=False),
    sa.Column("priority", sa.String(16), nullable=False),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("sla_policy_snapshot", jsonb, nullable=False),
    sa.Column("first_response_deadline", sa.DateTime(timezone=True)),
    sa.Column("next_response_deadline", sa.DateTime(timezone=True)),
    sa.Column("resolution_deadline", sa.DateTime(timezone=True)),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("resolved_at", sa.DateTime(timezone=True)),
    sa.Column("closed_at", sa.DateTime(timezone=True)),
)

support_messages = sa.Table(
    "support_messages",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("conversation_id", uuid, nullable=False),
    sa.Column("sequence", sa.Integer(), nullable=False),
    sa.Column("sender_type", sa.String(24), nullable=False),
    sa.Column("sender_id", uuid, nullable=False),
    sa.Column("channel", sa.String(40), nullable=False),
    sa.Column("message_type", sa.String(32), nullable=False),
    sa.Column("visibility", sa.String(24), nullable=False),
    sa.Column("body", sa.Text(), nullable=False),
    sa.Column("body_sha256", sa.String(64), nullable=False),
    sa.Column("client_idempotency_key", sa.String(128), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("edited_at", sa.DateTime(timezone=True)),
    sa.Column("redacted_at", sa.DateTime(timezone=True)),
)

support_idempotency_records = sa.Table(
    "support_idempotency_records",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("scope", sa.String(64), nullable=False),
    sa.Column("key_hash", sa.String(96), nullable=False),
    sa.Column("resource_reference", sa.String(80)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
