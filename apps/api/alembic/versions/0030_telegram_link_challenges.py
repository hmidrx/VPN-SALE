"""Add durable, hash-only Telegram account-link challenges.

Revision ID: 0030_telegram_link_challenges
Revises: 0029_unified_account_schema
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_telegram_link_challenges"
down_revision: str = "0029_unified_account_schema"
branch_labels = None
depends_on = None
UUID_T: postgresql.UUID[str] = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "telegram_link_challenges",
        sa.Column("id", UUID_T, primary_key=True),
        sa.Column(
            "user_id",
            UUID_T,
            sa.ForeignKey("identity_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "initiating_session_id",
            UUID_T,
            sa.ForeignKey("customer_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("token_hash", sa.String(96), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("failed_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("failed_attempt_count >= 0", name="ck_telegram_link_failed_attempts"),
    )
    op.create_index(
        "ix_telegram_link_challenges_user_active",
        "telegram_link_challenges",
        ["user_id", "consumed_at"],
    )
    op.create_index(
        "ix_telegram_link_challenges_expires_at",
        "telegram_link_challenges",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_link_challenges_expires_at", table_name="telegram_link_challenges")
    op.drop_index("ix_telegram_link_challenges_user_active", table_name="telegram_link_challenges")
    op.drop_table("telegram_link_challenges")
