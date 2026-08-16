"""SQLAlchemy Core mappings for support SLA escalation and manager notifications."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

metadata = sa.MetaData()
uuid = sa.Uuid(as_uuid=False)
jsonb = postgresql.JSONB(astext_type=sa.Text())

support_sla_escalations = sa.Table(
    "support_sla_escalations",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("reference", sa.String(64), nullable=False),
    sa.Column("conversation_id", uuid, nullable=False),
    sa.Column("kind", sa.String(24), nullable=False),
    sa.Column("phase", sa.String(16), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("deadline_at", sa.DateTime(timezone=True)),
    sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_by", uuid),
    sa.Column("acknowledged_by", uuid),
    sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)

support_notifications = sa.Table(
    "support_notifications",
    metadata,
    sa.Column("id", uuid, primary_key=True),
    sa.Column("conversation_id", uuid),
    sa.Column("event_type", sa.String(64), nullable=False),
    sa.Column("channel", sa.String(40), nullable=False),
    sa.Column("safe_payload", jsonb, nullable=False),
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("attempt_count", sa.Integer(), nullable=False),
    sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
