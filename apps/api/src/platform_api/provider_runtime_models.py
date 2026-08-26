"""ORM mappings for the provider runtime tables created by migration 0016."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase
from platform_api.order_models import JSON_TYPE


class PanelInstanceModel(IdentityBase):
    __tablename__ = "panel_instances"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    public_reference: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    endpoint_origin: Mapped[str] = mapped_column(String(512), nullable=False)
    base_path: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    tls_policy: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    endpoint_policy: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    optimistic_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PanelCredentialModel(IdentityBase):
    __tablename__ = "panel_credentials"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    panel_instance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("panel_instances.id"), nullable=False
    )
    credential_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    nonce_b64: Mapped[str] = mapped_column(String(64), nullable=False)
    ciphertext_b64: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderConnectionTestModel(IdentityBase):
    __tablename__ = "provider_connection_tests"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    panel_instance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("panel_instances.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_version: Mapped[str | None] = mapped_column(String(64))
    contract_digest: Mapped[str | None] = mapped_column(String(96))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    safe_error_code: Mapped[str | None] = mapped_column(String(64))
    tested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderSyncRunModel(IdentityBase):
    __tablename__ = "provider_sync_runs"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    sync_reference: Mapped[str] = mapped_column(String(48), nullable=False)
    panel_instance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("panel_instances.id"), nullable=False
    )
    adapter_code: Mapped[str] = mapped_column(String(96), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderInboundSnapshotModel(IdentityBase):
    __tablename__ = "provider_inbound_snapshots"
    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    panel_instance_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("panel_instances.id"), nullable=False
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("provider_sync_runs.id")
    )
    remote_identifier: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str | None] = mapped_column(String(64))
    sanitized_payload: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
