"""Durable provider fulfillment identity and retry state.

Revision ID: 0037_real_fulfillment
Revises: 0036_telegram_purchase_idem
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0037_real_fulfillment"
down_revision: str = "0036_telegram_purchase_idem"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("services", "starts_at", nullable=True)
    op.create_table(
        "fulfillment_allocation_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "product_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("product_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("location_code", sa.String(64), nullable=False),
        sa.Column("quality_code", sa.String(64), nullable=False),
        sa.Column(
            "allocation_target_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("allocation_targets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "product_version_id",
            "location_code",
            "quality_code",
            name="uq_fulfillment_binding_purchase_target",
        ),
    )
    op.add_column(
        "service_fulfillment_requests",
        sa.Column("remote_identity_uuid", postgresql.UUID(as_uuid=False), nullable=True),
    )
    op.execute(
        "update service_fulfillment_requests set remote_identity_uuid = "
        "md5('fulfillment:' || id::text)::uuid where remote_identity_uuid is null"
    )
    op.alter_column("service_fulfillment_requests", "remote_identity_uuid", nullable=False)
    op.add_column(
        "service_fulfillment_requests",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("service_fulfillment_requests", sa.Column("failure_category", sa.String(64)))
    op.add_column(
        "service_fulfillment_requests", sa.Column("next_attempt_at", sa.DateTime(timezone=True))
    )
    op.create_index(
        "ix_service_fulfillment_retry",
        "service_fulfillment_requests",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_fulfillment_retry", table_name="service_fulfillment_requests")
    op.drop_column("service_fulfillment_requests", "next_attempt_at")
    op.drop_column("service_fulfillment_requests", "failure_category")
    op.drop_column("service_fulfillment_requests", "attempt_count")
    op.drop_column("service_fulfillment_requests", "remote_identity_uuid")
    op.drop_table("fulfillment_allocation_bindings")
    op.alter_column("services", "starts_at", nullable=False)
