"""Enable repeated review cycles and register PAY-1B permissions.

Revision ID: 0033_manual_topup_application
Revises: 0032_manual_card_topups
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_manual_topup_application"
down_revision: str = "0032_manual_card_topups"
branch_labels = None
depends_on = None

PERMISSIONS = (
    (
        "7d752c8e-c118-4b8c-a000-000000000001",
        "manual_topups.read",
        "Read manual top-up evidence and review queue",
    ),
    (
        "7d752c8e-c118-4b8c-a000-000000000002",
        "manual_topups.review",
        "Review manual top-up requests",
    ),
    (
        "7d752c8e-c118-4b8c-a000-000000000003",
        "manual_topups.message",
        "Send customer-visible manual top-up messages",
    ),
    (
        "7d752c8e-c118-4b8c-a000-000000000004",
        "manual_topups.override_amount",
        "Approve manual top-ups with amount overrides",
    ),
)


def upgrade() -> None:
    op.drop_constraint(
        "uq_manual_topup_decision_request_kind", "manual_topup_decisions", type_="unique"
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=False)),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        permissions, [{"id": row[0], "code": row[1], "description": row[2]} for row in PERMISSIONS]
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_manual_topup_decision_request_kind",
        "manual_topup_decisions",
        ["request_id", "decision"],
    )
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM permissions WHERE code IN (:p1, :p2, :p3, :p4)"),
        {
            "p1": PERMISSIONS[0][1],
            "p2": PERMISSIONS[1][1],
            "p3": PERMISSIONS[2][1],
            "p4": PERMISSIONS[3][1],
        },
    )
