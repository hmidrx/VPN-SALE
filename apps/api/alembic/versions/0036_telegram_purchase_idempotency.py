"""Add a global Telegram purchase idempotency anchor.

Revision ID: 0036_telegram_purchase_idem
Revises: 0035_manual_topup_destinations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_telegram_purchase_idem"
down_revision: str = "0035_manual_topup_destinations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_purchase_idempotency",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="REVIEWING"),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("customer_id", "key_hash", name="uq_tg_purchase_idem_customer_key"),
        sa.CheckConstraint(
            "status in ('REVIEWING','COMMITTED')", name="ck_tg_purchase_idem_status"
        ),
        sa.CheckConstraint(
            "status != 'COMMITTED' or order_id is not null",
            name="ck_tg_purchase_idem_committed_order",
        ),
    )
    op.create_index("ix_tg_purchase_idem_order", "telegram_purchase_idempotency", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_tg_purchase_idem_order", table_name="telegram_purchase_idempotency")
    op.drop_table("telegram_purchase_idempotency")
