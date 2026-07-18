from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase
from platform_api.order_models import JSON_TYPE


class DeliveryProfileModel(IdentityBase):
    __tablename__ = "delivery_profiles"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    public_reference: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("public_reference", name="uq_delivery_profiles_public_reference"),
        Index("ix_delivery_profiles_status_updated", "status", "updated_at"),
    )


class DeliveryProfileVersionModel(IdentityBase):
    __tablename__ = "delivery_profile_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    profile_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("delivery_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol: Mapped[str] = mapped_column(String(32), nullable=False)
    transport: Mapped[str] = mapped_column(String(32), nullable=False)
    security: Mapped[str] = mapped_column(String(32), nullable=False)
    address_source: Mapped[str] = mapped_column(String(48), nullable=False)
    public_address: Mapped[str] = mapped_column(String(255), nullable=False)
    public_port: Mapped[int] = mapped_column(Integer, nullable=False)
    display_location: Mapped[str] = mapped_column(String(120), nullable=False)
    remark_template: Mapped[str] = mapped_column(String(160), nullable=False)
    tls_settings: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    reality_settings: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    transport_settings: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    protocol_settings: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    compatibility_tags: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    validation_errors: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "version_number", name="uq_delivery_profile_versions_number"
        ),
        Index("ix_delivery_profile_versions_status", "status", "created_at"),
    )


class DeliveryProfileAssignmentModel(IdentityBase):
    __tablename__ = "delivery_profile_assignments"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    profile_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("delivery_profile_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_value: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "target_type", "target_value", "active", name="uq_delivery_assignments_active_target"
        ),
        Index("ix_delivery_assignments_profile", "profile_version_id"),
    )


class DeliveryRendererVersionModel(IdentityBase):
    __tablename__ = "delivery_renderer_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    format_code: Mapped[str] = mapped_column(String(48), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    contract_source: Mapped[str] = mapped_column(String(240), nullable=False)
    supported_matrix: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("format_code", "renderer_version", name="uq_delivery_renderer_versions"),
    )


class DeliveryRevisionModel(IdentityBase):
    __tablename__ = "delivery_revisions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attachment_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    renderer_versions: Mapped[dict[str, str]] = mapped_column(JSON_TYPE, nullable=False)
    credential_fingerprints: Mapped[dict[str, str]] = mapped_column(JSON_TYPE, nullable=False)
    compatibility_state: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    correlation_reference: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "service_id", "revision_number", name="uq_delivery_revisions_service_number"
        ),
        Index("ix_delivery_revisions_service_created", "service_id", "created_at"),
    )


class DeliverySubscriptionModel(IdentityBase):
    __tablename__ = "delivery_subscriptions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    public_reference: Mapped[str] = mapped_column(String(48), nullable=False)
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    active_token_hash: Mapped[str | None] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("public_reference", name="uq_delivery_subscriptions_public_reference"),
        UniqueConstraint("service_id", "scope", name="uq_delivery_subscriptions_service_scope"),
        Index("ix_delivery_subscriptions_token_hash", "active_token_hash"),
    )


class DeliverySubscriptionTokenModel(IdentityBase):
    __tablename__ = "delivery_subscription_tokens"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("delivery_subscriptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    grace_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_delivery_subscription_tokens_hash"),
        Index("ix_delivery_subscription_tokens_status", "status", "issued_at"),
    )


class DeliveryAccessEventModel(IdentityBase):
    __tablename__ = "delivery_access_events"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    subscription_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("delivery_subscriptions.id", ondelete="RESTRICT")
    )
    service_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT")
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_metadata: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("ix_delivery_access_events_service_created", "service_id", "created_at"),
        Index("ix_delivery_access_events_action_outcome", "action", "outcome"),
    )
