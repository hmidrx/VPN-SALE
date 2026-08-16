"""Signed keyset pagination for the durable support read paths.

The legacy read endpoints stay available for compatibility, while this module exposes
pageable views for Telegram and Admin Web. Cursors are signed, audience-bound tokens;
they are navigation hints only and never replace ownership or RBAC checks.
"""

from __future__ import annotations

import base64
import hmac
import json
from datetime import UTC, datetime
from hashlib import sha256
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, TelegramAccountModel, UserModel
from platform_api.management import require_perm
from platform_api.support_runtime_models import support_conversations, support_messages
from platform_api.telegram_internal import Database, InternalAuth
from vpnsale_domain.support import SupportStatus

admin_router = APIRouter(
    prefix="/api/v1/admin/support-runtime",
    tags=["admin-support-pagination"],
)
telegram_router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-support-pagination"],
    include_in_schema=False,
)

_CURSOR_VERSION = 1
_MAX_CURSOR_LENGTH = 1024
_SIGNATURE_BYTES = 16


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _encode_cursor(secret: str, kind: str, payload: dict[str, object]) -> str:
    body = json.dumps(
        {"v": _CURSOR_VERSION, "k": kind, "p": payload},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = _b64encode(body)
    signature = hmac.new(secret.encode(), encoded.encode(), sha256).digest()[:_SIGNATURE_BYTES]
    return f"{encoded}.{_b64encode(signature)}"


def _decode_cursor(secret: str, kind: str, cursor: str) -> dict[str, object]:
    if not cursor or len(cursor) > _MAX_CURSOR_LENGTH or cursor.count(".") != 1:
        raise ValueError("invalid cursor")
    encoded, signature_text = cursor.split(".", 1)
    try:
        signature = _b64decode(signature_text)
        expected = hmac.new(secret.encode(), encoded.encode(), sha256).digest()[:_SIGNATURE_BYTES]
        if len(signature) != _SIGNATURE_BYTES or not hmac.compare_digest(signature, expected):
            raise ValueError("invalid cursor signature")
        decoded = json.loads(_b64decode(encoded))
    except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc
    if not isinstance(decoded, dict):
        raise ValueError("invalid cursor payload")
    value = cast(dict[str, object], decoded)
    payload = value.get("p")
    if value.get("v") != _CURSOR_VERSION or value.get("k") != kind or not isinstance(payload, dict):
        raise ValueError("invalid cursor binding")
    return cast(dict[str, object], payload)


def _cursor_error() -> HTTPException:
    return HTTPException(status_code=400, detail="support_cursor_invalid")


def _admin_secret(settings: Settings) -> str:
    return settings.admin_access_token_signing_key


def _customer_secret(settings: Settings) -> str:
    return settings.customer_access_token_signing_key


def _decode_conversation_cursor(secret: str, kind: str, cursor: str) -> tuple[datetime, str]:
    try:
        payload = _decode_cursor(secret, kind, cursor)
        updated_raw = payload.get("u")
        reference = payload.get("r")
        if not isinstance(updated_raw, str) or not isinstance(reference, str) or not reference:
            raise ValueError("invalid conversation cursor")
        updated_at = datetime.fromisoformat(updated_raw)
        if updated_at.tzinfo is None:
            raise ValueError("naive conversation cursor")
        return updated_at.astimezone(UTC), reference
    except ValueError as exc:
        raise _cursor_error() from exc


def _decode_message_cursor(secret: str, kind: str, cursor: str) -> int:
    try:
        payload = _decode_cursor(secret, kind, cursor)
        sequence = payload.get("s")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
            raise ValueError("invalid message cursor")
        return sequence
    except ValueError as exc:
        raise _cursor_error() from exc


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
    return str(user.id)


def _customer_conversation(db: Database, customer_id: str, reference: str) -> Any:
    row = (
        db.execute(
            select(support_conversations).where(
                support_conversations.c.reference == reference,
                support_conversations.c.requester_type == "CUSTOMER",
                support_conversations.c.requester_user_id == customer_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def _admin_conversation(db: Session, reference: str) -> Any:
    row = (
        db.execute(
            select(support_conversations).where(support_conversations.c.reference == reference)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def _customer_summary(row: Any) -> dict[str, object]:
    return {
        "reference": str(row["reference"]),
        "subject": str(row["subject"]),
        "status": str(row["status"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


def _admin_summary(row: Any, admin_id: str) -> dict[str, object]:
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


def _conversation_page(
    db: Session,
    *,
    statement: Any,
    cursor: str | None,
    limit: int,
    secret: str,
    kind: str,
) -> tuple[list[Any], str | None]:
    if cursor:
        updated_at, reference = _decode_conversation_cursor(secret, kind, cursor)
        statement = statement.where(
            or_(
                support_conversations.c.updated_at < updated_at,
                and_(
                    support_conversations.c.updated_at == updated_at,
                    support_conversations.c.reference < reference,
                ),
            )
        )
    raw = (
        db.execute(
            statement.order_by(
                support_conversations.c.updated_at.desc(),
                support_conversations.c.reference.desc(),
            ).limit(limit + 1)
        )
        .mappings()
        .all()
    )
    has_more = len(raw) > limit
    rows = raw[:limit]
    next_cursor = None
    if has_more and rows:
        tail = rows[-1]
        next_cursor = _encode_cursor(
            secret,
            kind,
            {"u": tail["updated_at"].isoformat(), "r": str(tail["reference"])},
        )
    return rows, next_cursor


def _message_page(
    db: Session,
    *,
    conversation_id: str,
    visibility: str,
    cursor: str | None,
    limit: int,
    secret: str,
    kind: str,
    message_type: str | None = None,
) -> tuple[list[dict[str, object]], str | None]:
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
    if cursor:
        sequence = _decode_message_cursor(secret, kind, cursor)
        statement = statement.where(support_messages.c.sequence < sequence)
    raw = (
        db.execute(statement.order_by(support_messages.c.sequence.desc()).limit(limit + 1))
        .mappings()
        .all()
    )
    has_more = len(raw) > limit
    selected = raw[:limit]
    next_cursor = None
    if has_more and selected:
        next_cursor = _encode_cursor(secret, kind, {"s": int(selected[-1]["sequence"])})
    items = [
        {
            "sequence": int(message["sequence"]),
            "sender_type": str(message["sender_type"]),
            "message_type": str(message["message_type"]),
            "visibility": str(message["visibility"]),
            "body": str(message["body"]),
            "created_at": message["created_at"].isoformat(),
        }
        for message in reversed(selected)
    ]
    return items, next_cursor


@telegram_router.get("/support/paged/tickets")
def telegram_ticket_page(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 10,
    cursor: str | None = None,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 20)
    customer_id = _customer_id(db, x_telegram_subject)
    rows, next_cursor = _conversation_page(
        db,
        statement=select(support_conversations).where(
            support_conversations.c.requester_type == "CUSTOMER",
            support_conversations.c.requester_user_id == customer_id,
        ),
        cursor=cursor,
        limit=bounded_limit,
        secret=_customer_secret(settings),
        kind="telegram-support-tickets",
    )
    _no_store(response)
    return {"items": [_customer_summary(row) for row in rows], "next_cursor": next_cursor}


@telegram_router.get("/support/paged/tickets/{reference}")
def telegram_ticket_detail_page(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 8,
    cursor: str | None = None,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 20)
    customer_id = _customer_id(db, x_telegram_subject)
    row = _customer_conversation(db, customer_id, reference)
    messages, next_cursor = _message_page(
        db,
        conversation_id=str(row["id"]),
        visibility="PUBLIC",
        cursor=cursor,
        limit=bounded_limit,
        secret=_customer_secret(settings),
        kind=f"telegram-support-messages:{reference}",
    )
    _no_store(response)
    return {**_customer_summary(row), "messages": messages, "messages_next_cursor": next_cursor}


@admin_router.get("/conversations-page")
def admin_conversation_page(
    response: Response,
    admin: Annotated[AdminModel, Depends(require_perm("support.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    status_filter: SupportStatus | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 100)
    statement = select(support_conversations)
    if status_filter is not None:
        statement = statement.where(support_conversations.c.status == status_filter.value)
    kind = f"admin-support-tickets:{status_filter.value if status_filter else 'ALL'}"
    rows, next_cursor = _conversation_page(
        db,
        statement=statement,
        cursor=cursor,
        limit=bounded_limit,
        secret=_admin_secret(settings),
        kind=kind,
    )
    _no_store(response)
    return {"items": [_admin_summary(row, admin.id) for row in rows], "next_cursor": next_cursor}


@admin_router.get("/conversations/{reference}/paged")
def admin_conversation_detail_page(
    reference: str,
    response: Response,
    admin: Annotated[AdminModel, Depends(require_perm("support.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 100)
    row = _admin_conversation(db, reference)
    messages, next_cursor = _message_page(
        db,
        conversation_id=str(row["id"]),
        visibility="PUBLIC",
        cursor=cursor,
        limit=bounded_limit,
        secret=_admin_secret(settings),
        kind=f"admin-support-public:{reference}",
    )
    _no_store(response)
    return {
        **_admin_summary(row, admin.id),
        "messages": messages,
        "messages_next_cursor": next_cursor,
    }


@admin_router.get("/conversations/{reference}/internal-notes-page")
def admin_internal_notes_page(
    reference: str,
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.internal_notes.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, object]:
    bounded_limit = min(max(limit, 1), 100)
    row = _admin_conversation(db, reference)
    notes, next_cursor = _message_page(
        db,
        conversation_id=str(row["id"]),
        visibility="AGENT_ONLY",
        cursor=cursor,
        limit=bounded_limit,
        secret=_admin_secret(settings),
        kind=f"admin-support-notes:{reference}",
        message_type="INTERNAL_NOTE",
    )
    _no_store(response)
    return {"items": notes, "next_cursor": next_cursor}
