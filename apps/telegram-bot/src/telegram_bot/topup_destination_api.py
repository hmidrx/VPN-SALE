"""Telegram-native manual top-up destination adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from telegram_bot.portal import CustomerContext
from telegram_bot.purchase_api import NativePurchasePrivatePlatformClient


@dataclass(frozen=True)
class ManualTopupDestination:
    mode: str
    support_required: bool
    formatted_card_number: str | None = None
    card_holder_name: str | None = None


class NativeTopupDestinationPortal(Protocol):
    def manual_topup_destination(
        self, context: CustomerContext, reference: str
    ) -> ManualTopupDestination: ...


class NativeTopupPrivatePlatformClient(
    NativePurchasePrivatePlatformClient, NativeTopupDestinationPortal
):
    def manual_topup_destination(
        self, context: CustomerContext, reference: str
    ) -> ManualTopupDestination:
        data = self._request(
            "GET",
            f"/manual-topups/{reference}/destination",
            context.telegram_user_id,
        )
        mode = data.get("mode")
        support_required = data.get("support_required")
        card = data.get("formatted_card_number")
        holder = data.get("card_holder_name")
        if mode not in {"DIRECT_CARD", "SUPPORT_ONLY"} or not isinstance(
            support_required, bool
        ):
            raise ValueError("invalid manual top-up destination response")
        if card is not None and not isinstance(card, str):
            raise ValueError("invalid manual top-up destination response")
        if holder is not None and not isinstance(holder, str):
            raise ValueError("invalid manual top-up destination response")
        if mode == "DIRECT_CARD" and (support_required or not card):
            raise ValueError("invalid manual top-up destination response")
        if mode == "SUPPORT_ONLY" and not support_required:
            raise ValueError("invalid manual top-up destination response")
        return ManualTopupDestination(mode, support_required, card, holder)
