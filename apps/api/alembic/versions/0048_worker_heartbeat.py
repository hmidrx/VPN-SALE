"""Add bounded worker heartbeat state for production liveness monitoring.

Revision ID: 0048_worker_heartbeat
Revises: 0047_low_traffic_tg
Create Date: 2026-08-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0048_worker_heartbeat"
down_revision: str = "0047_low_traffic_tg"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("role", sa.String(length=48), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("successful_cycles", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("failed_cycles", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("role", name="pk_worker_heartbeats"),
    )


def downgrade() -> None:
    op.drop_table("worker_heartbeats")
