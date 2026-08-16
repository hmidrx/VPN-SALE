# pyright: reportPrivateUsage=false
"""Private Telegram delivery bridge for explicit, sensitive customer actions.

This router shares the existing service-authenticated Telegram boundary and is never public-routed.
Plain subscription credentials exist only in the response to an explicit issue/rotate request.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Never
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.delivery import DeliveryError, DeliveryErrorCode, render_plain_links

from .config import Settings, get_settings
from .delivery_subscriptions import (
    active_revision_connection,
    issue_service_subscription,
    revoke_service_subscription,
    rotate_service_subscription,
)
from .service_models import ServiceModel
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-delivery"],
    include_in_schema=False,
)


def _owned_service(db: Session, customer_id: str, service_reference: str) -> ServiceModel:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if service is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service_not_found")
    return service


def _raise_delivery_error(exc: DeliveryError) -> Never:
    if exc.code is DeliveryErrorCode.SUBSCRIPTION_NOT_FOUND:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {
        DeliveryErrorCode.SERVICE_UNAVAILABLE,
        DeliveryErrorCode.CONCURRENT_MODIFICATION,
    }:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = status.HTTP_409_CONFLICT
    raise HTTPException(status_code=code, detail="delivery_unavailable") from exc


def _subscription_origin(settings: Settings) -> str:
    raw = settings.subscription_public_origin.rstrip("/")
    parsed = urlsplit(raw)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid subscription public origin")
    if settings.environment.casefold() in {"production", "prod", "staging"} and parsed.scheme != "https":
        raise ValueError("subscription public origin must use HTTPS")
    return raw


def subscription_urls(settings: Settings, token: str) -> dict[str, str]:
    """Build absolute URLs only while a newly issued plaintext token is in memory."""
    origin = _subscription_origin(settings)
    base = f"{origin}/subscriptions/{token}"
    return {
        "base64": base,
        "links": f"{base}/links",
        "mihomo": f"{base}/mihomo",
        "clash": f"{base}/clash",
        "sing_box": f"{base}/sing-box",
    }


def _mutation_response(
    response: Response,
    *,
    status_value: str,
    token: str | None,
    settings: Settings,
) -> dict[str, object]:
    _no_store(response)
    return {
        "status": status_value,
        "newly_issued": token is not None,
        "urls": subscription_urls(settings, token) if token is not None else {},
    }


@router.post("/services/{service_reference}/subscription/issue")
def issue_subscription(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Depends()],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    # The header dependency is injected below explicitly by FastAPI through the alias helper.
    del x_telegram_subject
    raise AssertionError("header dependency replacement missing")
