from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase


def _uuid() -> str:
    return str(uuid4())


class ManualTopupRequestModel(IdentityBase):
    __tablename__ = "manual_topup_requests"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    requested_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    source_channel: Mapped[str] = mapped_column(String(24), nullable=False)
    current_receipt_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey(
            "manual_topup_receipts.id",
            ondelete="RESTRICT",
            use_alter=True,
            name="fk_manual_topup_current_receipt",
        ),
    )
    customer_note: Mapped[str | None] = mapped_column(String(500))
    admin_visible_state: Mapped[str] = mapped_column(String(32), nullable=False, default="NEW")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT")
    )
    rejected_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT")
    )
    verified_transfer_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    bonus_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    total_credited_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    cash_journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), unique=True
    )
    bonus_journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), unique=True
    )
    customer_message: Mapped[str | None] = mapped_column(String(1000))
    reason_code: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("currency = 'IRR'", name="ck_manual_topup_request_currency"),
        CheckConstraint("requested_amount_rial >= 1000000", name="ck_manual_topup_request_minimum"),
        CheckConstraint("version > 0", name="ck_manual_topup_request_version"),
        CheckConstraint(
            "status in ('AWAITING_SUPPORT','AWAITING_RECEIPT','UNDER_REVIEW',"
            "'NEEDS_RESUBMISSION','APPROVED','REJECTED','CANCELLED','EXPIRED')",
            name="ck_manual_topup_request_status",
        ),
        CheckConstraint(
            "(status <> 'APPROVED') OR (verified_transfer_amount_rial > 0 AND "
            "bonus_amount_rial >= 0 AND total_credited_amount_rial = "
            "verified_transfer_amount_rial + bonus_amount_rial AND "
            "cash_journal_entry_id IS NOT NULL)",
            name="ck_manual_topup_request_approved_amounts",
        ),
        Index("ix_manual_topup_customer_status_created", "customer_id", "status", "created_at"),
        Index("ix_manual_topup_review_queue", "status", "submitted_at", "created_at"),
    )


class ManualTopupReceiptModel(IdentityBase):
    __tablename__ = "manual_topup_receipts"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("manual_topup_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    receipt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    sanitized_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    source_channel: Mapped[str] = mapped_column(String(24), nullable=False)
    telegram_file_unique_id_hash: Mapped[str | None] = mapped_column(String(64))
    security_state: Mapped[str] = mapped_column(String(24), nullable=False, default="SANITIZED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("request_id", "receipt_version", name="uq_manual_topup_receipt_version"),
        CheckConstraint(
            "receipt_version > 0 AND byte_size > 0", name="ck_manual_topup_receipt_values"
        ),
        Index("ix_manual_topup_receipt_hash", "sanitized_sha256"),
    )


class ManualTopupDecisionModel(IdentityBase):
    __tablename__ = "manual_topup_decisions"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("manual_topup_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    expected_request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_transfer_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    bonus_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    internal_note: Mapped[str | None] = mapped_column(String(1000))
    customer_message: Mapped[str | None] = mapped_column(String(1000))
    cash_journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), unique=True
    )
    bonus_journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("request_id", "decision", name="uq_manual_topup_decision_request_kind"),
    )


class ManualTopupIdempotencyModel(IdentityBase):
    __tablename__ = "manual_topup_idempotency"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "scope", "scope_id", "operation", "key_hash", name="uq_manual_topup_idempotency"
        ),
    )


class ManualTopupMessageModel(IdentityBase):
    __tablename__ = "manual_topup_messages"
    reference: Mapped[str] = mapped_column(String(48), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("manual_topup_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sender_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ManualTopupNotificationOutboxModel(IdentityBase):
    __tablename__ = "manual_topup_notification_outbox"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    event_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(96), nullable=False)
    request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("manual_topup_requests.id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    delivery_channel: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("event_reference", name="uq_manual_topup_outbox_event_reference"),
        UniqueConstraint("deduplication_key", name="uq_manual_topup_outbox_deduplication_key"),
        CheckConstraint(
            "status in ('PENDING','PROCESSING','SENT','FAILED')",
            name="ck_manual_topup_outbox_status",
        ),
        Index("ix_manual_topup_outbox_delivery", "status", "available_at"),
    )
