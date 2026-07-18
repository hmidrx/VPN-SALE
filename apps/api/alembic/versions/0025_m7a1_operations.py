"""Milestone 7-A1 operations readiness

Revision ID: 0025_m7a1_operations
Revises: 0024_m6d2_fleet_operations
Create Date: 2026-07-18 00:00:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_m7a1_operations"
down_revision: str = "0024_m6d2_fleet_operations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "operational_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_type", sa.String(length=48), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("safe_reference", sa.String(length=160), nullable=False),
        sa.Column("digest", sa.String(length=128), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "environment in ('LOCAL','TEST','CI','STAGING','PRODUCTION')",
            name="ck_operational_evidence_environment",
        ),
        sa.CheckConstraint(
            (
                "status in ('NOT_RUN','PASSED','PASSED_WITH_UNSUPPORTED_STEPS',"
                "'FAILED','CLEANUP_FAILED','RECERTIFICATION_REQUIRED','PASS','FAIL','WARNING')"
            ),
            name="ck_operational_evidence_status",
        ),
    )
    op.create_index(
        "ix_operational_evidence_type_env_time",
        "operational_evidence",
        ["evidence_type", "environment", "created_at"],
    )
    op.create_table(
        "backup_manifests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("backup_kind", sa.String(length=32), nullable=False),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("encrypted_object_reference", sa.String(length=160), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("schema_revision", sa.String(length=64), nullable=False),
        sa.Column("application_version", sa.String(length=80), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sanitized_report", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_backup_manifests_env_completed", "backup_manifests", ["environment", "completed_at"]
    )
    op.create_table(
        "restore_drills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("backup_manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invariant_digest", sa.String(length=128), nullable=False),
        sa.Column("sanitized_report", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_restore_drills_env_started", "restore_drills", ["environment", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_restore_drills_env_started", table_name="restore_drills")
    op.drop_table("restore_drills")
    op.drop_index("ix_backup_manifests_env_completed", table_name="backup_manifests")
    op.drop_table("backup_manifests")
    op.drop_index("ix_operational_evidence_type_env_time", table_name="operational_evidence")
    op.drop_table("operational_evidence")
