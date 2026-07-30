"""Add encrypted, versioned manual top-up destinations.

Revision ID: 0035_manual_topup_destinations
Revises: 0034_manual_topup_delivery
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0035_manual_topup_destinations"
down_revision = "0034_manual_topup_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_topup_destination_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("reference", sa.String(48), nullable=False, unique=True),
        sa.Column("encrypted_card_number", sa.Text(), nullable=False),
        sa.Column("encrypted_card_holder_name", sa.Text()),
        sa.Column("card_last4", sa.String(4), nullable=False),
        sa.Column("encryption_key_version", sa.String(32), nullable=False),
        sa.Column(
            "created_by_admin_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("card_last4 ~ '^[0-9]{4}$'", name="ck_manual_topup_destination_last4"),
    )
    op.create_table(
        "manual_topup_destination_settings",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column(
            "active_destination_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("manual_topup_destination_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "customer_display_enabled", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_by_admin_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("admins.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("key = 'default'", name="ck_manual_topup_destination_singleton"),
        sa.CheckConstraint("version > 0", name="ck_manual_topup_destination_settings_version"),
        sa.CheckConstraint(
            "NOT customer_display_enabled OR active_destination_version_id IS NOT NULL",
            name="ck_manual_topup_destination_enabled_requires_card",
        ),
    )
    op.execute("INSERT INTO manual_topup_destination_settings (key) VALUES ('default')")
    op.add_column(
        "manual_topup_requests", sa.Column("destination_version_id", postgresql.UUID(as_uuid=False))
    )
    op.create_foreign_key(
        "fk_manual_topup_request_destination",
        "manual_topup_requests",
        "manual_topup_destination_versions",
        ["destination_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_manual_topup_request_destination", "manual_topup_requests", ["destination_version_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_manual_topup_request_destination", table_name="manual_topup_requests")
    op.drop_constraint(
        "fk_manual_topup_request_destination", "manual_topup_requests", type_="foreignkey"
    )
    op.drop_column("manual_topup_requests", "destination_version_id")
    op.drop_table("manual_topup_destination_settings")
    op.drop_table("manual_topup_destination_versions")
