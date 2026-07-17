from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class OrderModel(IdentityBase):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    quote_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customer_price_quotes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quote_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    financial_status: Mapped[str] = mapped_column(String(40), nullable=False)
    fulfillment_status: Mapped[str] = mapped_column(String(40), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    final_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("reference", name="uq_orders_reference"),
        UniqueConstraint("quote_id", name="uq_orders_quote_one_economic"),
        CheckConstraint("currency = 'IRR'", name="ck_orders_currency_irr"),
        CheckConstraint(
            "subtotal_rial >= 0 and adjustment_total_rial >= 0 and final_amount_rial > 0",
            name="ck_orders_amounts",
        ),
        Index("ix_orders_customer_created", "customer_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
    )


class OrderItemModel(IdentityBase):
    __tablename__ = "order_items"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("product_versions.id", ondelete="RESTRICT"), nullable=False
    )
    product_machine_code: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("order_id", "position", name="uq_order_items_order_position"),
    )


class CheckoutSessionModel(IdentityBase):
    __tablename__ = "checkout_sessions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    quote_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    wallet_reservation_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_reservations.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("reference", name="uq_checkout_sessions_reference"),
        Index("ix_checkout_sessions_due", "status", "expires_at"),
    )


class InvoiceModel(IdentityBase):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    adjustment_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    discount_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payable_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_total_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invoice_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("reference", name="uq_invoices_reference"),
        UniqueConstraint("order_id", name="uq_invoices_order"),
        CheckConstraint("currency = 'IRR'", name="ck_invoices_currency_irr"),
        CheckConstraint(
            "payable_total_rial > 0 and paid_total_rial >= 0 "
            "and paid_total_rial <= payable_total_rial",
            name="ck_invoices_amounts",
        ),
        Index("ix_invoices_customer_issued", "customer_id", "issued_at"),
    )


class InvoiceLineModel(IdentityBase):
    __tablename__ = "invoice_lines"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    line_type: Mapped[str] = mapped_column(String(32), nullable=False)
    product_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    product_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_subtotal_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )


class WalletPaymentModel(IdentityBase):
    __tablename__ = "wallet_payments"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    reservation_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    capture_journal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    refund_journal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("reference", name="uq_wallet_payments_reference"),
        UniqueConstraint("order_id", "invoice_id", name="uq_wallet_payments_order_invoice"),
        CheckConstraint("amount_rial > 0", name="ck_wallet_payments_amount"),
    )


class OrderTimelineEventModel(IdentityBase):
    __tablename__ = "order_timeline_events"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_code: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_reference: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("order_id", "sequence", name="uq_order_timeline_sequence"),
        Index("ix_order_timeline_order", "order_id", "sequence"),
    )


class CheckoutIdempotencyRecordModel(IdentityBase):
    __tablename__ = "checkout_idempotency_records"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    quote_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    checkout_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("checkout_sessions.id", ondelete="RESTRICT")
    )
    result_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "quote_id",
            "operation_type",
            "payment_method",
            "key_hash",
            name="uq_checkout_idempotency_scope",
        ),
    )


class OrderCancellationModel(IdentityBase):
    __tablename__ = "order_cancellations"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    refund_journal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TransactionalOutboxModel(IdentityBase):
    __tablename__ = "transactional_outbox"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    event_key: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_transactional_outbox_event_key"),
        Index("ix_transactional_outbox_claim", "status", "available_at"),
    )
