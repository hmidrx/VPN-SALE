"""Add durable, deduplicated support SLA escalation history."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041_support_sla_escalations"
down_revision: str = "0040_support_reply_notifications"
branch_labels = None
depends_on = None

TABLE = "support_sla_escalations"


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    op.create_table(
        TABLE,
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "conversation_id",
            uuid,
            sa.ForeignKey("support_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="OPEN"),
        sa.Column("created_by", uuid, sa.ForeignKey("admins.id", ondelete="RESTRICT")),
        sa.Column("acknowledged_by", uuid, sa.ForeignKey("admins.id", ondelete="RESTRICT")),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference", name="uq_support_sla_escalation_reference"),
        sa.UniqueConstraint(
            "conversation_id",
            "kind",
            "phase",
            "deadline_at",
            name="uq_support_sla_escalation_deadline_phase",
        ),
        sa.CheckConstraint(
            "kind IN ('FIRST_RESPONSE','NEXT_RESPONSE','RESOLUTION','MANUAL')",
            name="ck_support_sla_escalation_kind",
        ),
        sa.CheckConstraint(
            "phase IN ('AT_RISK','BREACHED','MANUAL')",
            name="ck_support_sla_escalation_phase",
        ),
        sa.CheckConstraint(
            "source IN ('AUTOMATED','MANUAL')",
            name="ck_support_sla_escalation_source",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','ACKNOWLEDGED')",
            name="ck_support_sla_escalation_status",
        ),
        sa.CheckConstraint(
            "(source = 'MANUAL' AND kind = 'MANUAL' AND phase = 'MANUAL') OR "
            "(source = 'AUTOMATED' AND kind <> 'MANUAL' AND phase <> 'MANUAL')",
            name="ck_support_sla_escalation_source_shape",
        ),
    )
    op.create_index(
        "ix_support_sla_escalation_open",
        TABLE,
        ["status", "created_at"],
    )
    op.create_index(
        "ix_support_sla_escalation_conversation",
        TABLE,
        ["conversation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_support_sla_escalation_conversation", table_name=TABLE)
    op.drop_index("ix_support_sla_escalation_open", table_name=TABLE)
    op.drop_table(TABLE)
