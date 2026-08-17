"""Direct wallet payments for service operations.

Revision ID: 0045_service_op_wallet_payment
Revises: 0044_support_web_unread
Create Date: 2026-08-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045_service_op_wallet_payment"
down_revision: str = "0044_support_web_unread"
branch_labels: None = None
depends_on: None = None

UUID_T = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(none_as_null=True)


def upgrade() -> None:
    op.create_table(
        "service_operation_payments",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "operation_id",
            UUID_T,
            sa.ForeignKey("service_operations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            UUID_T,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id",
            UUID_T,
            sa.ForeignKey("wallets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reservation_id",
            UUID_T,
            sa.ForeignKey("wallet_reservations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "capture_journal_id",
            UUID_T,
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "refund_journal_id",
            UUID_T,
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        ),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("spend_snapshot", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("operation_id", name="uq_service_operation_payments_operation"),
        sa.UniqueConstraint("reservation_id", name="uq_service_operation_payments_reservation"),
        sa.UniqueConstraint(
            "capture_journal_id", name="uq_service_operation_payments_capture_journal"
        ),
        sa.CheckConstraint("amount_rial > 0", name="ck_service_operation_payments_amount"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_service_operation_payments_currency"),
        sa.CheckConstraint(
            "status in ('CAPTURED','REFUNDED')",
            name="ck_service_operation_payments_status",
        ),
    )
    op.create_index(
        "ix_service_operation_payments_customer_created",
        "service_operation_payments",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_service_operation_payments_status_created",
        "service_operation_payments",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_operation_payments_status_created",
        table_name="service_operation_payments",
    )
    op.drop_index(
        "ix_service_operation_payments_customer_created",
        table_name="service_operation_payments",
    )
    op.drop_table("service_operation_payments")
