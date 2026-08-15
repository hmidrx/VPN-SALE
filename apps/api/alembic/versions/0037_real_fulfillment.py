"""Durable provider fulfillment identity, retry, binding and entitlement-clock state.

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


UUID_TYPE = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.alter_column(
        "services", "starts_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.add_column(
        "service_fulfillment_requests",
        sa.Column("remote_identity_uuid", UUID_TYPE, nullable=True),
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

    op.create_table(
        "fulfillment_target_bindings",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column("product_version_id", UUID_TYPE, nullable=False),
        sa.Column("location_code", sa.String(80), nullable=False),
        sa.Column("quality_code", sa.String(80), nullable=False),
        sa.Column(
            "allocation_target_id",
            UUID_TYPE,
            sa.ForeignKey("allocation_targets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "capability_codes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "product_version_id",
            "location_code",
            "quality_code",
            "allocation_target_id",
            name="uq_fulfillment_target_binding_selection_target",
        ),
    )
    op.create_index(
        "ix_fulfillment_target_binding_lookup",
        "fulfillment_target_bindings",
        ["product_version_id", "location_code", "quality_code", "active"],
    )

    op.create_table(
        "fulfillment_entitlement_clocks",
        sa.Column(
            "fulfillment_request_id",
            UUID_TYPE,
            sa.ForeignKey("service_fulfillment_requests.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.execute("update services set starts_at = created_at where starts_at is null")
    op.alter_column(
        "services", "starts_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.drop_table("fulfillment_entitlement_clocks")
    op.drop_index("ix_fulfillment_target_binding_lookup", table_name="fulfillment_target_bindings")
    op.drop_table("fulfillment_target_bindings")
    op.drop_index("ix_service_fulfillment_retry", table_name="service_fulfillment_requests")
    op.drop_column("service_fulfillment_requests", "next_attempt_at")
    op.drop_column("service_fulfillment_requests", "failure_category")
    op.drop_column("service_fulfillment_requests", "attempt_count")
    op.drop_column("service_fulfillment_requests", "remote_identity_uuid")
