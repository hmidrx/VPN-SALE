"""Admin operations for durable support SLA escalations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import sanitize_metadata
from vpnsale_domain.support import SupportDomainError, sanitize_message

from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, AuditLogModel
from platform_api.management import require_perm
from platform_api.support_runtime_models import support_conversations
from platform_api.support_sla_models import support_notifications, support_sla_escalations

router = APIRouter(prefix="/api/v1/admin/support-runtime", tags=["admin-support-sla"])


class ManualEscalationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int = Field(gt=0)


class AcknowledgeEscalationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


def _clean_optional(value: str | None, limit: int) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        cleaned = sanitize_message(value, limit)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_text_invalid") from exc
    return cleaned or None


def _conversation(db: Session, reference: str, *, lock: bool = False) -> Any:
    statement = select(support_conversations).where(support_conversations.c.reference == reference)
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def _audit(
    db: Session,
    request: Request,
    admin_id: str,
    event_code: str,
    conversation: Any,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type="support_conversation",
            target_id=str(conversation["id"]),
            event_code=event_code,
            occurred_at=datetime.now(UTC),
            correlation_id=(
                request.headers.get("x-request-id")
                or request.headers.get("x-correlation-id")
                or "local"
            ),
            metadata_=sanitize_metadata(
                {"ticket_reference": str(conversation["reference"]), **metadata}
            ),
        )
    )


def _item(escalation: Any, conversation: Any) -> dict[str, object]:
    return {
        "reference": str(escalation["reference"]),
        "ticket_reference": str(conversation["reference"]),
        "ticket_status": str(conversation["status"]),
        "priority": str(conversation["priority"]),
        "kind": str(escalation["kind"]),
        "phase": str(escalation["phase"]),
        "source": str(escalation["source"]),
        "status": str(escalation["status"]),
        "deadline_at": (
            escalation["deadline_at"].isoformat()
            if escalation["deadline_at"] is not None
            else None
        ),
        "observed_at": escalation["observed_at"].isoformat(),
        "acknowledged_at": (
            escalation["acknowledged_at"].isoformat()
            if escalation["acknowledged_at"] is not None
            else None
        ),
        "created_at": escalation["created_at"].isoformat(),
    }


@router.get("/sla/escalations")
def list_sla_escalations(
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.sla.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status_filter: str = "OPEN",
    limit: int = 50,
) -> dict[str, object]:
    if status_filter not in {"OPEN", "ACKNOWLEDGED", "ALL"}:
        raise HTTPException(status_code=422, detail="support_sla_status_invalid")
    bounded = min(max(limit, 1), 100)
    statement = (
        select(support_sla_escalations, support_conversations)
        .join(
            support_conversations,
            support_conversations.c.id == support_sla_escalations.c.conversation_id,
        )
        .order_by(support_sla_escalations.c.created_at.desc())
        .limit(bounded)
    )
    if status_filter != "ALL":
        statement = statement.where(support_sla_escalations.c.status == status_filter)
    rows = db.execute(statement).mappings().all()
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "items": [
            _item(
                {column.name: row[column] for column in support_sla_escalations.c},
                {column.name: row[column] for column in support_conversations.c},
            )
            for row in rows
        ]
    }


@router.get("/conversations/{reference}/sla/escalations")
def conversation_sla_escalations(
    reference: str,
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.sla.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    conversation = _conversation(db, reference)
    rows = (
        db.execute(
            select(support_sla_escalations)
            .where(support_sla_escalations.c.conversation_id == conversation["id"])
            .order_by(support_sla_escalations.c.created_at.desc())
            .limit(100)
        )
        .mappings()
        .all()
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": [_item(row, conversation) for row in rows]}


@router.post("/conversations/{reference}/escalate")
def manually_escalate(
    reference: str,
    body: ManualEscalationRequest,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.escalate"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    conversation = _conversation(db, reference, lock=True)
    if int(conversation["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    if str(conversation["status"]) in {"RESOLVED", "CLOSED", "SPAM", "ARCHIVED"}:
        raise HTTPException(status_code=409, detail="ticket_not_escalatable")
    reason = _clean_optional(body.reason, 500)
    if reason is None:
        raise HTTPException(status_code=422, detail="support_text_invalid")

    now = datetime.now(UTC)
    escalation_reference = f"SLA-{uuid4().hex[:24]}"
    db.execute(
        support_sla_escalations.insert().values(
            id=str(uuid4()),
            reference=escalation_reference,
            conversation_id=conversation["id"],
            kind="MANUAL",
            phase="MANUAL",
            source="MANUAL",
            deadline_at=None,
            observed_at=now,
            status="OPEN",
            created_by=admin.id,
            acknowledged_by=None,
            acknowledged_at=None,
            created_at=now,
        )
    )
    db.execute(
        support_notifications.insert().values(
            id=str(uuid4()),
            conversation_id=conversation["id"],
            event_type="SUPPORT_MANUAL_ESCALATION",
            channel="ADMIN_WEB",
            safe_payload={
                "escalation_reference": escalation_reference,
                "ticket_reference": str(conversation["reference"]),
                "kind": "MANUAL",
                "phase": "MANUAL",
                "priority": str(conversation["priority"]),
            },
            status="PENDING",
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
        )
    )
    _audit(
        db,
        request,
        admin.id,
        "support.sla.manually_escalated",
        conversation,
        {"escalation_reference": escalation_reference, "reason": reason},
    )
    db.commit()
    escalation = (
        db.execute(
            select(support_sla_escalations).where(
                support_sla_escalations.c.reference == escalation_reference
            )
        )
        .mappings()
        .one()
    )
    return _item(escalation, conversation)


@router.post("/sla/escalations/{escalation_reference}/acknowledge")
def acknowledge_sla_escalation(
    escalation_reference: str,
    body: AcknowledgeEscalationRequest,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.escalate"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    escalation = (
        db.execute(
            select(support_sla_escalations)
            .where(support_sla_escalations.c.reference == escalation_reference)
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if escalation is None:
        raise HTTPException(status_code=404, detail="support_sla_escalation_not_found")
    conversation = (
        db.execute(
            select(support_conversations).where(
                support_conversations.c.id == escalation["conversation_id"]
            )
        )
        .mappings()
        .one()
    )
    if escalation["status"] == "OPEN":
        now = datetime.now(UTC)
        db.execute(
            update(support_sla_escalations)
            .where(support_sla_escalations.c.id == escalation["id"])
            .values(status="ACKNOWLEDGED", acknowledged_by=admin.id, acknowledged_at=now)
        )
        note = _clean_optional(body.note, 500)
        _audit(
            db,
            request,
            admin.id,
            "support.sla.escalation_acknowledged",
            conversation,
            {
                "escalation_reference": escalation_reference,
                **({"note": note} if note is not None else {}),
            },
        )
        db.commit()
    refreshed = (
        db.execute(
            select(support_sla_escalations).where(
                support_sla_escalations.c.id == escalation["id"]
            )
        )
        .mappings()
        .one()
    )
    return _item(refreshed, conversation)
