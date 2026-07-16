"""milestone 1a identity foundation
Revision ID: 0002_milestone_1a_identity
Revises: 0001_initial_foundation
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op

from platform_api.identity.models import IdentityBase

revision: str = "0002_milestone_1a_identity"
down_revision: str | None = "0001_initial_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    IdentityBase.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    IdentityBase.metadata.drop_all(bind=bind)
