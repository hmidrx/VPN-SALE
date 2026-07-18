from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .identity.models import IdentityBase


class OperationalEvidenceModel(IdentityBase):
    __tablename__ = "operational_evidence"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    evidence_type: Mapped[str] = mapped_column(String(48), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    digest: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "environment in ('LOCAL','TEST','CI','STAGING','PRODUCTION')",
            name="ck_operational_evidence_environment",
        ),
        CheckConstraint(
            "status in ('NOT_RUN','PASSED','PASSED_WITH_UNSUPPORTED_STEPS',"
            "'FAILED','CLEANUP_FAILED','RECERTIFICATION_REQUIRED','PASS','FAIL','WARNING')",
            name="ck_operational_evidence_status",
        ),
        Index(
            "ix_operational_evidence_type_env_time", "evidence_type", "environment", "created_at"
        ),
    )


class BackupManifestModel(IdentityBase):
    __tablename__ = "backup_manifests"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    backup_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_object_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    application_version: Mapped[str] = mapped_column(String(80), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sanitized_report: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (Index("ix_backup_manifests_env_completed", "environment", "completed_at"),)


class RestoreDrillModel(IdentityBase):
    __tablename__ = "restore_drills"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    backup_manifest_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invariant_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    sanitized_report: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (Index("ix_restore_drills_env_started", "environment", "started_at"),)


class QualityEvidenceModel(IdentityBase):
    __tablename__ = "quality_evidence"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    evidence_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    profile: Mapped[str] = mapped_column(String(32), nullable=False)
    gate_name: Mapped[str | None] = mapped_column(String(48))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    safe_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    digest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    sanitized_summary: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    finalized: Mapped[bool] = mapped_column(server_default="false", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "profile in ('CI_SAFE','LOCAL_ISOLATED','STAGING_STANDARD',"
            "'STAGING_LOAD','STAGING_SECURITY','STAGING_CHAOS')",
            name="ck_quality_evidence_profile",
        ),
        CheckConstraint(
            "state in ('NOT_RUN','RUNNING','PASSED','PASSED_WITH_LIMITATIONS',"
            "'FAILED','BLOCKED','EXPIRED')",
            name="ck_quality_evidence_state",
        ),
        Index("ix_quality_evidence_kind_profile_time", "evidence_kind", "profile", "created_at"),
    )


class ReleaseDefectModel(IdentityBase):
    __tablename__ = "release_defects"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    component: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    reproduction: Mapped[str] = mapped_column(Text, nullable=False)
    expected_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    observed_behavior: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    correction_reference: Mapped[str | None] = mapped_column(String(160))
    regression_test_reference: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    owner: Mapped[str] = mapped_column(String(80), nullable=False)
    release_blocker: Mapped[bool] = mapped_column(nullable=False)
    residual_risk: Mapped[str] = mapped_column(Text, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(
            "severity in ('CRITICAL','HIGH','MEDIUM','LOW')", name="ck_release_defects_severity"
        ),
        CheckConstraint(
            "status in ('OPEN','FIXED_PENDING_VERIFICATION','VERIFIED','DEFERRED')",
            name="ck_release_defects_status",
        ),
        Index("ix_release_defects_severity_status", "severity", "status"),
    )
