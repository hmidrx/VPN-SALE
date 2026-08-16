"""Add an atomic, payload-free outbox for customer support reply notifications."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040_support_reply_notifications"
down_revision: str = "0039_telegram_native_support"
branch_labels = None
depends_on = None

TABLE = "support_reply_notification_outbox"
TRIGGER = "trg_support_reply_notification_outbox"
FUNCTION = "enqueue_support_reply_notification"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        TABLE,
        sa.Column("id", uuid, primary_key=True),
        sa.Column("event_reference", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            uuid,
            sa.ForeignKey("support_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_category", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_reference", name="uq_support_reply_notification_event_ref"),
        sa.UniqueConstraint("message_id", name="uq_support_reply_notification_message"),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SENT','SKIPPED','FAILED')",
            name="ck_support_reply_notification_status",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_support_reply_notification_attempts"),
    )
    op.create_index(
        "ix_support_reply_notification_claim",
        TABLE,
        ["status", "available_at"],
    )
    op.create_index(
        "ix_support_reply_notification_conversation",
        TABLE,
        ["conversation_id"],
    )

    # Keep enqueue atomic with the durable support message insert.  The outbox stores
    # identifiers only; customer-visible text remains in support_messages and is read
    # only when the worker is ready to deliver.
    op.execute(
        f"""
        CREATE FUNCTION {FUNCTION}() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.sender_type = 'SUPPORT_AGENT'
               AND NEW.message_type = 'AGENT_MESSAGE'
               AND NEW.visibility = 'PUBLIC' THEN
                INSERT INTO {TABLE} (
                    id,
                    event_reference,
                    conversation_id,
                    message_id,
                    customer_id,
                    status,
                    attempts,
                    available_at,
                    processing_started_at,
                    sent_at,
                    last_error_category,
                    created_at
                )
                SELECT
                    NEW.id,
                    'SRN-' || replace(NEW.id::text, '-', ''),
                    NEW.conversation_id,
                    NEW.id,
                    conversation.requester_user_id,
                    'PENDING',
                    0,
                    CURRENT_TIMESTAMP,
                    NULL,
                    NULL,
                    NULL,
                    CURRENT_TIMESTAMP
                FROM support_conversations AS conversation
                WHERE conversation.id = NEW.conversation_id
                  AND conversation.requester_type = 'CUSTOMER'
                ON CONFLICT (message_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER}
        AFTER INSERT ON support_messages
        FOR EACH ROW
        EXECUTE FUNCTION {FUNCTION}()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON support_messages")
    op.execute(f"DROP FUNCTION IF EXISTS {FUNCTION}()")
    op.drop_index("ix_support_reply_notification_conversation", table_name=TABLE)
    op.drop_index("ix_support_reply_notification_claim", table_name=TABLE)
    op.drop_table(TABLE)
