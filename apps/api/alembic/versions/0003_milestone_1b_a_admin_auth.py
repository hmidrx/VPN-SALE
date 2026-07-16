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


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    if not _has_table(table_name):
        return set()
    return {
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    # Revision 0002 historically used live SQLAlchemy metadata. On a clean
    # checkout that can expose newer model fields before this revision runs.
    # Guard each additive operation so both clean installs and upgrades from a
    # genuine Milestone 1A database converge on the same schema.
    admin_session_columns = _column_names("admin_sessions")
    if "consumed_at" not in admin_session_columns:
        op.add_column(
            "admin_sessions",
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "csrf_token_hash" not in admin_session_columns:
        op.add_column(
            "admin_sessions",
            sa.Column("csrf_token_hash", sa.String(length=96), nullable=True),
        )

    totp_columns = _column_names("totp_credentials")
    if "confirmed_at" not in totp_columns:
        op.add_column(
            "totp_credentials",
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "pending_expires_at" not in totp_columns:
        op.add_column(
            "totp_credentials",
            sa.Column("pending_expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "last_accepted_time_step" not in totp_columns:
        op.add_column(
            "totp_credentials",
            sa.Column("last_accepted_time_step", sa.Integer(), nullable=True),
        )

    if not _has_table("admin_mfa_challenges"):
        op.create_table(
            "admin_mfa_challenges",
            sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
            sa.Column("admin_id", postgresql.UUID(as_uuid=False), nullable=False),
            sa.Column("challenge_hash", sa.String(length=96), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "ip_metadata",
                sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                nullable=True,
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
    if "ix_admin_mfa_challenges_admin" not in _index_names("admin_mfa_challenges"):
        op.create_index(
            "ix_admin_mfa_challenges_admin",
            "admin_mfa_challenges",
            ["admin_id", "expires_at"],
        )


def downgrade() -> None:
    if "ix_admin_mfa_challenges_admin" in _index_names("admin_mfa_challenges"):
        op.drop_index(
            "ix_admin_mfa_challenges_admin", table_name="admin_mfa_challenges"
        )
    if _has_table("admin_mfa_challenges"):
        op.drop_table("admin_mfa_challenges")

    totp_columns = _column_names("totp_credentials")
    if "last_accepted_time_step" in totp_columns:
        op.drop_column("totp_credentials", "last_accepted_time_step")
    if "pending_expires_at" in totp_columns:
        op.drop_column("totp_credentials", "pending_expires_at")
    if "confirmed_at" in totp_columns:
        op.drop_column("totp_credentials", "confirmed_at")

    admin_session_columns = _column_names("admin_sessions")
    if "csrf_token_hash" in admin_session_columns:
        op.drop_column("admin_sessions", "csrf_token_hash")
    if "consumed_at" in admin_session_columns:
        op.drop_column("admin_sessions", "consumed_at")
