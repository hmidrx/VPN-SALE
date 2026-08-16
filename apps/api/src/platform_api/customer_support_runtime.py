"""Authenticated customer-web bridge into the durable support store.

This keeps customer support available when Telegram is unavailable while preserving the
same ownership, SLA, state-machine and idempotency boundaries used by native support.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from vpnsale_domain.support import SupportStatus

from .config import Settings, get_settings
from .customer_auth.routes import current_customer_session_dependency
from .customer_auth.service import CustomerAuthService
from .customer_support_contract import (
    clean_customer_support_text,
    customer_support_detail,
    customer_support_idempotency_resource,
    customer_support_key_hash,
    customer_support_payload_digest,
    customer_support_routing,
    customer_support_summary,
    existing_customer_support_ticket_for_key,
    owned_customer_support_conversation,
    transition_customer_support,
)
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_messages,
)

router = APIRouter(prefix="/api/v1/customer/support", tags=["customer-support"])


class CreateTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=3, max_length=160)
    message: str = Field(min_length=1, max_length=4000)


class ReplyTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _require_csrf(
    db: Session,
    settings: Settings,
    current: CustomerSessionModel,
    token: str | None,
) -> None:
    if not CustomerAuthService(db, settings).validate_csrf(current, token):
        raise HTTPException(status_code=403, detail="csrf_invalid")


@router.get("/tickets")
def list_tickets(
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    rows = (
        db.execute(
            select(support_conversations)
            .where(
                support_conversations.c.requester_type == "CUSTOMER",
                support_conversations.c.requester_user_id == current.user_id,
            )
            .order_by(support_conversations.c.updated_at.desc())
            .limit(50)
        )
        .mappings()
        .all()
    )
    _no_store(response)
    return {"items": [customer_support_summary(row) for row in rows]}


@router.get("/tickets/{reference}")
def ticket_detail(
    reference: str,
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    payload = customer_support_detail(db, current.user_id, reference)
    _no_store(response)
    return payload


@router.post("/tickets")
def create_ticket(
    body: CreateTicketRequest,
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _require_csrf(db, settings, current, x_csrf_token)
    customer_id = current.user_id
    subject = clean_customer_support_text(body.subject, limit=160)
    message = clean_customer_support_text(body.message, limit=4000)
    routing = customer_support_routing(db)
    scope = f"web-ticket:{customer_id}"
    key_hash = customer_support_key_hash(idempotency_key)
    payload_digest = customer_support_payload_digest(subject, message)
    existing = db.scalar(
        select(support_idempotency_records.c.resource_reference).where(
            support_idempotency_records.c.scope == scope,
            support_idempotency_records.c.key_hash == key_hash,
        )
    )
    if existing:
        payload = existing_customer_support_ticket_for_key(
            db, customer_id, str(existing), payload_digest
        )
        _no_store(response)
        return payload

    now = datetime.now(UTC)
    reference = f"SUP-{uuid4().hex[:24]}"
    conversation_id = str(uuid4())
    resource_value = customer_support_idempotency_resource(reference, payload_digest)
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
        payload = existing_customer_support_ticket_for_key(
            db, customer_id, str(existing), payload_digest
        )
        _no_store(response)
        return payload

    db.execute(
        support_conversations.insert().values(
            id=conversation_id,
            reference=reference,
            requester_type="CUSTOMER",
            requester_user_id=customer_id,
            tenant_id=None,
            channel="CUSTOMER_WEB",
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
            channel="CUSTOMER_WEB",
            message_type="CUSTOMER_MESSAGE",
            visibility="PUBLIC",
            body=message,
            body_sha256=sha256(message.encode()).hexdigest(),
            client_idempotency_key=f"web:{key_hash}",
            created_at=now,
        )
    )
    db.commit()
    payload = customer_support_detail(db, customer_id, reference)
    _no_store(response)
    return payload


@router.post("/tickets/{reference}/reply")
def reply_ticket(
    reference: str,
    body: ReplyTicketRequest,
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _require_csrf(db, settings, current, x_csrf_token)
    customer_id = current.user_id
    message = clean_customer_support_text(body.message, limit=4000)
    row = owned_customer_support_conversation(db, customer_id, reference, lock=True)
    current_status = str(row["status"])
    if current_status in {SupportStatus.SPAM.value, SupportStatus.ARCHIVED.value}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")

    message_key = f"web:{customer_support_key_hash(idempotency_key)}"
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
                channel="CUSTOMER_WEB",
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
            .values(updated_at=now, version=support_conversations.c.version + 1)
        )
        if current_status == SupportStatus.WAITING_FOR_CUSTOMER.value:
            current_status = transition_customer_support(
                db,
                row,
                current_status,
                SupportStatus.IN_PROGRESS,
                actor_id=customer_id,
                reason="Customer replied from web while support was waiting for customer",
                now=now,
            )
        elif current_status in {SupportStatus.RESOLVED.value, SupportStatus.CLOSED.value}:
            current_status = transition_customer_support(
                db,
                row,
                current_status,
                SupportStatus.REOPENED,
                actor_id=customer_id,
                reason="Customer replied from web after resolution or closure",
                now=now,
            )
        if current_status in {SupportStatus.IN_PROGRESS.value, SupportStatus.REOPENED.value}:
            transition_customer_support(
                db,
                row,
                current_status,
                SupportStatus.WAITING_FOR_SUPPORT,
                actor_id=customer_id,
                reason="Customer web reply is waiting for support",
                now=now,
            )
        db.commit()
    payload = customer_support_detail(db, customer_id, reference)
    _no_store(response)
    return payload
