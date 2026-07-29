"""Add crash-safe delivery observability to the manual top-up outbox.

Revision ID: 0034_manual_topup_delivery
Revises: 0033_manual_topup_application
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0034_manual_topup_delivery"
down_revision: str = "0033_manual_topup_application"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "manual_topup_notification_outbox",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "manual_topup_notification_outbox",
        sa.Column("last_error_category", sa.String(48), nullable=True),
    )
    op.drop_constraint(
        "ck_manual_topup_outbox_status", "manual_topup_notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_manual_topup_outbox_status",
        "manual_topup_notification_outbox",
        "status in ('PENDING','PROCESSING','SENT','FAILED','SKIPPED')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE manual_topup_notification_outbox SET status = 'FAILED' WHERE status = 'SKIPPED'"
        )
    )
    op.drop_constraint(
        "ck_manual_topup_outbox_status", "manual_topup_notification_outbox", type_="check"
    )
    op.create_check_constraint(
        "ck_manual_topup_outbox_status",
        "manual_topup_notification_outbox",
        "status in ('PENDING','PROCESSING','SENT','FAILED')",
    )
    op.drop_column("manual_topup_notification_outbox", "last_error_category")
    op.drop_column("manual_topup_notification_outbox", "processing_started_at")
