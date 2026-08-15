from __future__ import annotations

from typing import Any, cast

from telegram_bot.internal_api import PrivatePlatformClient
from telegram_bot.portal import CustomerContext


class DeliveryPrivatePlatformClient(PrivatePlatformClient):
    """Production private platform client with explicit sensitive delivery access."""

    def service_delivery_links(
        self, context: CustomerContext, service_ref: str
    ) -> tuple[str, ...]:
        data = self._request(  # noqa: SLF001 - intentional private adapter extension
            "GET", f"/services/{service_ref}/delivery", context.telegram_user_id
        )
        if data.get("delivery_ready") is not True:
            return ()
        links_value: object = data.get("links")
        if not isinstance(links_value, list):
            return ()
        links: list[str] = []
        for value in cast(list[Any], links_value):
            if not isinstance(value, str):
                return ()
            links.append(value)
        return tuple(links)
