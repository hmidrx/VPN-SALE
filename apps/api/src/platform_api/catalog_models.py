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


class ProductCategoryModel(IdentityBase):
    __tablename__ = "product_categories"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    icon_reference: Mapped[str | None] = mapped_column(String(160))
    admin_notes: Mapped[str | None] = mapped_column(Text)
    localizations: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("slug", name="uq_product_categories_slug"),
        CheckConstraint(
            "status in ('DRAFT','ACTIVE','ARCHIVED')", name="ck_product_categories_status"
        ),
        CheckConstraint("display_order >= 0", name="ck_product_categories_display_order"),
        Index("ix_product_categories_customer", "status", "customer_visible", "display_order"),
    )


class ProductModel(IdentityBase):
    __tablename__ = "products"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    category_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("product_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    machine_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    customer_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    admin_notes: Mapped[str | None] = mapped_column(Text)
    current_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("product_versions.id", ondelete="RESTRICT")
    )
    localizations: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    availability: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("machine_code", name="uq_products_machine_code"),
        CheckConstraint(
            "status in ('DRAFT','ACTIVE','PAUSED','RETIRED','ARCHIVED')", name="ck_products_status"
        ),
        Index("ix_products_customer", "status", "customer_visible", "display_order"),
        Index("ix_products_category", "category_id"),
    )


class ProductVersionModel(IdentityBase):
    __tablename__ = "product_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="DRAFT")
    product_type: Mapped[str] = mapped_column(String(24), nullable=False)
    definition_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    options_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    constraints_snapshot: Mapped[list[object]] = mapped_column(
        JSON_TYPE, nullable=False, default=list
    )
    fulfillment_requirements_snapshot: Mapped[list[object]] = mapped_column(
        JSON_TYPE, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("product_id", "version_number", name="uq_product_versions_product_number"),
        CheckConstraint("version_number > 0", name="ck_product_versions_number"),
        CheckConstraint(
            "status in ('DRAFT','PUBLISHED','SUPERSEDED','RETIRED')",
            name="ck_product_versions_status",
        ),
        CheckConstraint(
            "product_type in ('FIXED_PLAN','CUSTOM_PLAN')", name="ck_product_versions_type"
        ),
        Index("ix_product_versions_product_status", "product_id", "status"),
    )


class PriceListModel(IdentityBase):
    __tablename__ = "price_lists"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="DEFAULT_RETAIL")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (UniqueConstraint("key", name="uq_price_lists_key"),)


class PriceListVersionModel(IdentityBase):
    __tablename__ = "price_list_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    price_list_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("price_lists.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    segment_key: Mapped[str | None] = mapped_column(String(80))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("price_list_id", "version_number", name="uq_price_list_versions_number"),
        CheckConstraint("version_number > 0", name="ck_price_list_versions_number"),
        CheckConstraint("priority >= 0", name="ck_price_list_versions_priority"),
        Index(
            "ix_price_list_versions_resolution", "active", "segment_key", "priority", "active_from"
        ),
    )


class PricingRuleModel(IdentityBase):
    __tablename__ = "pricing_rules"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    price_list_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("price_list_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), nullable=False)
    operation: Mapped[str | None] = mapped_column(String(32))
    selector_code: Mapped[str | None] = mapped_column(String(80))
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unit_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    percentage_basis_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    customer_label: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    __table_args__ = (
        UniqueConstraint("price_list_version_id", "code", name="uq_pricing_rules_version_code"),
        UniqueConstraint(
            "price_list_version_id", "priority", name="uq_pricing_rules_version_priority"
        ),
        CheckConstraint("amount_minor >= 0", name="ck_pricing_rules_amount_non_negative"),
        CheckConstraint("unit_size > 0", name="ck_pricing_rules_unit_size"),
        Index("ix_pricing_rules_price_list_version", "price_list_version_id"),
    )


class PricingTierModel(IdentityBase):
    __tablename__ = "pricing_tiers"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    pricing_rule_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("pricing_rules.id", ondelete="CASCADE"), nullable=False
    )
    lower_inclusive: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upper_exclusive: Mapped[int | None] = mapped_column(BigInteger)
    unit_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        UniqueConstraint("pricing_rule_id", "priority", name="uq_pricing_tiers_rule_priority"),
        CheckConstraint("lower_inclusive >= 0", name="ck_pricing_tiers_lower"),
        CheckConstraint(
            "upper_exclusive is null or upper_exclusive > lower_inclusive",
            name="ck_pricing_tiers_bounds",
        ),
        CheckConstraint("unit_amount_minor >= 0", name="ck_pricing_tiers_amount"),
    )


class CustomerPriceQuoteModel(IdentityBase):
    __tablename__ = "customer_price_quotes"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("product_versions.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    selected_options: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    price_list_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("price_list_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    final_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pricing_engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="ACTIVE")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validation_summary: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    __table_args__ = (
        UniqueConstraint("reference", name="uq_customer_price_quotes_reference"),
        CheckConstraint("subtotal_minor >= 0", name="ck_customer_price_quotes_subtotal"),
        CheckConstraint("final_amount_minor > 0", name="ck_customer_price_quotes_final"),
        Index("ix_customer_price_quotes_customer", "customer_id", "issued_at"),
        Index("ix_customer_price_quotes_reference", "reference"),
    )


class CustomerPriceQuoteLineModel(IdentityBase):
    __tablename__ = "customer_price_quote_lines"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    quote_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customer_price_quotes.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_code: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (Index("ix_customer_price_quote_lines_quote", "quote_id", "display_order"),)


class QuoteIdempotencyRecordModel(IdentityBase):
    __tablename__ = "quote_idempotency_records"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(96), nullable=False)
    quote_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customer_price_quotes.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("customer_id", "key_hash", name="uq_quote_idempotency_customer_key"),
        Index("ix_quote_idempotency_expires", "expires_at"),
    )
