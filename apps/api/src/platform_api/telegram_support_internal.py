"""Durable native support API for the production Telegram bot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from vpnsale_domain.support import sanitize_message

from .identity.models import TelegramAccountModel, UserModel
from .support_runtime_models import (
    support_categories,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_queues,
)
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-support"],
    include_in_schema=False,
)


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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="support_text_invalid") from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="support_text_invalid")
    return cleaned


def _routing(db: Database) -> tuple[str, str, str]:
    category = db.execute(
        select(support_categories.c.id, support_categories.c.label_fa).where(
            support_categories.c.code == "telegram_general",
            support_categories.c.active.is_(True),
        )
    ).one_or_none()
    queue = db.execute(
        select(support_queues.c.id, support_queues.c.default_priority).where(
            support_queues.c.code == "telegram_customer",
            support_queues.c.active.is_(True),
            support_queues.c.maintenance.is_(False),
        )
    ).one_or_none()
    if category is None or queue is None:
        raise HTTPException(status_code=503, detail="support_unavailable")
    return str(category[0]), str(queue[0]), str(queue[1])


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
    messages = db.execute(
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
        .order_by(support_messages.c.sequence.asc())
        .limit(100)
    ).mappings().all()
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


@router.get("/support/tickets")
def list_tickets(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    rows = db.execute(
        select(support_conversations)
        .where(
            support_conversations.c.requester_type == "CUSTOMER",
            support_conversations.c.requester_user_id == customer_id,
        )
        .order_by(support_conversations.c.updated_at.desc())
        .limit(20)
    ).mappings().all()
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    subject = _clean_text(body.subject, limit=160)
    message = _clean_text(body.message, limit=4000)
    category_id, queue_id, priority = _routing(db)
    scope = f"tg-ticket:{customer_id}"
    key_hash = _key_hash(idempotency_key)
    existing = db.scalar(
        select(support_idempotency_records.c.resource_reference).where(
            support_idempotency_records.c.scope == scope,
            support_idempotency_records.c.key_hash == key_hash,
        )
    )
    if existing:
        payload = _detail(db, customer_id, str(existing))
        _no_store(response)
        return payload

    now = datetime.now(UTC)
    reference = f"SUP-{uuid4().hex[:24]}"
    conversation_id = str(uuid4())
    claimed = db.execute(
        postgresql.insert(support_idempotency_records)
        .values(
            id=str(uuid4()),
            scope=scope,
            key_hash=key_hash,
            resource_reference=reference,
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
        payload = _detail(db, customer_id, str(existing))
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
            category_id=category_id,
            queue_id=queue_id,
            subject=subject,
            priority=priority,
            status="NEW",
            sla_policy_snapshot={
                "source": "telegram_normal",
                "first_response_minutes": 240,
                "next_response_minutes": 480,
                "resolution_minutes": 2880,
            },
            first_response_deadline=now + timedelta(minutes=240),
            next_response_deadline=now + timedelta(minutes=480),
            resolution_deadline=now + timedelta(minutes=2880),
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
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    message = _clean_text(body.message, limit=4000)
    row = _conversation(db, customer_id, reference, lock=True)
    if str(row["status"]) in {"SPAM", "ARCHIVED"}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")
    message_key = f"tg:{_key_hash(idempotency_key)}"
    existing = db.scalar(
        select(support_messages.c.id).where(
            support_messages.c.conversation_id == row["id"],
            support_messages.c.client_idempotency_key == message_key,
        )
    )
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
                body_sha256=sha256(message.encode()).hexdigest(),
                client_idempotency_key=message_key,
                created_at=now,
            )
        )
        db.execute(
            update(support_conversations)
            .where(support_conversations.c.id == row["id"])
            .values(
                status="WAITING_FOR_SUPPORT",
                updated_at=now,
                resolved_at=None,
                closed_at=None,
                version=support_conversations.c.version + 1,
            )
        )
        db.commit()
    payload = _detail(db, customer_id, reference)
    _no_store(response)
    return payload
