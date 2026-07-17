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

JSON_COL = JSON().with_variant(JSONB, "postgresql")


class CustomerNoteModel(IdentityBase):
    __tablename__ = "customer_admin_notes"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    note_type: Mapped[str] = mapped_column(String(32), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint(
            "note_type in ('GENERAL','FINANCIAL','SECURITY','OPERATIONS',"
            "'SUPPORT_PREPARATION','COMPLIANCE')",
            name="ck_customer_notes_type",
        ),
        CheckConstraint("version > 0", name="ck_customer_notes_version"),
        Index("ix_customer_notes_customer", "customer_id", "created_at"),
    )


class CustomerNoteHistoryModel(IdentityBase):
    __tablename__ = "customer_admin_note_history"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    note_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customer_admin_notes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CustomerTagModel(IdentityBase):
    __tablename__ = "customer_admin_tags"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name_i18n: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    description_i18n: Mapped[dict[str, object]] = mapped_column(
        JSON_COL, nullable=False, default=dict
    )
    color_token: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("code", name="uq_customer_tags_code"),
        Index("ix_customer_tags_active", "active"),
    )


class CustomerTagAssignmentModel(IdentityBase):
    __tablename__ = "customer_admin_tag_assignments"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    tag_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customer_admin_tags.id", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("customer_id", "tag_id", name="uq_customer_tag_assignment"),
        Index("ix_customer_tag_assignments_customer", "customer_id"),
        Index("ix_customer_tag_assignments_tag", "tag_id"),
    )


class CustomerSavedViewModel(IdentityBase):
    __tablename__ = "customer_admin_saved_views"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    owner_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="PERSONAL")
    filters: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    sort: Mapped[str] = mapped_column(String(32), nullable=False, default="created_desc")
    columns: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint("visibility in ('PERSONAL','SHARED')", name="ck_customer_views_visibility"),
        Index("ix_customer_views_owner", "owner_admin_id"),
    )


class CustomerAdjustmentRequestModel(IdentityBase):
    __tablename__ = "customer_admin_adjustment_requests"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    wallet_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    bucket_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_rial: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(48), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING_APPROVAL")
    high_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT")
    )
    journal_entry_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("journal_entries.id", ondelete="RESTRICT")
    )
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint(
            "requested_by_admin_id", "idempotency_key_hash", name="uq_customer_adjustment_idem"
        ),
        CheckConstraint("amount_rial > 0", name="ck_customer_adjustment_amount"),
        CheckConstraint("direction in ('CREDIT','DEBIT')", name="ck_customer_adjustment_direction"),
        Index("ix_customer_adjustments_customer", "customer_id", "created_at"),
        Index("ix_customer_adjustments_status", "status"),
    )


class CustomerExportJobModel(IdentityBase):
    __tablename__ = "customer_admin_export_jobs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    requested_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="QUEUED")
    file_format: Mapped[str] = mapped_column(String(8), nullable=False, default="CSV")
    filters: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    fields: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_reference_hash: Mapped[str | None] = mapped_column(String(64))
    content: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_customer_exports_admin_status", "requested_by_admin_id", "status"),)


class CustomerBulkJobModel(IdentityBase):
    __tablename__ = "customer_admin_bulk_jobs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    requested_by_admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="DRAFT")
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint(
            "requested_by_admin_id", "idempotency_key_hash", name="uq_customer_bulk_idem"
        ),
        Index("ix_customer_bulk_status", "status"),
    )


class CustomerBulkItemModel(IdentityBase):
    __tablename__ = "customer_admin_bulk_items"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("customer_admin_bulk_jobs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING")
    result: Mapped[dict[str, object]] = mapped_column(JSON_COL, nullable=False, default=dict)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("job_id", "customer_id", name="uq_customer_bulk_item"),
        UniqueConstraint("job_id", "idempotency_key_hash", name="uq_customer_bulk_item_idem"),
        Index("ix_customer_bulk_items_job", "job_id", "status"),
    )
