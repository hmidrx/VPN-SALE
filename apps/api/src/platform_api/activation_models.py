"""Durable activation and encrypted delivery persistence."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase


class ServiceActivationAttemptModel(IdentityBase):
    __tablename__ = "service_activation_attempts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    activation_attempt_id: Mapped[str] = mapped_column(String(160), nullable=False)
    activation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    activation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activation_failure_category: Mapped[str | None] = mapped_column(String(64))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("service_id", name="uq_service_activation_attempt_service"),
        UniqueConstraint("activation_attempt_id", name="uq_service_activation_attempt_identity"),
        Index(
            "ix_service_activation_claim", "activation_status", "next_retry_at", "lease_expires_at"
        ),
    )


class ServiceDeliveryRecordModel(IdentityBase):
    __tablename__ = "service_delivery_records"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    delivery_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_payload_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    encryption_key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("service_id", name="uq_service_delivery_record_service"),
        UniqueConstraint(
            "delivery_payload_reference", name="uq_service_delivery_payload_reference"
        ),
        Index("ix_service_delivery_ready", "service_id", "delivery_ready"),
    )
