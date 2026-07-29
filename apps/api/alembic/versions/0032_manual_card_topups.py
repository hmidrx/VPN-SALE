"""Add private, reviewed manual wallet top-up persistence.

Revision ID: 0032_manual_card_topups
Revises: 0031_wallet_topup_minimum
"""

from __future__ import annotations

from alembic import op

import platform_api.wallet_models  # noqa: F401
from platform_api.manual_topup_models import (
    ManualTopupDecisionModel,
    ManualTopupIdempotencyModel,
    ManualTopupMessageModel,
    ManualTopupNotificationOutboxModel,
    ManualTopupReceiptModel,
    ManualTopupRequestModel,
)

revision: str = "0032_manual_card_topups"
down_revision: str = "0031_wallet_topup_minimum"
branch_labels = None
depends_on = None

_TABLES = (
    ManualTopupRequestModel.__table__,
    ManualTopupReceiptModel.__table__,
    ManualTopupDecisionModel.__table__,
    ManualTopupIdempotencyModel.__table__,
    ManualTopupMessageModel.__table__,
    ManualTopupNotificationOutboxModel.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        table.create(bind, checkfirst=False)
    op.create_foreign_key(
        "fk_manual_topup_current_receipt",
        "manual_topup_requests",
        "manual_topup_receipts",
        ["current_receipt_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manual_topup_current_receipt", "manual_topup_requests", type_="foreignkey"
    )
    bind = op.get_bind()
    for table in reversed(_TABLES):
        table.drop(bind, checkfirst=False)
