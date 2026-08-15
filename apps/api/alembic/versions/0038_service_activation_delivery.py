"""Durable service activation attempts and encrypted customer delivery material.

Revision ID: 0038_service_activation_delivery
Revises: 0037_real_fulfillment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_service_activation_delivery"
down_revision: str = "0037_real_fulfillment"
branch_labels = None
depends_on = None

UUID_TYPE = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "service_activation_requests",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "service_id",
            UUID_TYPE,
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(96)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("failure_category", sa.String(64)),
        sa.Column("result_code", sa.String(80)),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column("causation_id", sa.String(96), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("service_id", name="uq_service_activation_service"),
        sa.CheckConstraint(
            "status in ('PENDING','CLAIMED','RETRY_PENDING','BLOCKED','OPERATOR_REVIEW','SUCCEEDED')",
            name="ck_service_activation_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_service_activation_attempt_count"),
    )
    op.create_index(
        "ix_service_activation_retry",
        "service_activation_requests",
        ["status", "next_attempt_at", "lease_expires_at"],
    )

    op.create_table(
        "service_deliveries",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "service_id",
            UUID_TYPE,
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(32), nullable=False, server_default="URI_LIST"),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(32), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("service_id", name="uq_service_delivery_service"),
        sa.CheckConstraint("item_count > 0", name="ck_service_delivery_item_count"),
        sa.CheckConstraint(
            "status in ('PREPARED','DELIVERED')",
            name="ck_service_delivery_status",
        ),
    )
    op.create_index(
        "ix_service_delivery_status_created",
        "service_deliveries",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_delivery_status_created", table_name="service_deliveries")
    op.drop_table("service_deliveries")
    op.drop_index("ix_service_activation_retry", table_name="service_activation_requests")
    op.drop_table("service_activation_requests")
