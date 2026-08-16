"""Durable unread/read state for authenticated customer-web support."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .customer_auth.routes import current_customer_session_dependency
from .customer_auth.service import CustomerAuthService
from .customer_support_contract import owned_customer_support_conversation
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .support_runtime_models import (
    support_conversations,
    support_message_deliveries,
    support_messages,
)

router = APIRouter(prefix="/api/v1/customer/support", tags=["customer-support-read-state"])


class MarkReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    through_sequence: int = Field(ge=1)


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


def customer_support_unread_counts(
    db: Session,
    customer_id: str,
    conversation_ids: list[str] | None = None,
) -> dict[str, int]:
    if conversation_ids is not None and not conversation_ids:
        return {}

    delivery = support_message_deliveries.alias("customer_delivery")
    statement = (
        select(
            support_messages.c.conversation_id,
            func.count().label("unread_count"),
        )
        .select_from(
            support_messages.join(
                support_conversations,
                support_conversations.c.id == support_messages.c.conversation_id,
            ).outerjoin(
                delivery,
                and_(
                    delivery.c.message_id == support_messages.c.id,
                    delivery.c.participant_type == "CUSTOMER",
                    delivery.c.participant_id == customer_id,
                ),
            )
        )
        .where(
            support_conversations.c.requester_type == "CUSTOMER",
            support_conversations.c.requester_user_id == customer_id,
            support_messages.c.sender_type == "SUPPORT_AGENT",
            support_messages.c.visibility == "PUBLIC",
            support_messages.c.redacted_at.is_(None),
            delivery.c.read_at.is_(None),
        )
        .group_by(support_messages.c.conversation_id)
    )
    if conversation_ids is not None:
        statement = statement.where(support_messages.c.conversation_id.in_(conversation_ids))
    return {str(row[0]): int(row[1]) for row in db.execute(statement).all()}


@router.get("/unread")
def unread_summary(
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    counts = customer_support_unread_counts(db, current.user_id)
    items: list[dict[str, object]] = []
    if counts:
        rows = db.execute(
            select(
                support_conversations.c.id,
                support_conversations.c.reference,
            ).where(
                support_conversations.c.requester_type == "CUSTOMER",
                support_conversations.c.requester_user_id == current.user_id,
                support_conversations.c.id.in_(list(counts)),
            )
        ).all()
        items = [
            {
                "reference": str(reference),
                "unread_count": counts.get(str(conversation_id), 0),
            }
            for conversation_id, reference in rows
            if counts.get(str(conversation_id), 0) > 0
        ]
    _no_store(response)
    return {
        "total_unread": sum(counts.values()),
        "tickets_with_unread": len(items),
        "items": items,
    }


@router.post("/tickets/{reference}/read")
def mark_ticket_read(
    reference: str,
    body: MarkReadRequest,
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> dict[str, int]:
    _require_csrf(db, settings, current, x_csrf_token)
    row = owned_customer_support_conversation(db, current.user_id, reference, lock=True)
    conversation_id = str(row["id"])

    message_ids = list(
        db.scalars(
            select(support_messages.c.id).where(
                support_messages.c.conversation_id == conversation_id,
                support_messages.c.sequence <= body.through_sequence,
                support_messages.c.sender_type == "SUPPORT_AGENT",
                support_messages.c.visibility == "PUBLIC",
                support_messages.c.redacted_at.is_(None),
            )
        ).all()
    )
    if message_ids:
        now = datetime.now(UTC)
        for message_id in message_ids:
            insert_statement = postgresql.insert(support_message_deliveries).values(
                id=str(uuid4()),
                message_id=message_id,
                participant_type="CUSTOMER",
                participant_id=current.user_id,
                delivered_at=now,
                read_at=now,
            )
            db.execute(
                insert_statement.on_conflict_do_update(
                    index_elements=[
                        support_message_deliveries.c.message_id,
                        support_message_deliveries.c.participant_type,
                        support_message_deliveries.c.participant_id,
                    ],
                    set_={
                        "delivered_at": func.coalesce(
                            support_message_deliveries.c.delivered_at,
                            insert_statement.excluded.delivered_at,
                        ),
                        "read_at": insert_statement.excluded.read_at,
                    },
                )
            )
    db.commit()

    remaining = customer_support_unread_counts(db, current.user_id, [conversation_id]).get(
        conversation_id, 0
    )
    _no_store(response)
    return {"unread_count": remaining}
