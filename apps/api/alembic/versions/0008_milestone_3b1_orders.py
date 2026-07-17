"""Milestone 3-B1 order checkout invoice backend."""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_milestone_3b1_orders"
down_revision: str = "0007_milestone_3a1_wallet"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("orders.read", "Read orders"),
    ("orders.manage", "Inspect order administration"),
    ("orders.cancel", "Cancel eligible orders"),
    ("invoices.read", "Read invoices"),
    ("checkout.read", "Read checkout records"),
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=False)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "orders",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "quote_id",
            uuid,
            sa.ForeignKey("customer_price_quotes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quote_reference", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("financial_status", sa.String(40), nullable=False),
        sa.Column("fulfillment_status", sa.String(40), nullable=False),
        sa.Column("payment_method", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_rial", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_total_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("final_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("snapshot", jsonb, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reference", name="uq_orders_reference"),
        sa.UniqueConstraint("quote_id", name="uq_orders_quote_one_economic"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_orders_currency_irr"),
        sa.CheckConstraint(
            "subtotal_rial >= 0 and adjustment_total_rial >= 0 and final_amount_rial > 0",
            name="ck_orders_amounts",
        ),
    )
    op.create_index("ix_orders_customer_created", "orders", ["customer_id", "created_at"])
    op.create_index("ix_orders_status_created", "orders", ["status", "created_at"])
    op.create_table(
        "order_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "product_id", uuid, sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "product_version_id",
            uuid,
            sa.ForeignKey("product_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("product_machine_code", sa.String(80), nullable=False),
        sa.Column("snapshot", jsonb, nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("order_id", "position", name="uq_order_items_order_position"),
    )
    op.create_table(
        "checkout_sessions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column("quote_id", uuid, nullable=False),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("payment_method", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "wallet_reservation_id",
            uuid,
            sa.ForeignKey("wallet_reservations.id", ondelete="RESTRICT"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reference", name="uq_checkout_sessions_reference"),
    )
    op.create_index("ix_checkout_sessions_due", "checkout_sessions", ["status", "expires_at"])
    op.create_table(
        "invoices",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_rial", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_total_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("discount_total_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("tax_total_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("payable_total_rial", sa.BigInteger(), nullable=False),
        sa.Column("paid_total_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("invoice_version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reference", name="uq_invoices_reference"),
        sa.UniqueConstraint("order_id", name="uq_invoices_order"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_invoices_currency_irr"),
        sa.CheckConstraint(
            "payable_total_rial > 0 and paid_total_rial >= 0 "
            "and paid_total_rial <= payable_total_rial",
            name="ck_invoices_amounts",
        ),
    )
    op.create_index("ix_invoices_customer_issued", "invoices", ["customer_id", "issued_at"])
    op.create_table(
        "invoice_lines",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "invoice_id", uuid, sa.ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("line_type", sa.String(32), nullable=False),
        sa.Column("product_id", uuid, nullable=False),
        sa.Column("product_version_id", uuid, nullable=False),
        sa.Column("description", sa.String(240), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("unit_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("line_subtotal_rial", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_table(
        "wallet_payments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "invoice_id", uuid, sa.ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("wallet_id", uuid, nullable=False),
        sa.Column("reservation_id", uuid, nullable=False),
        sa.Column(
            "capture_journal_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "refund_journal_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")
        ),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("reference", name="uq_wallet_payments_reference"),
        sa.UniqueConstraint("order_id", "invoice_id", name="uq_wallet_payments_order_invoice"),
        sa.CheckConstraint("amount_rial > 0", name="ck_wallet_payments_amount"),
    )
    op.create_table(
        "order_timeline_events",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_code", sa.String(80), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_reference", sa.String(80)),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("order_id", "sequence", name="uq_order_timeline_sequence"),
    )
    op.create_index("ix_order_timeline_order", "order_timeline_events", ["order_id", "sequence"])
    op.create_table(
        "checkout_idempotency_records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column("quote_id", uuid, nullable=False),
        sa.Column("operation_type", sa.String(48), nullable=False),
        sa.Column("payment_method", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("checkout_id", uuid, sa.ForeignKey("checkout_sessions.id", ondelete="RESTRICT")),
        sa.Column("result_snapshot", jsonb),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "customer_id",
            "quote_id",
            "operation_type",
            "payment_method",
            "key_hash",
            name="uq_checkout_idempotency_scope",
        ),
    )
    op.create_table(
        "order_cancellations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_reference", sa.String(80), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "refund_journal_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "transactional_outbox",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("event_key", sa.String(120), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("payload", jsonb, nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_category", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("event_key", name="uq_transactional_outbox_event_key"),
    )
    op.create_index(
        "ix_transactional_outbox_claim", "transactional_outbox", ["status", "available_at"]
    )
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String(length=120)),
        sa.column("description", sa.String(length=240)),
    )
    for code, description in PERMISSIONS:
        stmt = (
            postgresql.insert(permissions_table)
            .values(id=uuid4(), code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )
        op.execute(stmt)


def downgrade() -> None:
    for table in (
        "transactional_outbox",
        "order_cancellations",
        "checkout_idempotency_records",
        "order_timeline_events",
        "wallet_payments",
        "invoice_lines",
        "invoices",
        "checkout_sessions",
        "order_items",
        "orders",
    ):
        op.drop_table(table)
    for code, _ in PERMISSIONS:
        op.execute(sa.text("delete from permissions where code = :code").bindparams(code=code))
