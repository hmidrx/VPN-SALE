# pyright: reportPrivateUsage=false
"""Private Telegram access to the customer-safe manual top-up destination snapshot."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from vpnsale_domain.manual_topups import format_card_number

from .config import Settings, get_settings
from .identity.security import EncryptedSecret
from .manual_topup_models import ManualTopupDestinationVersionModel
from .manual_topups import (
    _encryptor,
    customer_manual_topup_destination_settings,
    customer_manual_topup_request,
)
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store

router = APIRouter(
    prefix="/api/v1/internal/telegram/manual-topups",
    tags=["internal-telegram"],
    include_in_schema=False,
)


@router.get("/{reference}/destination")
def manual_topup_destination(
    reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    request_row = customer_manual_topup_request(db, reference, customer_id)
    destination_settings = customer_manual_topup_destination_settings(db)
    _no_store(response)
    response.headers["Vary"] = "Authorization, X-Telegram-Subject"
    if not destination_settings.customer_display_enabled or not request_row.destination_version_id:
        return {"mode": "SUPPORT_ONLY", "support_required": True}

    destination = db.get(ManualTopupDestinationVersionModel, request_row.destination_version_id)
    if destination is None:
        return {"mode": "SUPPORT_ONLY", "support_required": True}

    encryptor = _encryptor(settings)
    card = encryptor.decrypt(
        EncryptedSecret(destination.encryption_key_version, destination.encrypted_card_number)
    )
    holder = (
        encryptor.decrypt(
            EncryptedSecret(
                destination.encryption_key_version,
                destination.encrypted_card_holder_name,
            )
        )
        if destination.encrypted_card_holder_name
        else None
    )
    return {
        "mode": "DIRECT_CARD",
        "formatted_card_number": format_card_number(card),
        "card_holder_name": holder,
        "support_required": False,
    }
