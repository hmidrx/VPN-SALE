"""Milestone 7-A2 quality and release hardening

Revision ID: 0026_m7a2_quality_release
Revises: 0025_m7a1_operations
Create Date: 2026-07-18 00:00:00.000000+00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_m7a2_quality_release"
down_revision: str = "0025_m7a1_operations"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "quality_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evidence_kind", sa.String(length=48), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False),
        sa.Column("gate_name", sa.String(length=48), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("safe_reference", sa.String(length=160), nullable=False),
        sa.Column("digest_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "sanitized_summary",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("finalized", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "profile in ('CI_SAFE','LOCAL_ISOLATED','STAGING_STANDARD',"
            "'STAGING_LOAD','STAGING_SECURITY','STAGING_CHAOS')",
            name="ck_quality_evidence_profile",
        ),
        sa.CheckConstraint(
            "state in ('NOT_RUN','RUNNING','PASSED','PASSED_WITH_LIMITATIONS',"
            "'FAILED','BLOCKED','EXPIRED')",
            name="ck_quality_evidence_state",
        ),
    )
    op.create_index(
        "ix_quality_evidence_kind_profile_time",
        "quality_evidence",
        ["evidence_kind", "profile", "created_at"],
    )
    op.create_table(
        "release_defects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(length=40), nullable=False, unique=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("component", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("reproduction", sa.Text(), nullable=False),
        sa.Column("expected_behavior", sa.Text(), nullable=False),
        sa.Column("observed_behavior", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("correction_reference", sa.String(length=160), nullable=True),
        sa.Column("regression_test_reference", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=80), nullable=False),
        sa.Column("release_blocker", sa.Boolean(), nullable=False),
        sa.Column("residual_risk", sa.Text(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fixed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "severity in ('CRITICAL','HIGH','MEDIUM','LOW')", name="ck_release_defects_severity"
        ),
        sa.CheckConstraint(
            "status in ('OPEN','FIXED_PENDING_VERIFICATION','VERIFIED','DEFERRED')",
            name="ck_release_defects_status",
        ),
    )
    op.create_index("ix_release_defects_severity_status", "release_defects", ["severity", "status"])


def downgrade() -> None:
    op.drop_index("ix_release_defects_severity_status", table_name="release_defects")
    op.drop_table("release_defects")
    op.drop_index("ix_quality_evidence_kind_profile_time", table_name="quality_evidence")
    op.drop_table("quality_evidence")
