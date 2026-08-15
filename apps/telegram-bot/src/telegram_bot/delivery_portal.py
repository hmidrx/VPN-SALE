from __future__ import annotations

from typing import Protocol, runtime_checkable

from telegram_bot.portal import CustomerContext


@runtime_checkable
class SensitiveDeliveryPortalPort(Protocol):
    """Narrow opt-in surface for customer-owned VPN credentials."""

    def service_delivery_links(
        self, context: CustomerContext, service_ref: str
    ) -> tuple[str, ...]: ...
