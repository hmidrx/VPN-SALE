from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase


def _uuid() -> str:
    return str(uuid4())


class ServiceActivationRequestModel(IdentityBase):
    """Durable, retry-safe activation work item for one provisioned service."""

    __tablename__ = "service_activation_requests"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String(96))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_category: Mapped[str | None] = mapped_column(String(64))
    result_code: Mapped[str | None] = mapped_column(String(80))
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("service_id", name="uq_service_activation_service"),
        CheckConstraint(
            "status in ('PENDING','CLAIMED','RETRY_PENDING','BLOCKED',"
            "'OPERATOR_REVIEW','SUCCEEDED')",
            name="ck_service_activation_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_service_activation_attempt_count"),
        Index(
            "ix_service_activation_retry",
            "status",
            "next_attempt_at",
            "lease_expires_at",
        ),
    )
