"""milestone 1c-a customer auth
Revision ID: 0004_milestone_1c_a_customer_auth
Revises: 0003_milestone_1b_a_admin_auth
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_milestone_1c_a_customer_auth"
down_revision: str | None = "0003_milestone_1b_a_admin_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _cols(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(table):
        return set()
    return {str(c["name"]) for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = _cols("customer_sessions")
    if "consumed_at" not in cols:
        op.add_column(
            "customer_sessions", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "csrf_token_hash" not in cols:
        op.add_column(
            "customer_sessions", sa.Column("csrf_token_hash", sa.String(length=96), nullable=True)
        )


def downgrade() -> None:
    cols = _cols("customer_sessions")
    if "csrf_token_hash" in cols:
        op.drop_column("customer_sessions", "csrf_token_hash")
    if "consumed_at" in cols:
        op.drop_column("customer_sessions", "consumed_at")
