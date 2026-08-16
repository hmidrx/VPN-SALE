"""Enable the durable customer-support queue for authenticated customer web traffic."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043_customer_web_support"
down_revision: str = "0042_support_agent_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    queues = sa.table(
        "support_queues",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("supported_channels", jsonb),
        sa.column("version", sa.Integer),
    )
    result = bind.execute(
        sa.update(queues)
        .where(queues.c.code == "telegram_customer")
        .values(
            name="Customer Support",
            supported_channels=["TELEGRAM_BOT", "CUSTOMER_WEB"],
            version=queues.c.version + 1,
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("durable customer support queue seed is unavailable")


def downgrade() -> None:
    bind = op.get_bind()
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    queues = sa.table(
        "support_queues",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("supported_channels", jsonb),
        sa.column("version", sa.Integer),
    )
    result = bind.execute(
        sa.update(queues)
        .where(queues.c.code == "telegram_customer")
        .values(
            name="Telegram Customer Support",
            supported_channels=["TELEGRAM_BOT"],
            version=queues.c.version + 1,
        )
    )
    if result.rowcount != 1:
        raise RuntimeError("durable customer support queue seed is unavailable")
