from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .identity.models import IdentityBase


class ConfigurationDefinitionModel(IdentityBase):
    __tablename__ = "configuration_definitions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    namespace: Mapped[str] = mapped_column(String(48), nullable=False)
    code: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    __table_args__ = (
        UniqueConstraint(
            "namespace", "code", "schema_version", name="uq_config_definitions_code_version"
        ),
    )


class ConfigurationDraftModel(IdentityBase):
    __tablename__ = "configuration_drafts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(48), nullable=False, default="global")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    snapshot: Mapped[dict[str, object]]
    created_by_admin_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_configuration_drafts_version"),
        Index("ix_configuration_drafts_status", "status"),
    )


class ConfigurationReleaseModel(IdentityBase):
    __tablename__ = "configuration_releases"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scope: Mapped[str] = mapped_column(String(48), nullable=False, default="global")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    immutable_snapshot: Mapped[dict[str, object]]
    draft_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("configuration_drafts.id", ondelete="RESTRICT")
    )
    published_by_admin_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_by_release_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("configuration_releases.id", ondelete="RESTRICT")
    )
    is_effective: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("scope", "version", name="uq_configuration_releases_scope_version"),
        Index(
            "uq_configuration_one_effective",
            "scope",
            unique=True,
            postgresql_where=sa.text("is_effective"),
        ),
        Index("ix_configuration_releases_status_dates", "status", "scheduled_for", "published_at"),
    )


class ConfigurationReleaseItemModel(IdentityBase):
    __tablename__ = "configuration_release_items"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    release_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("configuration_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    namespace: Mapped[str] = mapped_column(String(48), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, object]]
    __table_args__ = (
        UniqueConstraint(
            "release_id", "namespace", name="uq_configuration_release_items_namespace"
        ),
    )


class ConfigurationValidationRunModel(IdentityBase):
    __tablename__ = "configuration_validation_runs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    draft_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("configuration_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    issues: Mapped[dict[str, object]]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfigurationPreviewSessionModel(IdentityBase):
    __tablename__ = "configuration_preview_sessions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    opaque_reference_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    draft_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("configuration_drafts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_admin_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RuntimeConfigurationSnapshotModel(IdentityBase):
    __tablename__ = "runtime_configuration_snapshots"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    release_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("configuration_releases.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    etag: Mapped[str] = mapped_column(String(96), nullable=False)
    public_snapshot: Mapped[dict[str, object]]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MediaAssetModel(IdentityBase):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    public_reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(96), nullable=False)
    alt_text: Mapped[str | None] = mapped_column(String(240))
    storage_key: Mapped[str] = mapped_column(String(180), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("digest", "role", name="uq_media_assets_digest_role"),
        Index("ix_media_assets_status_role", "status", "role"),
    )
