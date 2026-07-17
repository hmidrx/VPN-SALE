"""Milestone 1D-A identity administration backend."""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_milestone_1d_a"
down_revision: str = "0004_milestone_1c_customer_auth"
branch_labels = None
depends_on = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {str(c["name"]) for c in insp.get_columns(table)}


def _idx(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {str(i["name"]) for i in insp.get_indexes(table) if i.get("name")}


def _fks(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {str(f["name"]) for f in insp.get_foreign_keys(table) if f.get("name")}


def _add_col(table: str, column: sa.Column[object]) -> None:
    if column.name not in _cols(table):
        op.add_column(table, column)


def upgrade() -> None:
    _add_col("admins", sa.Column("invitation_token_hash", sa.String(length=96), nullable=True))
    _add_col(
        "admins", sa.Column("invitation_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_col(
        "admins", sa.Column("invitation_revoked_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_col(
        "admins", sa.Column("invitation_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_col("roles", sa.Column("description", sa.String(length=240), nullable=True))
    _add_col(
        "roles", sa.Column("built_in", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    _add_col("roles", sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
    _add_col(
        "roles",
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    _add_col(
        "roles",
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    if "ix_roles_active" not in _idx("roles"):
        op.create_index("ix_roles_active", "roles", ["active"])
    op.execute(
        "update roles set built_in = true where machine_name in "
        "('super_admin','security_admin','support_viewer','auditor')"
    )
    _add_col(
        "security_events",
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="INFO"),
    )
    _add_col(
        "security_events",
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
    )
    _add_col(
        "security_events", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True)
    )
    _add_col(
        "security_events",
        sa.Column("acknowledged_by_admin_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    _add_col("security_events", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    _add_col(
        "security_events",
        sa.Column("resolved_by_admin_id", postgresql.UUID(as_uuid=False), nullable=True),
    )
    _add_col("security_events", sa.Column("resolution_note", sa.String(length=500), nullable=True))
    fks = _fks("security_events")
    if "fk_security_events_ack_admin" not in fks:
        op.create_foreign_key(
            "fk_security_events_ack_admin",
            "security_events",
            "admins",
            ["acknowledged_by_admin_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if "fk_security_events_res_admin" not in fks:
        op.create_foreign_key(
            "fk_security_events_res_admin",
            "security_events",
            "admins",
            ["resolved_by_admin_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    if "ix_security_events_status" not in _idx("security_events"):
        op.create_index("ix_security_events_status", "security_events", ["status"])
    permissions: Sequence[tuple[str, str]] = (
        ("admins.invite", "Invite administrators"),
        ("admins.unlock", "Unlock administrators"),
        ("users.block", "Block users"),
        ("users.activate", "Activate users"),
        ("users.deactivate", "Deactivate users"),
        ("security.read", "Read security events"),
        ("security.acknowledge", "Acknowledge security events"),
    )
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String(length=120)),
        sa.column("description", sa.String(length=240)),
    )
    for code, desc in permissions:
        stmt = (
            postgresql.insert(permissions_table)
            .values(id=uuid4(), code=code, description=desc)
            .on_conflict_do_nothing(index_elements=["code"])
        )
        op.execute(stmt)


def downgrade() -> None:
    for code in (
        "admins.invite",
        "admins.unlock",
        "users.block",
        "users.activate",
        "users.deactivate",
        "security.read",
        "security.acknowledge",
    ):
        op.execute(sa.text("delete from permissions where code = :code").bindparams(code=code))
    if "ix_security_events_status" in _idx("security_events"):
        op.drop_index("ix_security_events_status", table_name="security_events")
    if "fk_security_events_res_admin" in _fks("security_events"):
        op.drop_constraint("fk_security_events_res_admin", "security_events", type_="foreignkey")
    if "fk_security_events_ack_admin" in _fks("security_events"):
        op.drop_constraint("fk_security_events_ack_admin", "security_events", type_="foreignkey")
    for col in (
        "resolution_note",
        "resolved_by_admin_id",
        "resolved_at",
        "acknowledged_by_admin_id",
        "acknowledged_at",
        "status",
        "severity",
    ):
        if col in _cols("security_events"):
            op.drop_column("security_events", col)
    if "ix_roles_active" in _idx("roles"):
        op.drop_index("ix_roles_active", table_name="roles")
    for col in ("updated_at", "created_at", "active", "built_in", "description"):
        if col in _cols("roles"):
            op.drop_column("roles", col)
    for col in (
        "invitation_accepted_at",
        "invitation_revoked_at",
        "invitation_expires_at",
        "invitation_token_hash",
    ):
        if col in _cols("admins"):
            op.drop_column("admins", col)
