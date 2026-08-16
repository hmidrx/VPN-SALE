"""Enable the durable customer-support queue for authenticated customer web traffic."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0043_customer_web_support"
down_revision: str = "0042_support_agent_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE support_queues
            SET supported_channels = CASE
                    WHEN supported_channels @> '["CUSTOMER_WEB"]'::jsonb
                        THEN supported_channels
                    ELSE supported_channels || '["CUSTOMER_WEB"]'::jsonb
                END,
                version = version + 1
            WHERE code = 'telegram_customer'
            """
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("durable customer support queue seed is unavailable")


def downgrade() -> None:
    result = op.get_bind().execute(
        sa.text(
            """
            UPDATE support_queues
            SET supported_channels = supported_channels - 'CUSTOMER_WEB',
                version = version + 1
            WHERE code = 'telegram_customer'
            """
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("durable customer support queue seed is unavailable")
