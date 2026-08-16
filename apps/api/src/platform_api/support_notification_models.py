"""SQLAlchemy Core mapping for durable support reply notification delivery."""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()
uuid = sa.Uuid(as_uuid=False)

support_reply_notification_outbox = sa.Table(
    "support_reply_notification_outbox",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("event_reference", sa.String(64), nullable=False),
    sa.Column("conversation_id", uuid, nullable=False),
    sa.Column("message_id", uuid, nullable=False),
    sa.Column("customer_id", uuid, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("attempts", sa.Integer(), nullable=False),
    sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("processing_started_at", sa.DateTime(timezone=True)),
    sa.Column("sent_at", sa.DateTime(timezone=True)),
    sa.Column("last_error_category", sa.String(64)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
