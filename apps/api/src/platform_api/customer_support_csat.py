"""Authenticated customer-web CSAT over the shared durable support store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from vpnsale_domain.support import SupportStatus

from .config import Settings, get_settings
from .customer_auth.routes import current_customer_session_dependency
from .customer_auth.service import CustomerAuthService
from .customer_support_contract import (
    clean_customer_support_text,
    owned_customer_support_conversation,
)
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .support_runtime_models import support_csat, support_status_history

router = APIRouter(prefix="/api/v1/customer/support", tags=["customer-support-csat"])


class SubmitCsatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=1, le=5)
    feedback: str | None = Field(default=None, max_length=800)


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


def _resolution_cycle(db: Session, conversation_id: str) -> int:
    value = db.scalar(
        select(func.count())
        .select_from(support_status_history)
        .where(
            support_status_history.c.conversation_id == conversation_id,
            support_status_history.c.to_status == SupportStatus.REOPENED.value,
        )
    )
    return int(value or 0)


def _existing_csat(db: Session, conversation_id: str, cycle: int) -> Any:
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


def _clean_feedback(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return clean_customer_support_text(value, limit=800)


def _state(db: Session, row: Any) -> dict[str, object]:
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


@router.get("/tickets/{reference}/csat")
def csat_state(
    reference: str,
    response: Response,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = owned_customer_support_conversation(db, current.user_id, reference)
    payload = _state(db, row)
    _no_store(response)
    return payload


@router.post("/tickets/{reference}/csat")
def submit_csat(
    reference: str,
    body: SubmitCsatRequest,
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
    del idempotency_key
    _require_csrf(db, settings, current, x_csrf_token)
    row = owned_customer_support_conversation(db, current.user_id, reference, lock=True)
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

    inserted = db.execute(
        postgresql.insert(support_csat)
        .values(
            id=str(uuid4()),
            conversation_id=conversation_id,
            resolution_cycle=cycle,
            score=body.score,
            feedback=feedback,
            channel="CUSTOMER_WEB",
            submitted_at=datetime.now(UTC),
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
    refreshed = owned_customer_support_conversation(db, current.user_id, reference)
    payload = _state(db, refreshed)
    _no_store(response)
    return payload
