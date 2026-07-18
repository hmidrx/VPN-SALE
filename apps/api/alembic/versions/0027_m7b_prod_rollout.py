"""Milestone 7-B controlled production rollout

Revision ID: 0027_m7b_prod_rollout
Revises: 0026_m7a2_quality_release
Create Date: 2026-07-18 00:00:00.000000+00:00
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_m7b_prod_rollout"
down_revision: str = "0026_m7a2_quality_release"
branch_labels: None = None
depends_on: None = None

_PERMISSIONS: tuple[tuple[uuid.UUID, str, str], ...] = (
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000001"),
        "production_releases.read",
        "Read production release console",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000002"),
        "production_releases.manage",
        "Manage production release plans",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000003"),
        "production_releases.request",
        "Request production release approval",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000004"),
        "production_releases.approve",
        "Approve production releases",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000005"),
        "production_releases.deploy",
        "Execute protected production deployment workflow",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000006"),
        "production_releases.start_canary",
        "Start production canary phases",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000007"),
        "production_releases.advance",
        "Advance production rollout phases",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000008"),
        "production_releases.pause",
        "Pause production rollouts",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-000000000009"),
        "production_releases.resume",
        "Resume production rollouts",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-00000000000a"),
        "production_releases.rollback",
        "Execute production rollback",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-00000000000b"),
        "production_releases.manage_cohorts",
        "Manage production release cohorts",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-00000000000c"),
        "production_releases.manage_hypercare",
        "Manage production hypercare",
    ),
    (
        uuid.UUID("f4ea0c1d-7b00-4000-9000-00000000000d"),
        "production_releases.review_completion",
        "Review production completion reports",
    ),
)


def upgrade() -> None:
    op.create_table(
        "production_release_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(length=80), nullable=False, unique=True),
        sa.Column("owner_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "status in ('DRAFT','PUBLISHED','APPROVED','EXPIRED','CANCELLED')",
            name="ck_prod_release_plans_status",
        ),
    )
    op.create_table(
        "production_release_plan_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rc_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rc_provenance_digest", sa.String(length=64), nullable=False),
        sa.Column("source_commit_sha", sa.String(length=40), nullable=False),
        sa.Column("application_version", sa.String(length=80), nullable=False),
        sa.Column("artifact_digest", sa.String(length=128), nullable=False),
        sa.Column("migration_head", sa.String(length=64), nullable=False),
        sa.Column("provider_contract_digest", sa.String(length=128), nullable=False),
        sa.Column("renderer_digest", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("deployment_target_reference", sa.String(length=120), nullable=False),
        sa.Column(
            "approval_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "rollout_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["production_release_plans.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "plan_id", "version", name="uq_prod_release_plan_versions_plan_version"
        ),
        sa.CheckConstraint(
            "environment in ('CI','STAGING','PRODUCTION')",
            name="ck_prod_release_plan_versions_environment",
        ),
    )
    op.create_table(
        "production_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(length=80), nullable=False, unique=True),
        sa.Column("plan_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requester_actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("optimistic_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["plan_version_id"], ["production_release_plan_versions.id"]),
    )
    for table in (
        "production_release_approvals",
        "production_release_gates",
        "production_release_phases",
        "production_release_cohorts",
        "production_release_health_evaluations",
        "production_release_pauses",
        "production_release_rollbacks",
        "production_release_incidents",
        "production_release_hypercare",
        "production_release_reconciliations",
        "production_release_reports",
    ):
        op.create_table(
            table,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("release_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("record_type", sa.String(length=48), nullable=False),
            sa.Column("state", sa.String(length=48), nullable=False),
            sa.Column("safe_reference", sa.String(length=160), nullable=False),
            sa.Column("digest_sha256", sa.String(length=64), nullable=False),
            sa.Column(
                "sanitized_summary",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["release_id"], ["production_releases.id"], ondelete="CASCADE"),
        )
        op.create_index(f"ix_{table}_release_created", table, ["release_id", "created_at"])
    bind = op.get_bind()
    permission_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String()),
        sa.column("description", sa.String()),
    )
    for permission_id, code, description in _PERMISSIONS:
        bind.execute(
            postgresql.insert(permission_table)
            .values(id=permission_id, code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _, code, _ in _PERMISSIONS:
        bind.execute(
            sa.text("delete from permissions where code = :code").bindparams(
                sa.bindparam("code", type_=sa.String())
            ),
            {"code": code},
        )
    for table in reversed(
        (
            "production_release_approvals",
            "production_release_gates",
            "production_release_phases",
            "production_release_cohorts",
            "production_release_health_evaluations",
            "production_release_pauses",
            "production_release_rollbacks",
            "production_release_incidents",
            "production_release_hypercare",
            "production_release_reconciliations",
            "production_release_reports",
        )
    ):
        op.drop_index(f"ix_{table}_release_created", table_name=table)
        op.drop_table(table)
    op.drop_table("production_releases")
    op.drop_table("production_release_plan_versions")
    op.drop_table("production_release_plans")
