"""Private, service-authenticated Telegram bridge (never routed by Caddy)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db_session
from .identity.models import CustomerProfileModel, TelegramAccountModel, UserModel

router = APIRouter(prefix="/api/v1/internal/telegram", tags=["internal-telegram"])


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_user_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=32)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    language_code: str | None = Field(default=None, max_length=16)
    bot_started: bool = True


def _authenticate(
    authorization: Annotated[str | None, Header()] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> None:
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    try:
        expected = Path(settings.telegram_internal_token_file).read_text().strip()
    except OSError:
        expected = ""
    if len(expected) < 32 or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthenticated")


InternalAuth = Annotated[None, Depends(_authenticate)]
Database = Annotated[Session, Depends(get_db_session)]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def _account(db: Session, telegram_id: int) -> tuple[TelegramAccountModel, UserModel]:
    row = db.execute(
        select(TelegramAccountModel, UserModel)
        .join(UserModel, TelegramAccountModel.user_id == UserModel.id)
        .where(TelegramAccountModel.telegram_user_id == telegram_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="account_unlinked")
    return row[0], row[1]


@router.post("/identity/resolve")
def resolve(
    body: ResolveRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> dict[str, object]:
    account, user = _account(db, body.telegram_user_id)
    account.username, account.first_name, account.last_name = (
        body.username,
        body.first_name,
        body.last_name,
    )
    account.language_code, account.bot_started, account.blocked_bot = (
        body.language_code,
        True,
        False,
    )
    account.last_seen_at = datetime.now(UTC)
    db.commit()
    _no_store(response)
    opaque = hmac.new(
        Path(settings.telegram_internal_token_file).read_bytes(), user.id.encode(), hashlib.sha256
    ).hexdigest()[:24]
    return {
        "customer_reference": opaque,
        "account_state": user.status,
        "created": False,
        "locale": body.language_code or "fa",
    }


@router.get("/profile")
def profile(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    account, user = _account(db, x_telegram_subject)
    profile_row = db.get(CustomerProfileModel, user.id)
    _no_store(response)
    display = (
        profile_row.display_name
        if profile_row and profile_row.display_name
        else account.first_name or "مشتری"
    )
    return {
        "display_name": display,
        "telegram_linked": True,
        "account_state": user.status,
        "created_at": user.created_at.isoformat(),
        "locale": profile_row.locale if profile_row and profile_row.locale else "fa",
        "username": account.username,
    }


@router.post("/identity/blocked", status_code=204)
def blocked(
    _: InternalAuth, db: Database, x_telegram_subject: Annotated[int, Header(gt=0)]
) -> None:
    account, _user = _account(db, x_telegram_subject)
    account.blocked_bot = True
    db.commit()


# These collection routes intentionally return only customer-safe DTO shapes. Domain-backed
# expansion is performed in the respective service modules; no database identifier is exposed.
@router.get("/services")
def services(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _account(db, x_telegram_subject)
    _no_store(response)
    return {"items": []}


@router.get("/wallet")
def wallet(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _account(db, x_telegram_subject)
    _no_store(response)
    return {"balance_minor": 0, "currency": "IRR"}


@router.get("/wallet/transactions")
def transactions(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    _account(db, x_telegram_subject)
    _no_store(response)
    return {"items": []}
