"""Milestone 5-B customer administration platform."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_milestone_5b_customers"
down_revision: str = "0011_milestone_5a_config"
branch_labels = None
depends_on = None

PERMISSIONS = (
    (
        "customers.read",
        "Read customer directory and profiles",
        UUID("5b000000-0000-4000-8000-000000000001"),
    ),
    (
        "customers.manage",
        "Manage customer administration",
        UUID("5b000000-0000-4000-8000-000000000002"),
    ),
    (
        "customers.manage_status",
        "Manage customer lifecycle status",
        UUID("5b000000-0000-4000-8000-000000000003"),
    ),
    (
        "customers.manage_security",
        "Manage customer sessions and security",
        UUID("5b000000-0000-4000-8000-000000000004"),
    ),
    (
        "customers.notes.read",
        "Read internal customer notes",
        UUID("5b000000-0000-4000-8000-000000000005"),
    ),
    (
        "customers.notes.manage",
        "Manage internal customer notes",
        UUID("5b000000-0000-4000-8000-000000000006"),
    ),
    ("customers.tags.read", "Read customer tags", UUID("5b000000-0000-4000-8000-000000000007")),
    ("customers.tags.manage", "Manage customer tags", UUID("5b000000-0000-4000-8000-000000000008")),
    (
        "customers.bulk.read",
        "Read customer bulk operations",
        UUID("5b000000-0000-4000-8000-000000000009"),
    ),
    (
        "customers.bulk.manage",
        "Manage customer bulk operations",
        UUID("5b000000-0000-4000-8000-000000000010"),
    ),
    (
        "customers.export",
        "Export allowlisted customer data",
        UUID("5b000000-0000-4000-8000-000000000011"),
    ),
    (
        "customer_wallets.read",
        "Read customer wallet inspection",
        UUID("5b000000-0000-4000-8000-000000000012"),
    ),
    (
        "customer_wallets.freeze",
        "Freeze and unfreeze customer wallets",
        UUID("5b000000-0000-4000-8000-000000000013"),
    ),
    (
        "customer_wallets.adjust",
        "Request customer wallet adjustments",
        UUID("5b000000-0000-4000-8000-000000000014"),
    ),
    (
        "customer_wallets.adjust_cash",
        "Request cash-bucket customer wallet adjustments",
        UUID("5b000000-0000-4000-8000-000000000015"),
    ),
    (
        "customer_wallets.approve_adjustment",
        "Approve high-risk customer wallet adjustments",
        UUID("5b000000-0000-4000-8000-000000000016"),
    ),
)


def _seed_permissions() -> None:
    p = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    for code, desc, pid in PERMISSIONS:
        op.execute(
            postgresql.insert(p)
            .values(id=pid, code=code, description=desc)
            .on_conflict_do_update(index_elements=["code"], set_={"description": desc})
        )
        op.execute(
            sa.text(
                "insert into role_permissions (role_id, permission_id) "
                "select roles.id, :pid from roles "
                "where machine_name = 'super_admin' on conflict do nothing"
            ).bindparams(pid=str(pid))
        )


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "customer_admin_notes",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("note_type", sa.String(32), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "note_type in ('GENERAL','FINANCIAL','SECURITY','OPERATIONS',"
            "'SUPPORT_PREPARATION','COMPLIANCE')",
            name="ck_customer_notes_type",
        ),
        sa.CheckConstraint("version > 0", name="ck_customer_notes_version"),
    )
    op.create_index(
        "ix_customer_notes_customer", "customer_admin_notes", ["customer_id", "created_at"]
    )
    op.create_table(
        "customer_admin_note_history",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "note_id",
            uuid,
            sa.ForeignKey("customer_admin_notes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "changed_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "customer_admin_tags",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name_i18n", jsonb, nullable=False),
        sa.Column("description_i18n", jsonb, nullable=False),
        sa.Column("color_token", sa.String(32), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("code", name="uq_customer_tags_code"),
    )
    op.create_index("ix_customer_tags_active", "customer_admin_tags", ["active"])
    op.create_table(
        "customer_admin_tag_assignments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tag_id",
            uuid,
            sa.ForeignKey("customer_admin_tags.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("customer_id", "tag_id", name="uq_customer_tag_assignment"),
    )
    op.create_index(
        "ix_customer_tag_assignments_customer", "customer_admin_tag_assignments", ["customer_id"]
    )
    op.create_index("ix_customer_tag_assignments_tag", "customer_admin_tag_assignments", ["tag_id"])
    op.create_table(
        "customer_admin_saved_views",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "owner_admin_id", uuid, sa.ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="PERSONAL"),
        sa.Column("filters", jsonb, nullable=False),
        sa.Column("sort", sa.String(32), nullable=False, server_default="created_desc"),
        sa.Column("columns", jsonb, nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "visibility in ('PERSONAL','SHARED')", name="ck_customer_views_visibility"
        ),
    )
    op.create_index("ix_customer_views_owner", "customer_admin_saved_views", ["owner_admin_id"])
    op.create_table(
        "customer_admin_adjustment_requests",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("bucket_type", sa.String(32), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(48), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("explanation", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING_APPROVAL"),
        sa.Column("high_risk", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "requested_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approved_by_admin_id", uuid, sa.ForeignKey("admins.id", ondelete="RESTRICT")),
        sa.Column(
            "journal_entry_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")
        ),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "requested_by_admin_id", "idempotency_key_hash", name="uq_customer_adjustment_idem"
        ),
        sa.CheckConstraint("amount_rial > 0", name="ck_customer_adjustment_amount"),
        sa.CheckConstraint(
            "direction in ('CREDIT','DEBIT')", name="ck_customer_adjustment_direction"
        ),
    )
    op.create_index(
        "ix_customer_adjustments_customer",
        "customer_admin_adjustment_requests",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_customer_adjustments_status", "customer_admin_adjustment_requests", ["status"]
    )
    op.create_table(
        "customer_admin_export_jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "requested_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="QUEUED"),
        sa.Column("file_format", sa.String(8), nullable=False, server_default="CSV"),
        sa.Column("filters", jsonb, nullable=False),
        sa.Column("fields", jsonb, nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("download_reference_hash", sa.String(64)),
        sa.Column("content", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_customer_exports_admin_status",
        "customer_admin_export_jobs",
        ["requested_by_admin_id", "status"],
    )
    op.create_table(
        "customer_admin_bulk_jobs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "requested_by_admin_id",
            uuid,
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("parameters", jsonb, nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "requested_by_admin_id", "idempotency_key_hash", name="uq_customer_bulk_idem"
        ),
    )
    op.create_index("ix_customer_bulk_status", "customer_admin_bulk_jobs", ["status"])
    op.create_table(
        "customer_admin_bulk_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "job_id",
            uuid,
            sa.ForeignKey("customer_admin_bulk_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
        sa.Column("result", jsonb, nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("job_id", "customer_id", name="uq_customer_bulk_item"),
        sa.UniqueConstraint("job_id", "idempotency_key_hash", name="uq_customer_bulk_item_idem"),
    )
    op.create_index("ix_customer_bulk_items_job", "customer_admin_bulk_items", ["job_id", "status"])
    _seed_permissions()


def downgrade() -> None:
    for t in [
        "customer_admin_bulk_items",
        "customer_admin_bulk_jobs",
        "customer_admin_export_jobs",
        "customer_admin_adjustment_requests",
        "customer_admin_saved_views",
        "customer_admin_tag_assignments",
        "customer_admin_tags",
        "customer_admin_note_history",
        "customer_admin_notes",
    ]:
        op.drop_table(t)
    p = sa.table("permissions", sa.column("code", sa.String))
    op.execute(p.delete().where(p.c.code.in_([x[0] for x in PERMISSIONS])))
