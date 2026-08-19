"""Add the bounded Telegram operator health permission.

Revision ID: 0049_tg_operator_perm
Revises: 0048_worker_heartbeat
Create Date: 2026-08-18
"""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049_tg_operator_perm"
down_revision: str = "0048_worker_heartbeat"
branch_labels: None = None
depends_on: None = None

_PERMISSION = "ops.telegram.read"


def upgrade() -> None:
    permissions = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String(length=120)),
        sa.column("description", sa.String(length=240)),
    )
    op.execute(
        postgresql.insert(permissions)
        .values(
            id=uuid4(),
            code=_PERMISSION,
            description="Read bounded operational health from the linked Telegram operator path",
        )
        .on_conflict_do_nothing(index_elements=["code"])
    )
    op.execute(
        sa.text(
            """
            insert into role_permissions (role_id, permission_id)
            select roles.id, permissions.id
            from roles
            join permissions on permissions.code = :permission
            where roles.machine_name = 'super_admin'
            on conflict do nothing
            """
        ).bindparams(permission=_PERMISSION)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            delete from role_permissions
            where permission_id in (select id from permissions where code = :permission)
            """
        ).bindparams(permission=_PERMISSION)
    )
    op.execute(
        sa.text("delete from permissions where code = :permission").bindparams(
            permission=_PERMISSION
        )
    )
