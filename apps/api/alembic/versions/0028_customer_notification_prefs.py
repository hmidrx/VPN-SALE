"""customer notification preferences

Revision ID: 0028_customer_notification_prefs
Revises: 0027_m7b_prod_rollout
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

UUID_T: postgresql.UUID[str] = postgresql.UUID(as_uuid=False)

revision: str = "0028_customer_notification_prefs"
down_revision: str = "0027_m7b_prod_rollout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_notification_preferences",
        sa.Column("id", UUID_T, nullable=False),
        sa.Column("customer_id", UUID_T, nullable=False),
        sa.Column("service_expiry_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("low_traffic_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("payment_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("support_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("announcements_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_customer_notification_preferences_customer"),
    )
    op.create_table(
        "customer_notification_preference_idempotency",
        sa.Column("id", UUID_T, nullable=False),
        sa.Column("customer_id", UUID_T, nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "customer_id", "idempotency_key", name="uq_customer_notification_pref_idem"
        ),
    )


def downgrade() -> None:
    op.drop_table("customer_notification_preference_idempotency")
    op.drop_table("customer_notification_preferences")
