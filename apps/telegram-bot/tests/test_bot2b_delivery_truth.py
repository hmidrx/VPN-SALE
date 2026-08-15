from __future__ import annotations

from telegram_bot.delivery_portal import SensitiveDeliveryPortalPort
from telegram_bot.portal import CustomerContext
from telegram_bot.runtime.purchase_truth import _delivery_text


class DeliveryPortal:
    def service_delivery_links(
        self, context: CustomerContext, service_ref: str
    ) -> tuple[str, ...]:
        _ = context, service_ref
        return ("vless://safe",)


def test_sensitive_delivery_port_is_explicit_and_runtime_checkable() -> None:
    assert isinstance(DeliveryPortal(), SensitiveDeliveryPortalPort)


def test_delivery_text_never_overflows_bounded_message_budget() -> None:
    links = tuple(f"vless://{'a' * 700}{index}" for index in range(8))
    rendered = _delivery_text(links)
    assert len(rendered.encode()) <= 3700
    assert "کانفیگ سرویس" in rendered


def test_empty_delivery_does_not_claim_credentials_are_ready() -> None:
    assert _delivery_text(()) == "کانفیگ هنوز آماده نمایش نیست."
