"""milestone 1b-a admin auth
Revision ID: 0003_milestone_1b_a_admin_auth
Revises: 0002_milestone_1a_identity
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_milestone_1b_a_admin_auth"
down_revision: str | None = "0002_milestone_1a_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "admin_sessions", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "admin_sessions", sa.Column("csrf_token_hash", sa.String(length=96), nullable=True)
    )
    op.add_column(
        "totp_credentials", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "totp_credentials",
        sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "totp_credentials", sa.Column("last_accepted_time_step", sa.Integer(), nullable=True)
    )
    op.create_table(
        "admin_mfa_challenges",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("admin_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("challenge_hash", sa.String(length=96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ip_metadata", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True
        ),
        sa.Column(
            "user_agent_metadata",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("challenge_hash", name="uq_admin_mfa_challenges_hash"),
    )
    op.create_index(
        "ix_admin_mfa_challenges_admin", "admin_mfa_challenges", ["admin_id", "expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_admin_mfa_challenges_admin", table_name="admin_mfa_challenges")
    op.drop_table("admin_mfa_challenges")
    op.drop_column("totp_credentials", "last_accepted_time_step")
    op.drop_column("totp_credentials", "pending_expires_at")
    op.drop_column("totp_credentials", "confirmed_at")
    op.drop_column("admin_sessions", "csrf_token_hash")
    op.drop_column("admin_sessions", "consumed_at")
