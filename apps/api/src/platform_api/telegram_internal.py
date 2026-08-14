"""Private, service-authenticated Telegram bridge (never routed by Caddy)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .database import get_db_session
from .identity.models import CustomerProfileModel, TelegramAccountModel, UserModel
from .notification_preferences import (
    NotificationPreferencePatch,
    NotificationPreferencesOut,
    get_preferences,
    patch_preferences,
)
from .services import (
    CustomerServiceSummary,
    customer_service_projection,
    customer_service_summaries,
)
from .wallet import customer_transaction_page, customer_wallet_projection

router = APIRouter(
    prefix="/api/v1/internal/telegram", tags=["internal-telegram"], include_in_schema=False
)


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


@router.get("/dashboard")
def dashboard(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    telegram, user = _account(db, x_telegram_subject)
    customer_id = _customer_id(db, x_telegram_subject)
    profile_row = db.get(CustomerProfileModel, customer_id)
    service_items = customer_service_summaries(db, customer_id, 100)
    active = [item for item in service_items if item.lifecycle == "ACTIVE"]
    nearest = min((item.expires_at for item in active if item.expires_at is not None), default=None)
    try:
        wallet_data = customer_wallet_projection(db, customer_id)
        balance_rial = int(wallet_data["available_balance_rial"])
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="dashboard_unavailable") from exc
    if balance_rial % 10:
        raise HTTPException(status_code=503, detail="wallet_precision_unavailable")
    _no_store(response)
    return {
        "display_name": (profile_row.display_name if profile_row else None)
        or telegram.first_name
        or "مشتری",
        "account_state": user.status,
        "balance_toman": balance_rial // 10,
        "active_service_count": len(active),
        "nearest_expiry": nearest,
    }


@router.post(
    "/identity/blocked",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def blocked(
    _: InternalAuth, db: Database, x_telegram_subject: Annotated[int, Header(gt=0)]
) -> Response:
    account, _user = _account(db, x_telegram_subject)
    account.blocked_bot = True
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _customer_id(db: Session, telegram_id: int) -> str:
    _telegram, user = _account(db, telegram_id)
    if user.status not in {"ACTIVE", "PENDING"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="account_restricted")
    return user.id


def _service_item(summary: CustomerServiceSummary) -> dict[str, object]:
    data = summary.model_dump()
    entitlement = data["entitlement"]
    return {
        "reference": data["service_reference"],
        "plan_name": data["display_name"],
        "status": data["lifecycle"],
        "status_label": data["lifecycle_label"],
        "expires_at": data["expires_at"],
        "location": entitlement["location_label"],
        "traffic_entitlement_bytes": entitlement["traffic_quota_bytes"],
        "device_limit": entitlement["device_limit"],
        "delivery_ready": data["delivery_ready"],
        "usage": data["usage"],
        "renewable": data["lifecycle"] in {"ACTIVE", "EXPIRED"},
    }


@router.get("/services")
def services(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    _no_store(response)
    return {"items": [_service_item(item) for item in customer_service_summaries(db, customer_id)]}


@router.get("/services/{service_reference}")
def service_detail(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    detail = customer_service_projection(
        db, _customer_id(db, x_telegram_subject), service_reference
    )
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service_not_found")
    _no_store(response)
    item = _service_item(detail.summary)
    item["service_health"] = detail.service_health
    item["eligible_operations"] = detail.eligible_operations
    return item


@router.get("/wallet")
def wallet(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    _no_store(response)
    try:
        projection = customer_wallet_projection(db, customer_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="wallet_unavailable") from exc
    rial = int(projection["available_balance_rial"])
    if rial % 10:
        raise HTTPException(status_code=503, detail="wallet_precision_unavailable")
    return {"balance_minor": rial // 10, "currency": "TOMAN", "status": projection["status"]}


@router.get("/wallet/transactions")
def transactions(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 20,
    cursor: str | None = None,
) -> dict[str, object]:
    page = customer_transaction_page(
        db, _customer_id(db, x_telegram_subject), settings, limit=limit, cursor=cursor
    )
    _no_store(response)
    safe_items: list[dict[str, object]] = []
    token = Path(settings.telegram_internal_token_file).read_bytes()
    for item in page["items"]:
        amount_rial = item["amount_rial"]
        if amount_rial is None or int(amount_rial) % 10:
            continue
        safe_items.append(
            {
                "reference": hmac.new(
                    token, str(item["transaction_reference"]).encode(), hashlib.sha256
                ).hexdigest()[:20],
                "amount_minor": int(amount_rial) // 10,
                "currency": "TOMAN",
                "status": item["status"],
                "transaction_type": item["type"],
                "direction": item["direction"],
                "created_at": item["occurred_at"],
            }
        )
    return {"items": safe_items, "next_cursor": page["next_cursor"]}


@router.get("/notification-preferences")
def notification_preferences(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, bool]:
    _customer_id(db, x_telegram_subject)
    _no_store(response)
    return get_preferences(x_telegram_subject, db).model_dump()


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


@router.patch("/notification-preferences/{preference_key}")
def update_notification_preference(
    preference_key: str,
    body: PreferenceUpdate,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> dict[str, bool]:
    _customer_id(db, x_telegram_subject)
    if preference_key not in NotificationPreferencesOut.model_fields:
        raise HTTPException(status_code=400, detail="invalid_preference")
    _no_store(response)
    return patch_preferences(
        x_telegram_subject,
        NotificationPreferencePatch(key=preference_key, enabled=body.enabled),
        db,
        idempotency_key,
    ).model_dump()
