"""Seed the minimum durable routing required by native Telegram support."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039_telegram_native_support"
down_revision: str = "0038_service_activation_delivery"
branch_labels = None
depends_on = None

CATEGORY_ID = UUID("5e390000-0000-4000-8000-000000000001")
CALENDAR_ID = UUID("5e390000-0000-4000-8000-000000000002")
SLA_ID = UUID("5e390000-0000-4000-8000-000000000003")
TEAM_ID = UUID("5e390000-0000-4000-8000-000000000004")
QUEUE_ID = UUID("5e390000-0000-4000-8000-000000000005")


def upgrade() -> None:
    bind = op.get_bind()
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    categories = sa.table(
        "support_categories",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("label_fa", sa.String),
        sa.column("label_en", sa.String),
        sa.column("routing_code", sa.String),
        sa.column("active", sa.Boolean),
        sa.column("version", sa.Integer),
    )
    calendars = sa.table(
        "support_business_calendars",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("timezone", sa.String),
        sa.column("weekdays", jsonb),
        sa.column("holidays", jsonb),
        sa.column("emergency_closed", sa.Boolean),
        sa.column("version", sa.Integer),
    )
    policies = sa.table(
        "support_sla_policies",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("calendar_id", uuid),
        sa.column("priority", sa.String),
        sa.column("first_response_minutes", sa.Integer),
        sa.column("next_response_minutes", sa.Integer),
        sa.column("resolution_minutes", sa.Integer),
        sa.column("pause_on_customer_wait", sa.Boolean),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer),
    )
    teams = sa.table(
        "support_teams",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("active", sa.Boolean),
    )
    queues = sa.table(
        "support_queues",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("team_id", uuid),
        sa.column("sla_policy_id", uuid),
        sa.column("allowed_requester_types", jsonb),
        sa.column("supported_channels", jsonb),
        sa.column("default_priority", sa.String),
        sa.column("assignment_strategy", sa.String),
        sa.column("maintenance", sa.Boolean),
        sa.column("active", sa.Boolean),
        sa.column("version", sa.Integer),
    )

    bind.execute(
        postgresql.insert(categories)
        .values(
            id=CATEGORY_ID,
            code="telegram_general",
            label_fa="پشتیبانی عمومی",
            label_en="General support",
            routing_code="telegram_general",
            active=True,
            version=1,
        )
        .on_conflict_do_nothing(index_elements=[categories.c.code])
    )
    bind.execute(
        postgresql.insert(calendars)
        .values(
            id=CALENDAR_ID,
            code="telegram_always_open",
            timezone="Asia/Tehran",
            weekdays={str(day): [["00:00", "23:59"]] for day in range(7)},
            holidays=[],
            emergency_closed=False,
            version=1,
        )
        .on_conflict_do_nothing(index_elements=[calendars.c.code])
    )
    bind.execute(
        postgresql.insert(policies)
        .values(
            id=SLA_ID,
            code="telegram_normal",
            calendar_id=CALENDAR_ID,
            priority="NORMAL",
            first_response_minutes=240,
            next_response_minutes=480,
            resolution_minutes=2880,
            pause_on_customer_wait=True,
            effective_from=sa.func.now(),
            version=1,
        )
        .on_conflict_do_nothing(index_elements=[policies.c.code, policies.c.version])
    )
    bind.execute(
        postgresql.insert(teams)
        .values(id=TEAM_ID, code="telegram_support", name="Telegram Support", active=True)
        .on_conflict_do_nothing(index_elements=[teams.c.code])
    )
    bind.execute(
        postgresql.insert(queues)
        .values(
            id=QUEUE_ID,
            code="telegram_customer",
            name="Telegram Customer Support",
            team_id=TEAM_ID,
            sla_policy_id=SLA_ID,
            allowed_requester_types=["CUSTOMER"],
            supported_channels=["TELEGRAM_BOT"],
            default_priority="NORMAL",
            assignment_strategy="ROUND_ROBIN",
            maintenance=False,
            active=True,
            version=1,
        )
        .on_conflict_do_nothing(index_elements=[queues.c.code])
    )


def downgrade() -> None:
    bind = op.get_bind()
    targets = (
        ("support_queues", "telegram_customer"),
        ("support_teams", "telegram_support"),
        ("support_sla_policies", "telegram_normal"),
        ("support_business_calendars", "telegram_always_open"),
        ("support_categories", "telegram_general"),
    )
    for table_name, code in targets:
        table = sa.table(table_name, sa.column("code", sa.String))
        bind.execute(sa.delete(table).where(table.c.code == code))
