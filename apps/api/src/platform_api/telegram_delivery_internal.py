# pyright: reportPrivateUsage=false
"""Sensitive service delivery over the already-private Telegram bridge."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Response

from .delivery import customer_delivery_links
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store

router = APIRouter(
    prefix="/api/v1/internal/telegram", tags=["internal-telegram"], include_in_schema=False
)


@router.get("/services/{service_reference}/delivery")
def telegram_service_delivery(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    service, links = customer_delivery_links(db, customer_id, service_reference)
    _no_store(response)
    return {
        "service_reference": service.public_reference,
        "delivery_ready": True,
        "links": list(links),
    }
