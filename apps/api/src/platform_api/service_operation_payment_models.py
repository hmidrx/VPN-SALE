from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase
from platform_api.order_models import JSON_TYPE


class ServiceOperationPaymentModel(IdentityBase):
    """One direct wallet payment anchor per durable service operation."""

    __tablename__ = "service_operation_payments"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    reservation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("wallet_reservations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capture_journal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False
    )
    refund_journal_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    spend_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_service_operation_payments_operation"),
        UniqueConstraint("reservation_id", name="uq_service_operation_payments_reservation"),
        UniqueConstraint(
            "capture_journal_id", name="uq_service_operation_payments_capture_journal"
        ),
        CheckConstraint("amount_rial > 0", name="ck_service_operation_payments_amount"),
        CheckConstraint("currency = 'IRR'", name="ck_service_operation_payments_currency"),
        CheckConstraint(
            "status in ('CAPTURED','REFUNDED')", name="ck_service_operation_payments_status"
        ),
        Index("ix_service_operation_payments_customer_created", "customer_id", "created_at"),
        Index("ix_service_operation_payments_status_created", "status", "created_at"),
    )
