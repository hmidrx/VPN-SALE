from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .identity.models import IdentityBase
from .order_models import JSON_TYPE


class ServiceUsageAccountModel(IdentityBase):
    __tablename__ = "service_usage_accounts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id"), nullable=False, unique=True
    )
    allowance_bytes: Mapped[int | None] = mapped_column(BigInteger)
    is_unlimited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aggregation_policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    lifetime_baseline_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ServiceUsageCycleModel(IdentityBase):
    __tablename__ = "service_usage_cycles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    usage_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_usage_accounts.id"), nullable=False
    )
    cycle_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    start_reason: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allowance_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    lifetime_baseline_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    aggregation_policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    service_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ServiceUsageObservationModel(IdentityBase):
    __tablename__ = "service_usage_observations"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    usage_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_usage_accounts.id"), nullable=False
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id"), nullable=False
    )
    attachment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_attachments.id"), nullable=False
    )
    counter_generation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    provider_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_contract_code: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    counter_scope_key: Mapped[str] = mapped_column(String(160), nullable=False)
    upload_bytes: Mapped[int | None] = mapped_column(BigInteger)
    download_bytes: Mapped[int | None] = mapped_column(BigInteger)
    combined_bytes: Mapped[int | None] = mapped_column(BigInteger)
    remote_limit_bytes: Mapped[int | None] = mapped_column(BigInteger)
    remote_expiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_enabled: Mapped[bool | None] = mapped_column(Boolean)
    online_state: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    anomaly_flags: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    idempotency_key_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)


class ServiceUsageAggregateModel(IdentityBase):
    __tablename__ = "service_usage_aggregates"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    usage_account_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_usage_accounts.id"), nullable=False
    )
    cycle_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_usage_cycles.id"), nullable=False
    )
    used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    remaining_bytes: Mapped[int | None] = mapped_column(BigInteger)
    overage_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    consumed_percent: Mapped[int | None] = mapped_column(Integer)
    quota_state: Mapped[str] = mapped_column(String(48), nullable=False)
    expiry_state: Mapped[str] = mapped_column(String(48), nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    explanation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ServiceUsageSyncRunModel(IdentityBase):
    __tablename__ = "service_usage_sync_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    worker_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    safe_summary: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False, default=dict)
