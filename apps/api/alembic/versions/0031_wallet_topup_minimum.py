"""Set the customer wallet top-up minimum to 100,000 toman.

Revision ID: 0031_wallet_topup_minimum
Revises: 0030_telegram_link_challenges
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031_wallet_topup_minimum"
down_revision: str = "0030_telegram_link_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE wallet_policies SET minimum_topup_amount_rial = :minimum WHERE currency = 'IRR'"
        ).bindparams(minimum=1_000_000)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE wallet_policies SET minimum_topup_amount_rial = :minimum WHERE currency = 'IRR'"
        ).bindparams(minimum=100_000)
    )
