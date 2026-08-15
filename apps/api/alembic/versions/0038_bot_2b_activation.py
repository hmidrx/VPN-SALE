"""BOT-2B durable activation attempts, delivery records and state transitions.

Revision ID: 0038_bot_2b_activation
Revises: 0037_real_fulfillment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_bot_2b_activation"
down_revision: str = "0037_real_fulfillment"
branch_labels = None
depends_on = None
UUID_TYPE = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "service_activation_attempts",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "service_id",
            UUID_TYPE,
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activation_attempt_id", sa.String(160), nullable=False),
        sa.Column("activation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activation_status", sa.String(32), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("activation_failure_category", sa.String(64)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("service_id", name="uq_service_activation_attempt_service"),
        sa.UniqueConstraint("activation_attempt_id", name="uq_service_activation_attempt_identity"),
    )
    op.create_index(
        "ix_service_activation_claim",
        "service_activation_attempts",
        ["activation_status", "next_retry_at", "lease_expires_at"],
    )
    op.create_table(
        "service_delivery_records",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "service_id",
            UUID_TYPE,
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("delivery_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("delivery_payload_reference", sa.String(160), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("service_id", name="uq_service_delivery_record_service"),
        sa.UniqueConstraint(
            "delivery_payload_reference", name="uq_service_delivery_payload_reference"
        ),
    )
    op.create_index(
        "ix_service_delivery_ready", "service_delivery_records", ["service_id", "delivery_ready"]
    )


def downgrade() -> None:
    op.drop_index("ix_service_delivery_ready", table_name="service_delivery_records")
    op.drop_table("service_delivery_records")
    op.drop_index("ix_service_activation_claim", table_name="service_activation_attempts")
    op.drop_table("service_activation_attempts")
