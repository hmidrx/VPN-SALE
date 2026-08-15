"""Authoritative runtime configuration/state for paid order fulfillment."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase
from platform_api.order_models import JSON_TYPE


class FulfillmentTargetBindingModel(IdentityBase):
    """Explicit immutable-catalog selection -> allocation-target binding."""

    __tablename__ = "fulfillment_target_bindings"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    product_version_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    location_code: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_code: Mapped[str] = mapped_column(String(80), nullable=False)
    allocation_target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("allocation_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    capability_codes: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "product_version_id",
            "location_code",
            "quality_code",
            "allocation_target_id",
            name="uq_fulfillment_target_binding_selection_target",
        ),
        Index(
            "ix_fulfillment_target_binding_lookup",
            "product_version_id",
            "location_code",
            "quality_code",
            "active",
        ),
    )


class FulfillmentEntitlementClockModel(IdentityBase):
    """Customer entitlement clock persisted only after verified activation and delivery."""

    __tablename__ = "fulfillment_entitlement_clocks"

    fulfillment_request_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_fulfillment_requests.id", ondelete="CASCADE"),
        primary_key=True,
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
