"""Durable, deduplicated SLA escalation scanning for support conversations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker

from platform_api.support_runtime_models import support_conversations, support_messages
from platform_api.support_sla_models import support_notifications, support_sla_escalations

logger = logging.getLogger(__name__)
BATCH_SIZE = 50
TERMINAL_STATUSES = frozenset({"RESOLVED", "CLOSED", "SPAM", "ARCHIVED"})


def _snapshot_minutes(row: Any, key: str) -> int | None:
    snapshot_value = row["sla_policy_snapshot"]
    if not isinstance(snapshot_value, dict):
        return None
    snapshot = cast(dict[str, object], snapshot_value)
    value = snapshot.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    return value


def _pause_on_customer_wait(row: Any) -> bool:
    snapshot_value = row["sla_policy_snapshot"]
    if not isinstance(snapshot_value, dict):
        return False
    return cast(dict[str, object], snapshot_value).get("pause_on_customer_wait") is True


def _phase(now: datetime, deadline: datetime, duration_minutes: int) -> str | None:
    if now >= deadline:
        return "BREACHED"
    # At-risk means the final 20% of the SLA window, bounded to 1..60 minutes.
    warning_minutes = max(1, min(60, (duration_minutes + 4) // 5))
    if now >= deadline - timedelta(minutes=warning_minutes):
        return "AT_RISK"
    return None


def _latest_public_sender_at(
    db: Session, conversation_id: str, sender_type: str
) -> datetime | None:
    return db.scalar(
        select(func.max(support_messages.c.created_at)).where(
            support_messages.c.conversation_id == conversation_id,
            support_messages.c.sender_type == sender_type,
            support_messages.c.visibility == "PUBLIC",
            support_messages.c.redacted_at.is_(None),
        )
    )


def _debts(db: Session, row: Any, now: datetime) -> list[tuple[str, str, datetime]]:
    status = str(row["status"])
    if status in TERMINAL_STATUSES:
        return []
    if status == "WAITING_FOR_CUSTOMER" and _pause_on_customer_wait(row):
        return []

    conversation_id = str(row["id"])
    latest_customer = _latest_public_sender_at(db, conversation_id, "CUSTOMER")
    latest_agent = _latest_public_sender_at(db, conversation_id, "SUPPORT_AGENT")
    debts: list[tuple[str, str, datetime]] = []

    first_minutes = _snapshot_minutes(row, "first_response_minutes")
    first_deadline = row["first_response_deadline"]
    if (
        latest_agent is None
        and first_minutes is not None
        and isinstance(first_deadline, datetime)
        and status != "WAITING_FOR_CUSTOMER"
    ):
        first_phase = _phase(now, first_deadline, first_minutes)
        if first_phase is not None:
            debts.append(("FIRST_RESPONSE", first_phase, first_deadline))

    next_minutes = _snapshot_minutes(row, "next_response_minutes")
    if (
        latest_agent is not None
        and latest_customer is not None
        and latest_customer > latest_agent
        and next_minutes is not None
        and status != "WAITING_FOR_CUSTOMER"
    ):
        next_deadline = latest_customer + timedelta(minutes=next_minutes)
        next_phase = _phase(now, next_deadline, next_minutes)
        if next_phase is not None:
            debts.append(("NEXT_RESPONSE", next_phase, next_deadline))

    resolution_minutes = _snapshot_minutes(row, "resolution_minutes")
    resolution_deadline = row["resolution_deadline"]
    if resolution_minutes is not None and isinstance(resolution_deadline, datetime):
        resolution_phase = _phase(now, resolution_deadline, resolution_minutes)
        if resolution_phase is not None:
            debts.append(("RESOLUTION", resolution_phase, resolution_deadline))

    return debts


def _record(
    db: Session,
    row: Any,
    *,
    kind: str,
    phase: str,
    deadline: datetime,
    now: datetime,
) -> bool:
    escalation_id = str(uuid4())
    reference = f"SLA-{uuid4().hex[:24]}"
    inserted = db.execute(
        postgresql.insert(support_sla_escalations)
        .values(
            id=escalation_id,
            reference=reference,
            conversation_id=row["id"],
            kind=kind,
            phase=phase,
            source="AUTOMATED",
            deadline_at=deadline,
            observed_at=now,
            status="OPEN",
            created_by=None,
            acknowledged_by=None,
            acknowledged_at=None,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[
                support_sla_escalations.c.conversation_id,
                support_sla_escalations.c.kind,
                support_sla_escalations.c.phase,
                support_sla_escalations.c.deadline_at,
            ]
        )
        .returning(support_sla_escalations.c.id)
    ).scalar_one_or_none()
    if inserted is None:
        return False

    # The notification payload is deliberately identifier/operational metadata only.
    # Ticket subject, customer identity and message bodies never enter this outbox.
    db.execute(
        support_notifications.insert().values(
            id=str(uuid4()),
            conversation_id=row["id"],
            event_type=f"SUPPORT_SLA_{phase}",
            channel="ADMIN_WEB",
            safe_payload={
                "escalation_reference": reference,
                "ticket_reference": str(row["reference"]),
                "kind": kind,
                "phase": phase,
                "deadline_at": deadline.isoformat(),
                "priority": str(row["priority"]),
            },
            status="PENDING",
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
        )
    )
    logger.info(
        "support_sla_escalated",
        extra={
            "escalation_reference": reference,
            "ticket_reference": str(row["reference"]),
            "kind": kind,
            "phase": phase,
        },
    )
    return True


class SupportSlaEscalationWorker:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory

    def run_once(self, now: datetime | None = None, batch_size: int = BATCH_SIZE) -> int:
        now = now or datetime.now(UTC)
        bounded_batch = min(max(batch_size, 1), BATCH_SIZE)
        created = 0
        with self.factory.begin() as db:
            rows = (
                db.execute(
                    select(support_conversations)
                    .where(support_conversations.c.status.not_in(TERMINAL_STATUSES))
                    .order_by(
                        support_conversations.c.resolution_deadline.asc().nulls_last(),
                        support_conversations.c.created_at.asc(),
                    )
                    .limit(bounded_batch)
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .all()
            )
            for row in rows:
                for kind, phase, deadline in _debts(db, row, now):
                    created += int(
                        _record(
                            db,
                            row,
                            kind=kind,
                            phase=phase,
                            deadline=deadline,
                            now=now,
                        )
                    )
        return created
