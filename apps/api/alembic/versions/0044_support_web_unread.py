"""Baseline historical customer support replies before enabling website unread state."""

from __future__ import annotations

from alembic import op

revision: str = "0044_support_web_unread"
down_revision: str = "0043_customer_web_support"
branch_labels = None
depends_on = None

_BASELINE_ID = "md5('web-unread-baseline:' || message.id::text || ':' || conversation.requester_user_id::text)::uuid"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO support_message_deliveries (
            id,
            message_id,
            participant_type,
            participant_id,
            delivered_at,
            read_at
        )
        SELECT
            {_BASELINE_ID},
            message.id,
            'CUSTOMER',
            conversation.requester_user_id,
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM support_messages AS message
        JOIN support_conversations AS conversation
          ON conversation.id = message.conversation_id
        WHERE conversation.requester_type = 'CUSTOMER'
          AND conversation.requester_user_id IS NOT NULL
          AND message.sender_type = 'SUPPORT_AGENT'
          AND message.visibility = 'PUBLIC'
          AND message.redacted_at IS NULL
        ON CONFLICT (message_id, participant_type, participant_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM support_message_deliveries AS delivery
        USING support_messages AS message, support_conversations AS conversation
        WHERE message.id = delivery.message_id
          AND conversation.id = message.conversation_id
          AND conversation.requester_type = 'CUSTOMER'
          AND conversation.requester_user_id IS NOT NULL
          AND delivery.participant_type = 'CUSTOMER'
          AND delivery.participant_id = conversation.requester_user_id
          AND delivery.id = {_BASELINE_ID}
        """
    )
