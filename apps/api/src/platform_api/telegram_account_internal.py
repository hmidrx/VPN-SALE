"""Private Telegram account-security bridge.

The bot authenticates with the existing service credential and ownership is derived only
from the Telegram subject. Raw customer-session database identifiers are never returned.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select

from .config import Settings, get_settings
from .identity.models import CustomerSessionModel, TelegramAccountModel, UserModel
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-account-security"],
    include_in_schema=False,
)


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


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _reference_key(settings: Settings) -> bytes:
    try:
        key = Path(settings.telegram_internal_token_file).read_bytes().strip()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account_security_unavailable",
        ) from exc
    if len(key) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="account_security_unavailable",
        )
    return key


def session_reference(settings: Settings, session_id: str) -> str:
    digest = hmac.new(
        _reference_key(settings),
        f"customer-session:{session_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"ses_{digest[:24]}"


def _active(row: CustomerSessionModel, now: datetime) -> bool:
    return (
        row.revoked_at is None
        and row.consumed_at is None
        and _aware(row.idle_expires_at) > now
        and _aware(row.absolute_expires_at) > now
    )


def _owned_sessions(db: Database, customer_id: str) -> list[CustomerSessionModel]:
    # The SQL predicate is the primary ownership boundary. The Python ownership check is
    # intentionally repeated so a future query refactor cannot accidentally expose another user.
    rows = db.scalars(
        select(CustomerSessionModel)
        .where(CustomerSessionModel.user_id == customer_id)
        .order_by(CustomerSessionModel.created_at.desc())
        .limit(100)
    ).all()
    return [row for row in rows if row.user_id == customer_id]


def _resolve_owned_reference(
    rows: list[CustomerSessionModel], settings: Settings, reference: str
) -> CustomerSessionModel | None:
    if len(reference) != 28 or not reference.startswith("ses_"):
        return None
    matches = [
        row for row in rows if hmac.compare_digest(session_reference(settings, row.id), reference)
    ]
    return matches[0] if len(matches) == 1 else None


@router.get("/sessions")
def list_sessions(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    now = datetime.now(UTC)
    items: list[dict[str, object]] = []
    for row in _owned_sessions(db, customer_id):
        if not _active(row, now):
            continue
        label = (row.device_label or "نشست وب").strip()[:80] or "نشست وب"
        last_seen = row.last_used_at or row.created_at
        items.append(
            {
                "reference": session_reference(settings, row.id),
                "label": label,
                "last_seen_at": _aware(last_seen).isoformat(),
                "created_at": _aware(row.created_at).isoformat(),
                "expires_at": min(
                    _aware(row.idle_expires_at), _aware(row.absolute_expires_at)
                ).isoformat(),
                # The Telegram bot itself does not use a customer web session.
                "current": False,
            }
        )
    _no_store(response)
    return {"items": items}


@router.post("/sessions/{reference}/revoke")
def revoke_session(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    customer_id = _customer_id(db, x_telegram_subject)
    target = _resolve_owned_reference(_owned_sessions(db, customer_id), settings, reference)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if target.revoked_at is None:
        target.revoked_at = datetime.now(UTC)
        target.revocation_reason = "telegram_customer_revoked"
        db.commit()
    _no_store(response)
    return {"status": "REVOKED"}
