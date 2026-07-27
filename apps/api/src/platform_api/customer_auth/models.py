from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase


class TelegramLinkChallengeModel(IdentityBase):
    """Feature-owned model intentionally excluded from historical Alembic imports."""

    __tablename__ = "telegram_link_challenges"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False
    )
    initiating_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customer_sessions.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("failed_attempt_count >= 0", name="ck_telegram_link_failed_attempts"),
        Index("ix_telegram_link_challenges_user_active", "user_id", "consumed_at"),
        Index("ix_telegram_link_challenges_expires_at", "expires_at"),
    )
