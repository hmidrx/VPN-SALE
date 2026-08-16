"""Public customer-support primitives shared by authenticated channels.

The channel adapters own authentication and transport details. This module owns the
customer-visible projection, routing, sanitization, idempotency helpers and support
state transitions so browser and bot flows can follow the same durable rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.support import (
    LEGAL_TRANSITIONS,
    SupportDomainError,
    SupportStatus,
    sanitize_message,
)

from .support_runtime_models import (
    support_categories,
    support_conversations,
    support_messages,
    support_queues,
    support_sla_policies,
    support_status_history,
)


@dataclass(frozen=True)
class CustomerSupportRouting:
    category_id: str
    queue_id: str
    team_id: str | None
    priority: str
    policy_snapshot: dict[str, object]
    first_response_minutes: int
    next_response_minutes: int
    resolution_minutes: int


def clean_customer_support_text(value: str, *, limit: int) -> str:
    try:
        cleaned = sanitize_message(value, limit)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_text_invalid") from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="support_text_invalid")
    return cleaned


def customer_support_routing(db: Session) -> CustomerSupportRouting:
    category_id = db.scalar(
        select(support_categories.c.id).where(
            support_categories.c.code == "telegram_general",
            support_categories.c.active.is_(True),
        )
    )
    route = db.execute(
        select(
            support_queues.c.id,
            support_queues.c.team_id,
            support_queues.c.default_priority,
            support_sla_policies.c.code,
            support_sla_policies.c.version,
            support_sla_policies.c.first_response_minutes,
            support_sla_policies.c.next_response_minutes,
            support_sla_policies.c.resolution_minutes,
            support_sla_policies.c.pause_on_customer_wait,
        )
        .join(
            support_sla_policies,
            support_sla_policies.c.id == support_queues.c.sla_policy_id,
        )
        .where(
            support_queues.c.code == "telegram_customer",
            support_queues.c.active.is_(True),
            support_queues.c.maintenance.is_(False),
        )
    ).one_or_none()
    if category_id is None or route is None:
        raise HTTPException(status_code=503, detail="support_unavailable")
    first_response = int(route[5])
    next_response = int(route[6])
    resolution = int(route[7])
    return CustomerSupportRouting(
        category_id=str(category_id),
        queue_id=str(route[0]),
        team_id=str(route[1]) if route[1] is not None else None,
        priority=str(route[2]),
        policy_snapshot={
            "code": str(route[3]),
            "version": int(route[4]),
            "first_response_minutes": first_response,
            "next_response_minutes": next_response,
            "resolution_minutes": resolution,
            "pause_on_customer_wait": bool(route[8]),
        },
        first_response_minutes=first_response,
        next_response_minutes=next_response,
        resolution_minutes=resolution,
    )


def owned_customer_support_conversation(
    db: Session,
    customer_id: str,
    reference: str,
    *,
    lock: bool = False,
) -> Any:
    statement = select(support_conversations).where(
        support_conversations.c.reference == reference,
        support_conversations.c.requester_type == "CUSTOMER",
        support_conversations.c.requester_user_id == customer_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def customer_support_summary(row: Any) -> dict[str, object]:
    return {
        "reference": str(row["reference"]),
        "subject": str(row["subject"]),
        "status": str(row["status"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def customer_support_detail(
    db: Session,
    customer_id: str,
    reference: str,
) -> dict[str, object]:
    row = owned_customer_support_conversation(db, customer_id, reference)
    newest = (
        db.execute(
            select(
                support_messages.c.sequence,
                support_messages.c.sender_type,
                support_messages.c.message_type,
                support_messages.c.body,
                support_messages.c.created_at,
            )
            .where(
                support_messages.c.conversation_id == row["id"],
                support_messages.c.visibility == "PUBLIC",
                support_messages.c.redacted_at.is_(None),
            )
            .order_by(support_messages.c.sequence.desc())
            .limit(100)
        )
        .mappings()
        .all()
    )
    messages = list(reversed(newest))
    return {
        **customer_support_summary(row),
        "messages": [
            {
                "sequence": int(message["sequence"]),
                "sender_type": str(message["sender_type"]),
                "message_type": str(message["message_type"]),
                "body": str(message["body"]),
                "created_at": message["created_at"].isoformat(),
            }
            for message in messages
        ],
    }


def customer_support_key_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def customer_support_payload_digest(*values: str) -> str:
    return sha256("\u0000".join(values).encode()).hexdigest()


def customer_support_idempotency_resource(reference: str, payload_digest: str) -> str:
    return f"{reference}|{payload_digest[:32]}"


def _parse_idempotency_resource(value: str) -> tuple[str, str | None]:
    reference, separator, digest = value.partition("|")
    return reference, digest if separator else None


def existing_customer_support_ticket_for_key(
    db: Session,
    customer_id: str,
    resource_value: str,
    payload_digest: str,
) -> dict[str, object]:
    reference, stored_digest = _parse_idempotency_resource(resource_value)
    if stored_digest is not None and stored_digest != payload_digest[:32]:
        raise HTTPException(status_code=409, detail="idempotency_conflict")
    return customer_support_detail(db, customer_id, reference)


def _resume_deadlines_after_customer_wait(
    db: Session,
    row: Any,
    now: datetime,
) -> dict[str, datetime | None]:
    snapshot_value = row["sla_policy_snapshot"]
    if not isinstance(snapshot_value, dict):
        return {}
    snapshot = cast(dict[str, object], snapshot_value)
    if snapshot.get("pause_on_customer_wait") is not True:
        return {}
    paused_at = db.scalar(
        select(support_status_history.c.created_at)
        .where(
            support_status_history.c.conversation_id == row["id"],
            support_status_history.c.to_status == SupportStatus.WAITING_FOR_CUSTOMER.value,
        )
        .order_by(support_status_history.c.created_at.desc())
        .limit(1)
    )
    if paused_at is None or paused_at >= now:
        return {}
    delta = now - paused_at
    return {
        "first_response_deadline": (
            row["first_response_deadline"] + delta
            if row["first_response_deadline"] is not None
            else None
        ),
        "next_response_deadline": (
            row["next_response_deadline"] + delta
            if row["next_response_deadline"] is not None
            else None
        ),
        "resolution_deadline": (
            row["resolution_deadline"] + delta if row["resolution_deadline"] is not None else None
        ),
    }


def transition_customer_support(
    db: Session,
    row: Any,
    from_status: str,
    to_status: SupportStatus,
    *,
    actor_id: str,
    reason: str,
    now: datetime,
) -> str:
    current = SupportStatus(from_status)
    if to_status not in LEGAL_TRANSITIONS[current]:
        raise HTTPException(status_code=409, detail="ticket_transition_invalid")
    values: dict[str, object] = {
        "status": to_status.value,
        "updated_at": now,
        "version": support_conversations.c.version + 1,
    }
    if current == SupportStatus.WAITING_FOR_CUSTOMER:
        values.update(_resume_deadlines_after_customer_wait(db, row, now))
    if to_status == SupportStatus.RESOLVED:
        values["resolved_at"] = now
    if to_status == SupportStatus.CLOSED:
        values["closed_at"] = now
    if to_status == SupportStatus.REOPENED:
        values["resolved_at"] = None
        values["closed_at"] = None
    db.execute(
        support_status_history.insert().values(
            id=str(uuid4()),
            conversation_id=row["id"],
            from_status=current.value,
            to_status=to_status.value,
            reason=clean_customer_support_text(reason, limit=500),
            created_by=actor_id,
            created_at=now,
        )
    )
    db.execute(
        update(support_conversations)
        .where(support_conversations.c.id == row["id"])
        .values(**values)
    )
    return to_status.value
