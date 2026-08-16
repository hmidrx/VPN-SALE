"""Enqueue durable Telegram delivery for public agent image attachments."""

from __future__ import annotations

from alembic import op

revision: str = "0042_support_agent_image"
down_revision: str = "0041_support_sla_escalations"
branch_labels = None
depends_on = None


def _replace_function(message_types: str) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enqueue_support_reply_notification() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.sender_type = 'SUPPORT_AGENT'
               AND NEW.message_type IN ({message_types})
               AND NEW.visibility = 'PUBLIC' THEN
                INSERT INTO support_reply_notification_outbox (
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
        $$;
        """
    )


def upgrade() -> None:
    _replace_function("'AGENT_MESSAGE', 'AGENT_ATTACHMENT'")


def downgrade() -> None:
    _replace_function("'AGENT_MESSAGE'")
