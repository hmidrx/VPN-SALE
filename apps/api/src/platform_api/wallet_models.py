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


class WalletModel(IdentityBase):
    __tablename__ = "wallets"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("customer_id", "currency", name="uq_wallets_customer_currency"),
        CheckConstraint("currency = 'IRR'", name="ck_wallets_currency_irr"),
        CheckConstraint("status in ('ACTIVE','FROZEN','CLOSED')", name="ck_wallets_status"),
        Index("ix_wallets_customer", "customer_id"),
    )


class LedgerAccountModel(IdentityBase):
    __tablename__ = "ledger_accounts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    account_type: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    wallet_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT")
    )
    system_account: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    __table_args__ = (
        UniqueConstraint("code", name="uq_ledger_accounts_code"),
        CheckConstraint("currency = 'IRR'", name="ck_ledger_accounts_currency_irr"),
        Index("ix_ledger_accounts_wallet", "wallet_id"),
    )


class JournalEntryModel(IdentityBase):
    __tablename__ = "journal_entries"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    operation_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="POSTED")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    wallet_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_record_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_financial_idempotency.id", ondelete="SET NULL")
    )
    reversal_of_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    description_code: Mapped[str] = mapped_column(String(80), nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("status in ('POSTED','REVERSED')", name="ck_journal_entries_status"),
        CheckConstraint("currency = 'IRR'", name="ck_journal_entries_currency_irr"),
        Index("ix_journal_entries_wallet_posted", "wallet_id", "posted_at"),
        Index("ix_journal_entries_correlation", "correlation_id"),
    )


class LedgerPostingModel(IdentityBase):
    __tablename__ = "ledger_postings"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    journal_entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False
    )
    ledger_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("ledger_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posting_order: Mapped[int] = mapped_column(Integer, nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(80), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "journal_entry_id", "posting_order", name="uq_ledger_postings_entry_order"
        ),
        CheckConstraint("direction in ('DEBIT','CREDIT')", name="ck_ledger_postings_direction"),
        CheckConstraint("amount_rial > 0", name="ck_ledger_postings_amount_positive"),
        Index("ix_ledger_postings_account", "ledger_account_id"),
    )


class WalletBalanceProjectionModel(IdentityBase):
    __tablename__ = "wallet_balance_projections"
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), primary_key=True
    )
    posted_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reserved_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    available_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    promotional_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    expiring_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "posted_balance_rial >= 0 and reserved_balance_rial >= 0 "
            "and available_balance_rial >= 0",
            name="ck_wallet_projection_non_negative",
        ),
    )


class WalletBalanceBucketModel(IdentityBase):
    __tablename__ = "wallet_balance_buckets"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    bucket_type: Mapped[str] = mapped_column(String(32), nullable=False)
    balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    __table_args__ = (
        UniqueConstraint("wallet_id", "bucket_type", name="uq_wallet_buckets_wallet_type"),
        CheckConstraint("balance_rial >= 0", name="ck_wallet_buckets_balance_non_negative"),
    )


class WalletCreditLotModel(IdentityBase):
    __tablename__ = "wallet_credit_lots"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    bucket_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_operation: Mapped[str] = mapped_column(String(64), nullable=False)
    journal_entry_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    __table_args__ = (
        CheckConstraint(
            "original_amount_rial > 0 and remaining_amount_rial >= 0",
            name="ck_wallet_credit_lots_amounts",
        ),
        Index("ix_wallet_credit_lots_expiration", "status", "expires_at"),
    )


class WalletReservationModel(IdentityBase):
    __tablename__ = "wallet_reservations"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    purpose_code: Mapped[str] = mapped_column(String(80), nullable=False)
    opaque_reference: Mapped[str | None] = mapped_column(String(120))
    idempotency_record_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_financial_idempotency.id", ondelete="SET NULL")
    )
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("amount_rial > 0", name="ck_wallet_reservations_amount_positive"),
        CheckConstraint(
            "status in ('ACTIVE','RELEASED','EXPIRED','CAPTURED','CANCELLED')",
            name="ck_wallet_reservations_status",
        ),
        Index("ix_wallet_reservations_wallet_status", "wallet_id", "status"),
        Index("ix_wallet_reservations_expiration", "status", "expires_at"),
    )


class WalletFinancialIdempotencyModel(IdentityBase):
    __tablename__ = "wallet_financial_idempotency"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result_type: Mapped[str | None] = mapped_column(String(32))
    result_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint(
            "scope_type",
            "scope_id",
            "operation_type",
            "key_hash",
            name="uq_wallet_idempotency_scope_op_key",
        ),
    )


class WalletPolicyModel(IdentityBase):
    __tablename__ = "wallet_policies"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IRR")
    minimum_topup_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    maximum_topup_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    maximum_wallet_balance_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    default_reservation_lifetime_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_reservation_lifetime_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    promotional_credit_expiration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    referral_credit_expiration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    gift_credit_expiration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    spending_bucket_priority: Mapped[str] = mapped_column(Text, nullable=False)
    customer_wallet_operations_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    max_transaction_history_page_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("currency", name="uq_wallet_policies_currency"),
        CheckConstraint("currency = 'IRR'", name="ck_wallet_policies_currency_irr"),
        CheckConstraint(
            "minimum_topup_amount_rial <= maximum_topup_amount_rial",
            name="ck_wallet_policies_topup_bounds",
        ),
    )


class WalletReconciliationRunModel(IdentityBase):
    __tablename__ = "wallet_reconciliation_runs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    mismatches: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    repaired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
