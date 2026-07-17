from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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


class PaymentMethodModel(IdentityBase):
    __tablename__ = "payment_methods"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False)
    method_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    supported_purposes: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    supported_channels: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maintenance_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    capability_set: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    secret_reference: Mapped[str | None] = mapped_column(String(160))
    credential_state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="UNCONFIGURED"
    )
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    public_config: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("code", name="uq_payment_methods_code"),
        CheckConstraint("currency = 'IRR'", name="ck_payment_methods_currency_irr"),
        CheckConstraint(
            "status in ('DRAFT','ACTIVE','PAUSED','MAINTENANCE','RETIRED','ARCHIVED')",
            name="ck_payment_methods_status",
        ),
        Index("ix_payment_methods_status_priority", "status", "priority"),
    )


class PaymentMethodLocalizationModel(IdentityBase):
    __tablename__ = "payment_method_localizations"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    payment_method_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint(
            "payment_method_id", "locale", name="uq_payment_method_localizations_locale"
        ),
    )


class PaymentMethodPolicyModel(IdentityBase):
    __tablename__ = "payment_method_policies"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    payment_method_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    min_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    __table_args__ = (
        UniqueConstraint("payment_method_id", "purpose", name="uq_payment_method_policies_purpose"),
        CheckConstraint(
            "min_amount_rial > 0 and max_amount_rial >= min_amount_rial",
            name="ck_payment_method_policies_amounts",
        ),
    )


class PaymentIntentModel(IdentityBase):
    __tablename__ = "payment_intents"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(48), nullable=False)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    payment_method_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_methods.id", ondelete="RESTRICT"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    wallet_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT")
    )
    order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    invoice_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("invoices.id", ondelete="RESTRICT")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("reference", name="uq_payment_intents_reference"),
        CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_intents_amount_currency"
        ),
        Index("ix_payment_intents_customer_created", "customer_id", "created_at"),
        Index("ix_payment_intents_status_expires", "status", "expires_at"),
    )


class PaymentAttemptModel(IdentityBase):
    __tablename__ = "payment_attempts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_intents.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    provider_payment_reference: Mapped[str | None] = mapped_column(String(160))
    provider_transaction_reference: Mapped[str | None] = mapped_column(String(160))
    action_url: Mapped[str | None] = mapped_column(String(500))
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("reference", name="uq_payment_attempts_reference"),
        UniqueConstraint("intent_id", "attempt_number", name="uq_payment_attempts_intent_number"),
        UniqueConstraint("provider_transaction_reference", name="uq_payment_attempts_provider_tx"),
        CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_attempts_amount_currency"
        ),
        Index("ix_payment_attempts_intent_status", "intent_id", "status"),
    )


class PaymentVerificationModel(IdentityBase):
    __tablename__ = "payment_verifications"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    attempt_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    provider_transaction_reference: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    verified_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    failure_category: Mapped[str | None] = mapped_column(String(80))
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        Index("ix_payment_verifications_attempt_created", "attempt_id", "created_at"),
    )


class PaymentSettlementModel(IdentityBase):
    __tablename__ = "payment_settlements"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_intents.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    provider_transaction_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    journal_entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False
    )
    refundable_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("reference", name="uq_payment_settlements_reference"),
        UniqueConstraint("intent_id", name="uq_payment_settlements_intent"),
        UniqueConstraint(
            "provider_transaction_reference", name="uq_payment_settlements_provider_tx"
        ),
        CheckConstraint(
            "amount_rial > 0 and refundable_amount_rial >= 0 and currency = 'IRR'",
            name="ck_payment_settlements_amount_currency",
        ),
    )


class PaymentWebhookInboxModel(IdentityBase):
    __tablename__ = "payment_webhook_inbox"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    payment_method_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_methods.id", ondelete="RESTRICT")
    )
    provider_code: Mapped[str] = mapped_column(String(48), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_event_reference: Mapped[str | None] = mapped_column(String(160))
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    sanitized_headers: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "provider_code",
            "adapter_version",
            "provider_event_reference",
            name="uq_payment_webhook_provider_event",
        ),
        UniqueConstraint(
            "provider_code",
            "adapter_version",
            "payload_digest",
            name="uq_payment_webhook_payload_digest",
        ),
        Index("ix_payment_webhook_status_received", "status", "received_at"),
    )


class PaymentRefundModel(IdentityBase):
    __tablename__ = "payment_refunds"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    settlement_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("payment_settlements.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by_admin_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("reference", name="uq_payment_refunds_reference"),
        CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_refunds_amount_currency"
        ),
        Index("ix_payment_refunds_settlement_status", "settlement_id", "status"),
    )


class PaymentRefundAttemptModel(IdentityBase):
    __tablename__ = "payment_refund_attempts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    refund_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("payment_refunds.id", ondelete="RESTRICT"), nullable=False
    )
    provider_refund_reference: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PaymentIdempotencyRecordModel(IdentityBase):
    __tablename__ = "payment_idempotency_records"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "operation_type",
            "key_hash",
            name="uq_payment_idempotency_scope",
        ),
    )


class PaymentReconciliationRunModel(IdentityBase):
    __tablename__ = "payment_reconciliation_runs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    mismatch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_by_admin_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("reference", name="uq_payment_reconciliation_runs_reference"),
    )
