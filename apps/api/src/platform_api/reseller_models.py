from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase


class ResellerTierModel(IdentityBase):
    __tablename__ = "reseller_tiers"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    limits: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("code", name="uq_reseller_tiers_code"),)


class ResellerAccountModel(IdentityBase):
    __tablename__ = "reseller_accounts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    principal_user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    business_name: Mapped[str] = mapped_column(String(180), nullable=False)
    public_brand_label: Mapped[str] = mapped_column(String(120), nullable=False)
    tier_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reseller_tiers.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    settlement_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    price_book_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    financial_account_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    credit_terms: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    quota_overrides: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    remark_policy: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    parent_reseller_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reseller_accounts.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("reference", name="uq_reseller_accounts_reference"),
        UniqueConstraint("principal_user_id", name="uq_reseller_accounts_principal"),
        CheckConstraint(
            (
                "status in ('DRAFT','PENDING_REVIEW','ACTIVE','SUSPENDED','BLOCKED',"
                "'TERMINATED','ARCHIVED')"
            ),
            name="ck_reseller_accounts_status",
        ),
        CheckConstraint(
            "settlement_mode in ('PREPAID','CONTROLLED_CREDIT')",
            name="ck_reseller_accounts_settlement",
        ),
        Index("ix_reseller_accounts_status", "status", "created_at"),
    )


class ResellerPriceBookModel(IdentityBase):
    __tablename__ = "reseller_price_books"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("reference", name="uq_reseller_price_books_ref"),)


class ResellerPricingRuleModel(IdentityBase):
    __tablename__ = "reseller_pricing_rules"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    price_book_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("reseller_price_books.id", ondelete="RESTRICT"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    rule_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    product_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("products.id", ondelete="RESTRICT")
    )
    category_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("categories.id", ondelete="RESTRICT")
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    percent_bps: Mapped[int | None] = mapped_column(Integer)
    minimum_price_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    minimum_margin_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        Index(
            "ix_reseller_pricing_effective", "price_book_id", "scope", "effective_at", "expires_at"
        ),
    )


class ResellerCustomerRelationshipModel(IdentityBase):
    __tablename__ = "reseller_customer_relationships"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reseller_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reseller_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT")
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    visible_profile: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        Index("ix_reseller_customer_reseller", "reseller_id", "state"),
        Index("ix_reseller_customer_customer", "customer_id", "state"),
    )


class ResellerFinancialAccountModel(IdentityBase):
    __tablename__ = "reseller_financial_accounts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reseller_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reseller_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT")
    )
    credit_limit_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    utilized_credit_rial: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_reference: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("reseller_id", name="uq_reseller_financial_account"),
        CheckConstraint(
            (
                "credit_limit_rial >= 0 and utilized_credit_rial >= 0 "
                "and utilized_credit_rial <= credit_limit_rial"
            ),
            name="ck_reseller_credit_limit",
        ),
    )


class ResellerOrderAttributionModel(IdentityBase):
    __tablename__ = "reseller_order_attributions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reseller_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("reseller_accounts.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    wholesale_amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    retail_amount_rial: Mapped[int | None] = mapped_column(BigInteger)
    pricing_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    remark_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("order_id", name="uq_reseller_order_attribution_order"),)
