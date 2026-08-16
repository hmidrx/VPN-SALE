"""Durable native support API for the production Telegram bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from vpnsale_domain.support import (
    LEGAL_TRANSITIONS,
    SupportDomainError,
    SupportStatus,
    sanitize_message,
)

from .identity.models import TelegramAccountModel, UserModel
from .support_runtime_models import (
    support_categories,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_queues,
    support_sla_policies,
    support_status_history,
)
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-support"],
    include_in_schema=False,
)


@dataclass(frozen=True)
class SupportRouting:
    category_id: str
    queue_id: str
    team_id: str | None
    priority: str
    policy_snapshot: dict[str, object]
    first_response_minutes: int
    next_response_minutes: int
    resolution_minutes: int


class CreateTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=1, max_length=4000)


class ReplyTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _customer_id(db: Database, telegram_id: int) -> str:
    row = db.execute(
        select(TelegramAccountModel, UserModel)
        .join(UserModel, TelegramAccountModel.user_id == UserModel.id)
        .where(TelegramAccountModel.telegram_user_id == telegram_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account_unlinked")
    user = row[1]
    if user.status not in {"ACTIVE", "PENDING"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_restricted")
    return user.id


def _clean_text(value: str, *, limit: int) -> str:
    try:
        cleaned = sanitize_message(value, limit)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_text_invalid") from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="support_text_invalid")
    return cleaned


def _routing(db: Database) -> SupportRouting:
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
    return SupportRouting(
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


def _conversation(db: Database, customer_id: str, reference: str, *, lock: bool = False) -> Any:
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


def _summary(row: Any) -> dict[str, object]:
    return {
        "reference": str(row["reference"]),
        "subject": str(row["subject"]),
        "status": str(row["status"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _detail(db: Database, customer_id: str, reference: str) -> dict[str, object]:
    row = _conversation(db, customer_id, reference)
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
        **_summary(row),
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


def _key_hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _payload_digest(*values: str) -> str:
    return sha256("\u0000".join(values).encode()).hexdigest()


def _idempotency_resource(reference: str, payload_digest: str) -> str:
    return f"{reference}|{payload_digest[:32]}"


def _parse_idempotency_resource(value: str) -> tuple[str, str | None]:
    reference, separator, digest = value.partition("|")
    return reference, digest if separator else None


def _existing_ticket_for_key(
    db: Database,
    customer_id: str,
    resource_value: str,
    payload_digest: str,
) -> dict[str, object]:
    reference, stored_digest = _parse_idempotency_resource(resource_value)
    if stored_digest is not None and stored_digest != payload_digest[:32]:
        raise HTTPException(status_code=409, detail="idempotency_conflict")
    return _detail(db, customer_id, reference)


def _resume_deadlines_after_customer_wait(
    db: Database,
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


def _transition(
    db: Database,
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
            reason=_clean_text(reason, limit=500),
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


@router.get("/support/tickets")
def list_tickets(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    rows = (
        db.execute(
            select(support_conversations)
            .where(
                support_conversations.c.requester_type == "CUSTOMER",
                support_conversations.c.requester_user_id == customer_id,
            )
            .order_by(support_conversations.c.updated_at.desc())
            .limit(20)
        )
        .mappings()
        .all()
    )
    _no_store(response)
    return {"items": [_summary(row) for row in rows]}


@router.get("/support/tickets/{reference}")
def ticket_detail(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    payload = _detail(db, customer_id, reference)
    _no_store(response)
    return payload


@router.post("/support/tickets")
def create_ticket(
    body: CreateTicketRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    subject = _clean_text(body.subject, limit=160)
    message = _clean_text(body.message, limit=4000)
    routing = _routing(db)
    scope = f"tg-ticket:{customer_id}"
    key_hash = _key_hash(idempotency_key)
    payload_digest = _payload_digest(subject, message)
    existing = db.scalar(
        select(support_idempotency_records.c.resource_reference).where(
            support_idempotency_records.c.scope == scope,
            support_idempotency_records.c.key_hash == key_hash,
        )
    )
    if existing:
        payload = _existing_ticket_for_key(db, customer_id, str(existing), payload_digest)
        _no_store(response)
        return payload

    now = datetime.now(UTC)
    reference = f"SUP-{uuid4().hex[:24]}"
    conversation_id = str(uuid4())
    resource_value = _idempotency_resource(reference, payload_digest)
    claimed = db.execute(
        postgresql.insert(support_idempotency_records)
        .values(
            id=str(uuid4()),
            scope=scope,
            key_hash=key_hash,
            resource_reference=resource_value,
            created_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[
                support_idempotency_records.c.scope,
                support_idempotency_records.c.key_hash,
            ]
        )
        .returning(support_idempotency_records.c.resource_reference)
    ).scalar_one_or_none()
    if claimed is None:
        existing = db.scalar(
            select(support_idempotency_records.c.resource_reference).where(
                support_idempotency_records.c.scope == scope,
                support_idempotency_records.c.key_hash == key_hash,
            )
        )
        if not existing:
            raise HTTPException(status_code=503, detail="support_retry")
        payload = _existing_ticket_for_key(db, customer_id, str(existing), payload_digest)
        _no_store(response)
        return payload

    db.execute(
        support_conversations.insert().values(
            id=conversation_id,
            reference=reference,
            requester_type="CUSTOMER",
            requester_user_id=customer_id,
            tenant_id=None,
            channel="TELEGRAM_BOT",
            category_id=routing.category_id,
            queue_id=routing.queue_id,
            subject=subject,
            priority=routing.priority,
            status=SupportStatus.NEW.value,
            assigned_team_id=routing.team_id,
            sla_policy_snapshot=routing.policy_snapshot,
            first_response_deadline=now + timedelta(minutes=routing.first_response_minutes),
            next_response_deadline=now + timedelta(minutes=routing.next_response_minutes),
            resolution_deadline=now + timedelta(minutes=routing.resolution_minutes),
            version=1,
            created_at=now,
            updated_at=now,
        )
    )
    db.execute(
        support_messages.insert().values(
            id=str(uuid4()),
            conversation_id=conversation_id,
            sequence=1,
            sender_type="CUSTOMER",
            sender_id=customer_id,
            channel="TELEGRAM_BOT",
            message_type="CUSTOMER_MESSAGE",
            visibility="PUBLIC",
            body=message,
            body_sha256=sha256(message.encode()).hexdigest(),
            client_idempotency_key=f"tg:{key_hash}",
            created_at=now,
        )
    )
    db.commit()
    payload = _detail(db, customer_id, reference)
    _no_store(response)
    return payload


@router.post("/support/tickets/{reference}/reply")
def reply_ticket(
    reference: str,
    body: ReplyTicketRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    message = _clean_text(body.message, limit=4000)
    row = _conversation(db, customer_id, reference, lock=True)
    current_status = str(row["status"])
    if current_status in {SupportStatus.SPAM.value, SupportStatus.ARCHIVED.value}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")
    message_key = f"tg:{_key_hash(idempotency_key)}"
    existing = db.execute(
        select(support_messages.c.id, support_messages.c.body_sha256).where(
            support_messages.c.conversation_id == row["id"],
            support_messages.c.client_idempotency_key == message_key,
        )
    ).one_or_none()
    message_digest = sha256(message.encode()).hexdigest()
    if existing is not None and str(existing[1]) != message_digest:
        raise HTTPException(status_code=409, detail="idempotency_conflict")
    if existing is None:
        last_sequence = db.scalar(
            select(func.max(support_messages.c.sequence)).where(
                support_messages.c.conversation_id == row["id"]
            )
        )
        now = datetime.now(UTC)
        db.execute(
            support_messages.insert().values(
                id=str(uuid4()),
                conversation_id=row["id"],
                sequence=int(last_sequence or 0) + 1,
                sender_type="CUSTOMER",
                sender_id=customer_id,
                channel="TELEGRAM_BOT",
                message_type="CUSTOMER_MESSAGE",
                visibility="PUBLIC",
                body=message,
                body_sha256=message_digest,
                client_idempotency_key=message_key,
                created_at=now,
            )
        )
        db.execute(
            update(support_conversations)
            .where(support_conversations.c.id == row["id"])
            .values(
                updated_at=now,
                version=support_conversations.c.version + 1,
            )
        )
        if current_status == SupportStatus.WAITING_FOR_CUSTOMER.value:
            current_status = _transition(
                db,
                row,
                current_status,
                SupportStatus.IN_PROGRESS,
                actor_id=customer_id,
                reason="Customer replied while support was waiting for customer",
                now=now,
            )
        elif current_status in {
            SupportStatus.RESOLVED.value,
            SupportStatus.CLOSED.value,
        }:
            current_status = _transition(
                db,
                row,
                current_status,
                SupportStatus.REOPENED,
                actor_id=customer_id,
                reason="Customer replied after resolution or closure",
                now=now,
            )
        if current_status in {
            SupportStatus.IN_PROGRESS.value,
            SupportStatus.REOPENED.value,
        }:
            _transition(
                db,
                row,
                current_status,
                SupportStatus.WAITING_FOR_SUPPORT,
                actor_id=customer_id,
                reason="Customer reply is waiting for support",
                now=now,
            )
        db.commit()
    payload = _detail(db, customer_id, reference)
    _no_store(response)
    return payload
