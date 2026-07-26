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
from sqlalchemy.engine.interfaces import (
    ReflectedForeignKeyConstraint,
    ReflectedIndex,
    ReflectedUniqueConstraint,
)
from sqlalchemy.engine.reflection import Inspector

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


def _inspector(bind: sa.Connection) -> Inspector:
    """Return a fresh inspector; PostgreSQL catalog results are cached per inspector."""
    return sa.inspect(bind)


def _unique_constraint_columns(item: ReflectedUniqueConstraint) -> tuple[str, ...]:
    return tuple(item.get("column_names") or ())


def _index_columns(item: ReflectedIndex) -> tuple[str, ...]:
    return tuple(name for name in (item.get("column_names") or ()) if isinstance(name, str))


def _foreign_key_columns(item: ReflectedForeignKeyConstraint) -> tuple[str, ...]:
    return tuple(item.get("constrained_columns") or ())


def _single_column_uniqueness(
    inspector: Inspector, table_name: str, column_name: str
) -> list[tuple[str, str]]:
    rules: list[tuple[str, str]] = []
    constraint_names: set[str] = set()
    for constraint in inspector.get_unique_constraints(table_name):
        if _unique_constraint_columns(constraint) == (column_name,):
            name = constraint.get("name")
            if not isinstance(name, str):
                raise RuntimeError("unified account migration refused: unnamed uniqueness rule")
            constraint_names.add(name)
            rules.append(("unique", name))
    for index in inspector.get_indexes(table_name):
        if not index.get("unique") or _index_columns(index) != (column_name,):
            continue
        duplicate = index.get("duplicates_constraint")
        if isinstance(duplicate, str) and duplicate in constraint_names:
            continue
        name = index.get("name")
        if not isinstance(name, str):
            raise RuntimeError("unified account migration refused: unnamed unique index")
        rules.append(("index", name))
    return rules


def _admin_bridge_foreign_keys(
    inspector: Inspector,
) -> list[ReflectedForeignKeyConstraint]:
    return [
        fk
        for fk in inspector.get_foreign_keys("admins")
        if _foreign_key_columns(fk) == ("user_id",)
    ]


def _is_expected_admin_bridge_fk(fk: ReflectedForeignKeyConstraint) -> bool:
    options = fk.get("options")
    ondelete = options.get("ondelete") if options is not None else None
    return (
        fk.get("referred_table") == "identity_users"
        and tuple(fk.get("referred_columns") or ()) == ("id",)
        and (ondelete is None or str(ondelete).upper() in {"RESTRICT", "NO ACTION"})
    )


def _reconcile_admin_bridge(bind: sa.Connection) -> None:
    inspector = _inspector(bind)
    admin_columns = {column["name"]: column for column in inspector.get_columns("admins")}
    if "user_id" not in admin_columns:
        op.add_column("admins", sa.Column("user_id", UUID_T))

    inspector = _inspector(bind)
    user_id_column = next(
        column for column in inspector.get_columns("admins") if column["name"] == "user_id"
    )
    if not user_id_column["nullable"] or not isinstance(user_id_column["type"], postgresql.UUID):
        raise RuntimeError("unified account migration refused: incompatible admin bridge column")
    bridge_fks = _admin_bridge_foreign_keys(inspector)
    if any(not _is_expected_admin_bridge_fk(fk) for fk in bridge_fks) or len(bridge_fks) > 1:
        raise RuntimeError(
            "unified account migration refused: incompatible admin bridge foreign key"
        )
    if not bridge_fks:
        op.create_foreign_key(
            "fk_admins_user_id_identity_users",
            "admins",
            "identity_users",
            ["user_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    uniqueness = _single_column_uniqueness(_inspector(bind), "admins", "user_id")
    if len(uniqueness) > 1:
        raise RuntimeError("unified account migration refused: duplicate admin bridge uniqueness")
    if not uniqueness:
        op.create_unique_constraint("uq_admins_user_id", "admins", ["user_id"])


def _reconcile_telegram_uniqueness(bind: sa.Connection) -> None:
    inspector = _inspector(bind)
    uniqueness = _single_column_uniqueness(inspector, "telegram_accounts", "user_id")
    if len(uniqueness) > 1:
        raise RuntimeError("unified account migration refused: duplicate Telegram ownership rules")
    if uniqueness:
        return
    indexes = {
        index["name"]: index
        for index in inspector.get_indexes("telegram_accounts")
        if isinstance(index.get("name"), str)
    }
    if "ix_telegram_accounts_user_id" in indexes:
        op.drop_index("ix_telegram_accounts_user_id", table_name="telegram_accounts")
    op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"], unique=True)


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
    inspector = _inspector(bind)
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
    _reconcile_admin_bridge(bind)
    if "user_role_assignments" not in existing_tables:
        _create_user_role_assignments()
    _reconcile_telegram_uniqueness(bind)
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
    telegram_uniqueness = _single_column_uniqueness(
        _inspector(bind), "telegram_accounts", "user_id"
    )
    if len(telegram_uniqueness) != 1:
        raise RuntimeError(
            "unified account downgrade refused: Telegram ownership rule is incompatible"
        )
    rule_type, rule_name = telegram_uniqueness[0]
    if rule_type == "unique":
        op.drop_constraint(rule_name, "telegram_accounts", type_="unique")
    else:
        op.drop_index(rule_name, table_name="telegram_accounts")
    remaining_indexes = {
        index["name"] for index in _inspector(bind).get_indexes("telegram_accounts")
    }
    if "ix_telegram_accounts_user_id" not in remaining_indexes:
        op.create_index("ix_telegram_accounts_user_id", "telegram_accounts", ["user_id"])

    # Dropping an owning table removes only that table's constraints and indexes,
    # regardless of whether metadata.create_all supplied alternate object names.
    op.drop_table("user_role_assignments")
    admin_columns = {column["name"] for column in _inspector(bind).get_columns("admins")}
    if "user_id" not in admin_columns:
        raise RuntimeError("unified account downgrade refused: admin bridge column is missing")
    # PostgreSQL removes the foreign key and unique/index dependencies owned by
    # this column; no constraint name assumption or broad CASCADE is required.
    op.drop_column("admins", "user_id")
    op.drop_table("account_emails")
    op.drop_table("account_credentials")
