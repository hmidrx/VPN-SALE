from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase

TELEGRAM_PRODUCTION_WORKER_ROLE = "telegram-production"


class WorkerHeartbeatModel(IdentityBase):
    __tablename__ = "worker_heartbeats"

    role: Mapped[str] = mapped_column(String(48), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    successful_cycles: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    failed_cycles: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
