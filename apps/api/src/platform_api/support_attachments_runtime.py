"""Private customer support image attachments and permission-gated agent retrieval."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from vpnsale_domain.support import LEGAL_TRANSITIONS, SupportStatus

from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, TelegramAccountModel, UserModel
from platform_api.management import require_perm
from platform_api.support_attachment_storage import (
    ALLOWED_SUPPORT_IMAGE_TYPES,
    InvalidSupportAttachment,
    LocalPrivateSupportAttachmentStorage,
)
from platform_api.support_runtime_models import (
    support_attachments,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_internal import Database, InternalAuth

telegram_router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-support-attachments"],
    include_in_schema=False,
)
admin_router = APIRouter(
    prefix="/api/v1/admin/support-runtime",
    tags=["admin-support-attachments"],
)

_ATTACHMENT_BODY = "📎 تصویر پیوست شد."


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _customer_id(db: Session, telegram_id: int) -> str:
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
    return str(user.id)


def _conversation(
    db: Session,
    reference: str,
    *,
    customer_id: str | None = None,
    lock: bool = False,
) -> Any:
    statement = select(support_conversations).where(
        support_conversations.c.reference == reference,
    )
    if customer_id is not None:
        statement = statement.where(
            support_conversations.c.requester_type == "CUSTOMER",
            support_conversations.c.requester_user_id == customer_id,
        )
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).mappings().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


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
        values.update(_resume_deadlines(db, row, now))
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
            reason=reason,
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


def _advance_after_customer_attachment(db: Session, row: Any, customer_id: str, now: datetime) -> None:
    current_status = str(row["status"])
    if current_status == SupportStatus.WAITING_FOR_CUSTOMER.value:
        current_status = _transition(
            db,
            row,
            current_status,
            SupportStatus.IN_PROGRESS,
            actor_id=customer_id,
            reason="Customer attached an image while support was waiting for customer",
            now=now,
        )
    elif current_status in {SupportStatus.RESOLVED.value, SupportStatus.CLOSED.value}:
        current_status = _transition(
            db,
            row,
            current_status,
            SupportStatus.REOPENED,
            actor_id=customer_id,
            reason="Customer attached an image after resolution or closure",
            now=now,
        )
    if current_status in {SupportStatus.IN_PROGRESS.value, SupportStatus.REOPENED.value}:
        _transition(
            db,
            row,
            current_status,
            SupportStatus.WAITING_FOR_SUPPORT,
            actor_id=customer_id,
            reason="Customer image attachment is waiting for support",
            now=now,
        )


async def _read_bounded(request: Request, maximum_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > maximum_bytes:
            raise HTTPException(status_code=413, detail="support_attachment_too_large")
        if chunk:
            chunks.append(chunk)
    if not chunks:
        raise HTTPException(status_code=422, detail="support_attachment_invalid")
    return b"".join(chunks)


def _resource_value(asset_reference: str, digest: str) -> str:
    return f"{asset_reference}|{digest[:32]}"


def _parse_resource(value: str) -> tuple[str, str | None]:
    reference, separator, digest = value.partition("|")
    return reference, digest if separator else None


def _attachment_dto(db: Session, conversation_id: str, asset_reference: str) -> dict[str, object]:
    row = db.execute(
        select(
            support_attachments.c.asset_reference,
            support_attachments.c.normalized_filename,
            support_attachments.c.content_type,
            support_attachments.c.byte_size,
            support_attachments.c.created_at,
            support_messages.c.sequence,
        )
        .join(support_messages, support_messages.c.id == support_attachments.c.message_id)
        .where(
            support_attachments.c.conversation_id == conversation_id,
            support_attachments.c.asset_reference == asset_reference,
            support_attachments.c.state == "READY",
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=503, detail="support_retry")
    return {
        "asset_reference": str(row[0]),
        "message_sequence": int(row[5]),
        "filename": str(row[1]),
        "content_type": str(row[2]),
        "byte_size": int(row[3]),
        "created_at": row[4].isoformat(),
    }


@telegram_router.post("/support/tickets/{reference}/attachments")
async def upload_customer_support_attachment(
    reference: str,
    request: Request,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    row = _conversation(db, reference, customer_id=customer_id, lock=True)
    current_status = str(row["status"])
    if current_status in {SupportStatus.SPAM.value, SupportStatus.ARCHIVED.value}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_SUPPORT_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="support_attachment_type_invalid")
    raw = await _read_bounded(request, settings.support_max_attachment_bytes)
    payload_digest = hashlib.sha256(
        content_type.encode() + b"\x00" + hashlib.sha256(raw).digest()
    ).hexdigest()
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    scope = f"tg-att:{reference}"
    existing_resource = db.scalar(
        select(support_idempotency_records.c.resource_reference).where(
            support_idempotency_records.c.scope == scope,
            support_idempotency_records.c.key_hash == key_hash,
        )
    )
    if existing_resource:
        asset_reference, stored_digest = _parse_resource(str(existing_resource))
        if stored_digest != payload_digest[:32]:
            raise HTTPException(status_code=409, detail="idempotency_conflict")
        payload = _attachment_dto(db, str(row["id"]), asset_reference)
        _no_store(response)
        return payload

    count = int(
        db.scalar(
            select(func.count())
            .select_from(support_attachments)
            .where(support_attachments.c.conversation_id == row["id"])
        )
        or 0
    )
    if count >= settings.support_max_attachments_per_conversation:
        raise HTTPException(status_code=409, detail="support_attachment_limit")

    asset_reference = f"SAT-{uuid4().hex[:24]}"
    storage = LocalPrivateSupportAttachmentStorage(
        Path(settings.support_private_upload_root),
        maximum_bytes=settings.support_max_attachment_bytes,
        dimension_limit=settings.support_image_dimension_limit,
    )
    try:
        stored = storage.store(asset_reference, io.BytesIO(raw), content_type)
    except InvalidSupportAttachment as exc:
        raise HTTPException(status_code=422, detail="support_attachment_invalid") from exc

    suffix = stored.suffix
    filename = f"support-image-{asset_reference[-8:]}{suffix}"
    message_id = str(uuid4())
    now = datetime.now(UTC)
    try:
        last_sequence = db.scalar(
            select(func.max(support_messages.c.sequence)).where(
                support_messages.c.conversation_id == row["id"]
            )
        )
        sequence = int(last_sequence or 0) + 1
        db.execute(
            support_messages.insert().values(
                id=message_id,
                conversation_id=row["id"],
                sequence=sequence,
                sender_type="CUSTOMER",
                sender_id=customer_id,
                channel="TELEGRAM_BOT",
                message_type="CUSTOMER_ATTACHMENT",
                visibility="PUBLIC",
                body=_ATTACHMENT_BODY,
                body_sha256=hashlib.sha256(_ATTACHMENT_BODY.encode()).hexdigest(),
                client_idempotency_key=f"tg-attachment:{key_hash}",
                created_at=now,
            )
        )
        db.execute(
            support_attachments.insert().values(
                id=str(uuid4()),
                conversation_id=row["id"],
                message_id=message_id,
                asset_reference=asset_reference,
                normalized_filename=filename,
                content_type=stored.media_type,
                byte_size=stored.byte_size,
                sha256=stored.sanitized_sha256,
                state="READY",
                created_by=customer_id,
                created_at=now,
            )
        )
        db.execute(
            support_idempotency_records.insert().values(
                id=str(uuid4()),
                scope=scope,
                key_hash=key_hash,
                resource_reference=_resource_value(asset_reference, payload_digest),
                created_at=now,
            )
        )
        db.execute(
            update(support_conversations)
            .where(support_conversations.c.id == row["id"])
            .values(updated_at=now, version=support_conversations.c.version + 1)
        )
        _advance_after_customer_attachment(db, row, customer_id, now)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(asset_reference)
        raise

    payload = _attachment_dto(db, str(row["id"]), asset_reference)
    _no_store(response)
    return payload


@admin_router.get("/conversations/{reference}/attachments")
def list_support_attachments(
    reference: str,
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.attachments.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    row = _conversation(db, reference)
    attachments = db.execute(
        select(
            support_attachments.c.asset_reference,
            support_attachments.c.normalized_filename,
            support_attachments.c.content_type,
            support_attachments.c.byte_size,
            support_attachments.c.created_at,
            support_messages.c.sequence,
        )
        .join(support_messages, support_messages.c.id == support_attachments.c.message_id)
        .where(
            support_attachments.c.conversation_id == row["id"],
            support_attachments.c.state == "READY",
        )
        .order_by(support_messages.c.sequence.asc(), support_attachments.c.created_at.asc())
        .limit(50)
    ).all()
    _no_store(response)
    return {
        "items": [
            {
                "asset_reference": str(item[0]),
                "message_sequence": int(item[5]),
                "filename": str(item[1]),
                "content_type": str(item[2]),
                "byte_size": int(item[3]),
                "created_at": item[4].isoformat(),
            }
            for item in attachments
        ]
    }


@admin_router.get("/conversations/{reference}/attachments/{asset_reference}")
def download_support_attachment(
    reference: str,
    asset_reference: str,
    _: Annotated[AdminModel, Depends(require_perm("support.attachments.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    row = _conversation(db, reference)
    attachment = db.execute(
        select(
            support_attachments.c.normalized_filename,
            support_attachments.c.content_type,
        ).where(
            support_attachments.c.conversation_id == row["id"],
            support_attachments.c.asset_reference == asset_reference,
            support_attachments.c.state == "READY",
        )
    ).one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="support_attachment_not_found")
    storage = LocalPrivateSupportAttachmentStorage(Path(settings.support_private_upload_root))
    try:
        source = storage.open(asset_reference)
    except (OSError, InvalidSupportAttachment) as exc:
        raise HTTPException(status_code=404, detail="support_attachment_not_found") from exc
    filename = str(attachment[0])
    content_type = str(attachment[1])
    return StreamingResponse(
        source,
        media_type=content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
