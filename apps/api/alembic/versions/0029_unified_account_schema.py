"""Unified account schema and one-to-one identity invariants.

Revision ID: 0029_unified_account_schema
Revises: 0028_customer_notification_prefs

Downgrade is intentionally refused after any unified credential, email, admin link,
or non-customer user role has been populated. Customer assignments created by the
upgrade are safely removable with the table.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

UUID_T: postgresql.UUID[str] = postgresql.UUID(as_uuid=False)
revision: str = "0029_unified_account_schema"
down_revision: str = "0028_customer_notification_prefs"
branch_labels = None
depends_on = None

BUILTIN_ROLES = {
    name: (str(uuid5(NAMESPACE_URL, f"vpnsale:role:{name}")), label)
    for name, label in (
        ("customer", "Customer"),
        ("reseller", "Reseller"),
        ("support", "Support"),
        ("admin", "Administrator"),
        ("super_admin", "Super Admin"),
    )
}


def _ensure_roles_and_backfill(bind: sa.Connection) -> None:
    for name, (role_id, label) in BUILTIN_ROLES.items():
        bind.execute(
            sa.text("""
            INSERT INTO roles (id, machine_name, display_name, built_in, active,
                               created_at, updated_at)
            VALUES (:id, :name, :label, true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (machine_name) DO NOTHING
        """),
            {"id": role_id, "name": name, "label": label},
        )
    bind.execute(
        sa.text("""
        INSERT INTO user_role_assignments (user_id, role_id, assigned_at)
        SELECT u.id, r.id, CURRENT_TIMESTAMP FROM identity_users u
        JOIN roles r ON r.machine_name = 'customer'
        ON CONFLICT (user_id, role_id) DO NOTHING
    """)
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    duplicate = bind.execute(
        sa.text("""
        SELECT 1 FROM telegram_accounts WHERE user_id IS NOT NULL
        GROUP BY user_id HAVING COUNT(*) > 1 LIMIT 1
    """)
    ).first()
    if duplicate is not None:
        raise RuntimeError("unified account migration refused: duplicate Telegram ownership exists")

    if "account_credentials" not in existing_tables:
        _create_account_credentials()
    if "account_emails" not in existing_tables:
        _create_account_emails()
    admin_columns = {column["name"] for column in inspector.get_columns("admins")}
    if "user_id" not in admin_columns:
        op.add_column("admins", sa.Column("user_id", UUID_T))
        op.create_foreign_key(
            "fk_admins_user_id_identity_users",
            "admins",
            "identity_users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_unique_constraint("uq_admins_user_id", "admins", ["user_id"])
    if "user_role_assignments" not in existing_tables:
        _create_user_role_assignments()
    telegram_index = next(
        (
            index
            for index in inspector.get_indexes("telegram_accounts")
            if index["name"] == "ix_telegram_accounts_user_id"
        ),
        None,
    )
    if telegram_index is None or not telegram_index.get("unique", False):
        if telegram_index is not None:
            op.drop_index("ix_telegram_accounts_user_id", table_name="telegram_accounts")
        op.create_index(
            "ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"], unique=True
        )
    _ensure_roles_and_backfill(bind)


def _create_account_credentials() -> None:
    op.create_table(
        "account_credentials",
        sa.Column("user_id", UUID_T, nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("normalized_username", sa.String(32), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lock_until", sa.DateTime(timezone=True)),
        sa.Column("last_successful_login_at", sa.DateTime(timezone=True)),
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True)),
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "failed_login_count >= 0", name="ck_account_credentials_failed_login_count"
        ),
        sa.CheckConstraint("credential_version > 0", name="ck_account_credentials_version"),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'", name="ck_account_credentials_argon2id"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint(
            "normalized_username", name="uq_account_credentials_normalized_username"
        ),
    )


def _create_account_emails() -> None:
    op.create_table(
        "account_emails",
        sa.Column("id", UUID_T, nullable=False),
        sa.Column("user_id", UUID_T, nullable=False),
        sa.Column("normalized_email", sa.String(320), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_account_emails_user_id"),
        sa.UniqueConstraint("normalized_email", name="uq_account_emails_normalized_email"),
    )


def _create_user_role_assignments() -> None:
    op.create_table(
        "user_role_assignments",
        sa.Column("user_id", UUID_T, nullable=False),
        sa.Column("role_id", UUID_T, nullable=False),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("assigned_by_admin_id", UUID_T),
        sa.ForeignKeyConstraint(["user_id"], ["identity_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_admin_id"], ["admins.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
        sa.UniqueConstraint("user_id", "role_id", name="uq_user_role_assignments_pair"),
    )
    op.create_index("ix_user_role_assignments_role_id", "user_role_assignments", ["role_id"])
    op.create_index(
        "ix_user_role_assignments_assigned_by", "user_role_assignments", ["assigned_by_admin_id"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    unsafe = bind.execute(
        sa.text("""
        SELECT EXISTS (SELECT 1 FROM account_credentials) OR EXISTS (SELECT 1 FROM account_emails)
          OR EXISTS (SELECT 1 FROM admins WHERE user_id IS NOT NULL)
          OR EXISTS (SELECT 1 FROM user_role_assignments ura
                     JOIN roles r ON r.id=ura.role_id
                     WHERE r.machine_name <> 'customer')
    """)
    ).scalar()
    if unsafe:
        raise RuntimeError(
            "unified account downgrade refused: populated account data would be lost"
        )
    op.drop_index("ix_telegram_accounts_user_id", table_name="telegram_accounts")
    op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"])
    op.drop_index("ix_user_role_assignments_assigned_by", table_name="user_role_assignments")
    op.drop_index("ix_user_role_assignments_role_id", table_name="user_role_assignments")
    op.drop_table("user_role_assignments")
    op.drop_constraint("uq_admins_user_id", "admins", type_="unique")
    op.drop_constraint("fk_admins_user_id_identity_users", "admins", type_="foreignkey")
    op.drop_column("admins", "user_id")
    op.drop_table("account_emails")
    op.drop_table("account_credentials")
