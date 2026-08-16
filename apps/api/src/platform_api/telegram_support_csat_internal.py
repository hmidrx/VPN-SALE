"""Durable customer CSAT API for native Telegram support."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from vpnsale_domain.support import SupportDomainError, SupportStatus, sanitize_message

from .identity.models import TelegramAccountModel, UserModel
from .support_runtime_models import (
    support_conversations,
    support_csat,
    support_status_history,
)
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-support-csat"],
    include_in_schema=False,
)


class SubmitCsatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    feedback: str | None = Field(default=None, max_length=800)


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


def _resolution_cycle(db: Database, conversation_id: str) -> int:
    value = db.scalar(
        select(func.count())
        .select_from(support_status_history)
        .where(
            support_status_history.c.conversation_id == conversation_id,
            support_status_history.c.to_status == SupportStatus.REOPENED.value,
        )
    )
    return int(value or 0)


def _clean_feedback(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        cleaned = sanitize_message(value, 800)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_csat_feedback_invalid") from exc
    if not cleaned:
        return None
    return cleaned


def _existing_csat(db: Database, conversation_id: str, cycle: int) -> Any:
    return (
        db.execute(
            select(support_csat.c.score, support_csat.c.feedback).where(
                support_csat.c.conversation_id == conversation_id,
                support_csat.c.resolution_cycle == cycle,
            )
        )
        .mappings()
        .one_or_none()
    )


def _state(db: Database, row: Any) -> dict[str, object]:
    cycle = _resolution_cycle(db, str(row["id"]))
    existing = _existing_csat(db, str(row["id"]), cycle)
    submitted = existing is not None
    eligible_status = str(row["status"]) in {
        SupportStatus.RESOLVED.value,
        SupportStatus.CLOSED.value,
    }
    return {
        "eligible": eligible_status and not submitted,
        "submitted": submitted,
        "score": int(existing["score"]) if existing is not None else None,
    }


def _same_submission(existing: Any, score: int, feedback: str | None) -> bool:
    return int(existing["score"]) == score and (existing["feedback"] or None) == feedback


@router.get("/support/tickets/{reference}/csat")
def csat_state(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    row = _conversation(db, customer_id, reference)
    payload = _state(db, row)
    _no_store(response)
    return payload


@router.post("/support/tickets/{reference}/csat")
def submit_csat(
    reference: str,
    body: SubmitCsatRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    del (
        idempotency_key
    )  # the (conversation, resolution_cycle) unique key is the durable idempotency anchor
    customer_id = _customer_id(db, x_telegram_subject)
    row = _conversation(db, customer_id, reference, lock=True)
    if str(row["status"]) not in {
        SupportStatus.RESOLVED.value,
        SupportStatus.CLOSED.value,
    }:
        raise HTTPException(status_code=409, detail="support_csat_not_eligible")

    feedback = _clean_feedback(body.feedback)
    conversation_id = str(row["id"])
    cycle = _resolution_cycle(db, conversation_id)
    existing = _existing_csat(db, conversation_id, cycle)
    if existing is not None:
        if not _same_submission(existing, body.score, feedback):
            raise HTTPException(status_code=409, detail="support_csat_already_submitted")
        db.commit()
        payload = _state(db, row)
        _no_store(response)
        return payload

    now = datetime.now(UTC)
    inserted = db.execute(
        postgresql.insert(support_csat)
        .values(
            id=str(uuid4()),
            conversation_id=conversation_id,
            resolution_cycle=cycle,
            score=body.score,
            feedback=feedback,
            channel="TELEGRAM_BOT",
            submitted_at=now,
        )
        .on_conflict_do_nothing(
            index_elements=[support_csat.c.conversation_id, support_csat.c.resolution_cycle]
        )
        .returning(support_csat.c.id)
    ).scalar_one_or_none()
    if inserted is None:
        existing = _existing_csat(db, conversation_id, cycle)
        if existing is None:
            db.rollback()
            raise HTTPException(status_code=503, detail="support_csat_retry")
        if not _same_submission(existing, body.score, feedback):
            db.rollback()
            raise HTTPException(status_code=409, detail="support_csat_already_submitted")

    db.commit()
    refreshed = _conversation(db, customer_id, reference)
    payload = _state(db, refreshed)
    _no_store(response)
    return payload
