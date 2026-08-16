"""Durable PostgreSQL-backed support inbox and agent operations."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import sanitize_metadata
from vpnsale_domain.support import (
    LEGAL_TRANSITIONS,
    SupportDomainError,
    SupportStatus,
    sanitize_message,
)

from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, AuditLogModel
from platform_api.management import require_perm
from platform_api.support_runtime_models import (
    support_assignments,
    support_conversations,
    support_messages,
    support_status_history,
)

router = APIRouter(prefix="/api/v1/admin/support-runtime", tags=["admin-support-runtime"])


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)


class AgentMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)
    expected_version: int = Field(gt=0)


class StatusChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: SupportStatus
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int = Field(gt=0)


def _clean(value: str, limit: int) -> str:
    try:
        cleaned = sanitize_message(value, limit)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_text_invalid") from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="support_text_invalid")
    return cleaned


def _conversation(db: Session, reference: str, *, lock: bool = False) -> Any:
    statement = select(support_conversations).where(support_conversations.c.reference == reference)
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def _summary(row: Any, admin_id: str) -> dict[str, object]:
    return {
        "reference": str(row["reference"]),
        "subject": str(row["subject"]),
        "status": str(row["status"]),
        "priority": str(row["priority"]),
        "channel": str(row["channel"]),
        "assigned_to_me": row["assigned_agent_id"] == admin_id,
        "assigned": row["assigned_agent_id"] is not None,
        "version": int(row["version"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "first_response_deadline": (
            row["first_response_deadline"].isoformat()
            if row["first_response_deadline"] is not None
            else None
        ),
        "resolution_deadline": (
            row["resolution_deadline"].isoformat()
            if row["resolution_deadline"] is not None
            else None
        ),
    }


def _messages(
    db: Session,
    conversation_id: str,
    *,
    visibility: str,
    message_type: str | None = None,
) -> list[dict[str, object]]:
    statement = select(
        support_messages.c.sequence,
        support_messages.c.sender_type,
        support_messages.c.message_type,
        support_messages.c.visibility,
        support_messages.c.body,
        support_messages.c.created_at,
    ).where(
        support_messages.c.conversation_id == conversation_id,
        support_messages.c.visibility == visibility,
        support_messages.c.redacted_at.is_(None),
    )
    if message_type is not None:
        statement = statement.where(support_messages.c.message_type == message_type)
    newest = (
        db.execute(statement.order_by(support_messages.c.sequence.desc()).limit(100))
        .mappings()
        .all()
    )
    rows = list(reversed(newest))
    return [
        {
            "sequence": int(message["sequence"]),
            "sender_type": str(message["sender_type"]),
            "message_type": str(message["message_type"]),
            "visibility": str(message["visibility"]),
            "body": str(message["body"]),
            "created_at": message["created_at"].isoformat(),
        }
        for message in rows
    ]


def _detail(db: Session, reference: str, admin_id: str) -> dict[str, object]:
    row = _conversation(db, reference)
    return {
        **_summary(row, admin_id),
        "messages": _messages(db, str(row["id"]), visibility="PUBLIC"),
    }


def _audit(
    db: Session,
    request: Request,
    admin_id: str,
    event_code: str,
    row: Any,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type="support_conversation",
            target_id=str(row["id"]),
            event_code=event_code,
            occurred_at=datetime.now(UTC),
            correlation_id=(
                request.headers.get("x-request-id")
                or request.headers.get("x-correlation-id")
                or "local"
            ),
            metadata_=sanitize_metadata(
                {"ticket_reference": str(row["reference"]), **(metadata or {})}
            ),
        )
    )


def _resume_deadlines(db: Session, row: Any, now: datetime) -> dict[str, datetime | None]:
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
    db: Session,
    row: Any,
    target: SupportStatus,
    *,
    actor_id: str,
    reason: str,
    now: datetime,
) -> None:
    current = SupportStatus(str(row["status"]))
    if target not in LEGAL_TRANSITIONS[current]:
        raise HTTPException(status_code=409, detail="ticket_transition_invalid")
    values: dict[str, object] = {
        "status": target.value,
        "updated_at": now,
        "version": support_conversations.c.version + 1,
    }
    if current == SupportStatus.WAITING_FOR_CUSTOMER:
        values.update(_resume_deadlines(db, row, now))
    if target == SupportStatus.RESOLVED:
        values["resolved_at"] = now
    if target == SupportStatus.CLOSED:
        values["closed_at"] = now
    if target == SupportStatus.REOPENED:
        values["resolved_at"] = None
        values["closed_at"] = None
    db.execute(
        support_status_history.insert().values(
            id=str(uuid4()),
            conversation_id=row["id"],
            from_status=current.value,
            to_status=target.value,
            reason=_clean(reason, 500),
            created_by=actor_id,
            created_at=now,
        )
    )
    db.execute(
        update(support_conversations)
        .where(support_conversations.c.id == row["id"])
        .values(**values)
    )


def _message_key(prefix: str, admin_id: str, key: str) -> str:
    digest = sha256(f"{admin_id}:{key}".encode()).hexdigest()
    return f"admin:{prefix}:{digest}"


def _insert_agent_message(
    db: Session,
    row: Any,
    *,
    admin_id: str,
    body: str,
    key: str,
    internal: bool,
) -> bool:
    message_key = _message_key("note" if internal else "reply", admin_id, key)
    digest = sha256(body.encode()).hexdigest()
    existing = db.execute(
        select(support_messages.c.id, support_messages.c.body_sha256).where(
            support_messages.c.conversation_id == row["id"],
            support_messages.c.client_idempotency_key == message_key,
        )
    ).one_or_none()
    if existing is not None:
        if str(existing[1]) != digest:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        return False
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
            sender_type="SUPPORT_AGENT",
            sender_id=admin_id,
            channel="ADMIN_WEB",
            message_type="INTERNAL_NOTE" if internal else "AGENT_MESSAGE",
            visibility="AGENT_ONLY" if internal else "PUBLIC",
            body=body,
            body_sha256=digest,
            client_idempotency_key=message_key,
            created_at=now,
        )
    )
    db.execute(
        update(support_conversations)
        .where(support_conversations.c.id == row["id"])
        .values(updated_at=now, version=support_conversations.c.version + 1)
    )
    return True


@router.get("/conversations")
def inbox(
    response: Response,
    admin: Annotated[AdminModel, Depends(require_perm("support.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status_filter: SupportStatus | None = None,
    limit: int = 50,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 100)
    statement = select(support_conversations)
    if status_filter is not None:
        statement = statement.where(support_conversations.c.status == status_filter.value)
    rows = (
        db.execute(
            statement.order_by(support_conversations.c.updated_at.desc()).limit(bounded_limit)
        )
        .mappings()
        .all()
    )
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": [_summary(row, admin.id) for row in rows]}


@router.get("/conversations/{reference}")
def conversation_detail(
    reference: str,
    response: Response,
    admin: Annotated[AdminModel, Depends(require_perm("support.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    response.headers["Cache-Control"] = "private, no-store"
    return _detail(db, reference, admin.id)


@router.get("/conversations/{reference}/internal-notes")
def internal_notes(
    reference: str,
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.internal_notes.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = _conversation(db, reference)
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "items": _messages(
            db,
            str(row["id"]),
            visibility="AGENT_ONLY",
            message_type="INTERNAL_NOTE",
        )
    }


@router.post("/conversations/{reference}/claim")
def claim_conversation(
    reference: str,
    body: ClaimRequest,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.assign"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = _conversation(db, reference, lock=True)
    if int(row["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    assigned = row["assigned_agent_id"]
    if assigned is not None and str(assigned) != admin.id:
        raise HTTPException(status_code=409, detail="ticket_assignment_conflict")
    if assigned is None:
        now = datetime.now(UTC)
        db.execute(
            support_assignments.insert().values(
                id=str(uuid4()),
                conversation_id=row["id"],
                from_agent_id=None,
                to_agent_id=admin.id,
                from_queue_id=row["queue_id"],
                to_queue_id=row["queue_id"],
                reason="CLAIM",
                created_by=admin.id,
                created_at=now,
            )
        )
        current_status = SupportStatus(str(row["status"]))
        values: dict[str, object] = {
            "assigned_agent_id": admin.id,
            "updated_at": now,
            "version": support_conversations.c.version + 1,
        }
        if current_status in {SupportStatus.NEW, SupportStatus.OPEN}:
            values["status"] = SupportStatus.ASSIGNED.value
            db.execute(
                support_status_history.insert().values(
                    id=str(uuid4()),
                    conversation_id=row["id"],
                    from_status=current_status.value,
                    to_status=SupportStatus.ASSIGNED.value,
                    reason="Agent claimed conversation",
                    created_by=admin.id,
                    created_at=now,
                )
            )
        db.execute(
            update(support_conversations)
            .where(support_conversations.c.id == row["id"])
            .values(**values)
        )
        _audit(db, request, admin.id, "support.conversation.claimed", row)
        db.commit()
    return _detail(db, reference, admin.id)


@router.post("/conversations/{reference}/reply")
def reply_conversation(
    reference: str,
    body: AgentMessageRequest,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.reply"))],
    db: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    message = _clean(body.body, 4000)
    row = _conversation(db, reference, lock=True)
    key = _message_key("reply", admin.id, idempotency_key)
    existing = db.execute(
        select(support_messages.c.body_sha256).where(
            support_messages.c.conversation_id == row["id"],
            support_messages.c.client_idempotency_key == key,
        )
    ).one_or_none()
    digest = sha256(message.encode()).hexdigest()
    if existing is not None:
        if str(existing[0]) != digest:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        return _detail(db, reference, admin.id)
    if int(row["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    if str(row["status"]) in {
        SupportStatus.RESOLVED.value,
        SupportStatus.CLOSED.value,
        SupportStatus.SPAM.value,
        SupportStatus.ARCHIVED.value,
    }:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")
    _insert_agent_message(
        db,
        row,
        admin_id=admin.id,
        body=message,
        key=idempotency_key,
        internal=False,
    )
    _audit(db, request, admin.id, "support.message.replied", row, {"visibility": "PUBLIC"})
    db.commit()
    return _detail(db, reference, admin.id)


@router.post("/conversations/{reference}/internal-notes")
def add_internal_note(
    reference: str,
    body: AgentMessageRequest,
    request: Request,
    admin: Annotated[
        AdminModel,
        Depends(require_perm("support.internal_notes.manage")),
    ],
    db: Annotated[Session, Depends(get_db_session)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    note = _clean(body.body, 4000)
    row = _conversation(db, reference, lock=True)
    key = _message_key("note", admin.id, idempotency_key)
    existing = db.execute(
        select(support_messages.c.body_sha256).where(
            support_messages.c.conversation_id == row["id"],
            support_messages.c.client_idempotency_key == key,
        )
    ).one_or_none()
    digest = sha256(note.encode()).hexdigest()
    if existing is not None:
        if str(existing[0]) != digest:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        return {
            "items": _messages(
                db,
                str(row["id"]),
                visibility="AGENT_ONLY",
                message_type="INTERNAL_NOTE",
            )
        }
    if int(row["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    if str(row["status"]) == SupportStatus.ARCHIVED.value:
        raise HTTPException(status_code=409, detail="ticket_not_writable")
    _insert_agent_message(
        db,
        row,
        admin_id=admin.id,
        body=note,
        key=idempotency_key,
        internal=True,
    )
    _audit(
        db,
        request,
        admin.id,
        "support.internal_note.added",
        row,
        {"visibility": "AGENT_ONLY"},
    )
    db.commit()
    return {
        "items": _messages(
            db,
            str(row["id"]),
            visibility="AGENT_ONLY",
            message_type="INTERNAL_NOTE",
        )
    }


@router.post("/conversations/{reference}/status")
def change_status(
    reference: str,
    body: StatusChangeRequest,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.manage_status"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = _conversation(db, reference, lock=True)
    if int(row["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    now = datetime.now(UTC)
    _transition(
        db,
        row,
        body.status,
        actor_id=admin.id,
        reason=body.reason,
        now=now,
    )
    _audit(
        db,
        request,
        admin.id,
        "support.status.changed",
        row,
        {"from": str(row["status"]), "to": body.status.value},
    )
    db.commit()
    return _detail(db, reference, admin.id)
