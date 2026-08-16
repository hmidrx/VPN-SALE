"""Authenticated customer-web image attachments for durable support tickets."""

from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from vpnsale_domain.support import SupportStatus

from .config import Settings, get_settings
from .customer_auth.routes import current_customer_session_dependency
from .customer_auth.service import CustomerAuthService
from .customer_support_contract import (
    owned_customer_support_conversation,
    transition_customer_support,
)
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .support_attachment_storage import (
    ALLOWED_SUPPORT_IMAGE_TYPES,
    InvalidSupportAttachment,
    LocalPrivateSupportAttachmentStorage,
)
from .support_runtime_models import (
    support_attachments,
    support_conversations,
    support_idempotency_records,
    support_messages,
)

router = APIRouter(prefix="/api/v1/customer/support", tags=["customer-support-attachments"])

_ATTACHMENT_BODY = "📎 تصویر پیوست شد."


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


def _payload_digest(content_type: str, raw: bytes) -> str:
    return hashlib.sha256(
        content_type.encode() + b"\x00" + hashlib.sha256(raw).digest()
    ).hexdigest()


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


def _advance_after_customer_attachment(
    db: Session,
    row: object,
    customer_id: str,
    now: datetime,
) -> None:
    current_status = str(row["status"])  # type: ignore[index]
    if current_status == SupportStatus.WAITING_FOR_CUSTOMER.value:
        current_status = transition_customer_support(
            db,
            row,
            current_status,
            SupportStatus.IN_PROGRESS,
            actor_id=customer_id,
            reason="Customer attached an image from web while support was waiting for customer",
            now=now,
        )
    elif current_status in {SupportStatus.RESOLVED.value, SupportStatus.CLOSED.value}:
        current_status = transition_customer_support(
            db,
            row,
            current_status,
            SupportStatus.REOPENED,
            actor_id=customer_id,
            reason="Customer attached an image from web after resolution or closure",
            now=now,
        )
    if current_status in {SupportStatus.IN_PROGRESS.value, SupportStatus.REOPENED.value}:
        transition_customer_support(
            db,
            row,
            current_status,
            SupportStatus.WAITING_FOR_SUPPORT,
            actor_id=customer_id,
            reason="Customer web image attachment is waiting for support",
            now=now,
        )


@router.post("/tickets/{reference}/attachments")
async def upload_customer_web_attachment(
    reference: str,
    request: Request,
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

    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_SUPPORT_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="support_attachment_type_invalid")

    preflight = owned_customer_support_conversation(db, customer_id, reference)
    if str(preflight["status"]) in {SupportStatus.SPAM.value, SupportStatus.ARCHIVED.value}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")

    raw = await _read_bounded(request, settings.support_max_attachment_bytes)
    payload_digest = _payload_digest(content_type, raw)
    key_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    scope = f"web-att:{reference}"

    row = owned_customer_support_conversation(db, customer_id, reference, lock=True)
    if str(row["status"]) in {SupportStatus.SPAM.value, SupportStatus.ARCHIVED.value}:
        raise HTTPException(status_code=409, detail="ticket_not_replyable")

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

    attachment_count = int(
        db.scalar(
            select(func.count())
            .select_from(support_attachments)
            .where(support_attachments.c.conversation_id == row["id"])
        )
        or 0
    )
    if attachment_count >= settings.support_max_attachments_per_conversation:
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

    filename = f"support-image-{asset_reference[-8:]}{stored.suffix}"
    message_id = str(uuid4())
    now = datetime.now(UTC)
    try:
        last_sequence = db.scalar(
            select(func.max(support_messages.c.sequence)).where(
                support_messages.c.conversation_id == row["id"]
            )
        )
        db.execute(
            support_messages.insert().values(
                id=message_id,
                conversation_id=row["id"],
                sequence=int(last_sequence or 0) + 1,
                sender_type="CUSTOMER",
                sender_id=customer_id,
                channel="CUSTOMER_WEB",
                message_type="CUSTOMER_ATTACHMENT",
                visibility="PUBLIC",
                body=_ATTACHMENT_BODY,
                body_sha256=hashlib.sha256(_ATTACHMENT_BODY.encode()).hexdigest(),
                client_idempotency_key=f"web-attachment:{key_hash}",
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


@router.get("/tickets/{reference}/attachments/{asset_reference}")
def download_customer_support_attachment(
    reference: str,
    asset_reference: str,
    current: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    row = owned_customer_support_conversation(db, current.user_id, reference)
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
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
