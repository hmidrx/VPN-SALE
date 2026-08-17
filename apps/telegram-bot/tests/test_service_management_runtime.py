from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingUser
from telegram_bot.runtime.service_management import ServiceManagementBotCommandHandler
from telegram_bot.service_management_api import ServiceOperationEligibility


class _ServiceManagementPortal(InMemoryCustomerPortal):
    eligible = True

    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]:
        del context, service_reference
        return (
            ServiceOperationEligibility("RENEW", self.eligible, True, True, ()),
            ServiceOperationEligibility("ADD_TRAFFIC", self.eligible, True, True, ()),
        )


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"service-management-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"service-management-rate-limit").hexdigest(),
    )


def _callback(action: CallbackAction, update_id: int) -> IncomingCallback:
    user = IncomingUser(42, username="customer", first_name="Customer")
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        user,
        BotCallback(action, "svc_opaque").pack(),
    )


def _handler(portal: _ServiceManagementPortal) -> ServiceManagementBotCommandHandler:
    return ServiceManagementBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal
    )


def test_renew_and_extra_traffic_no_longer_fall_back_to_mini_app() -> None:
    portal = _ServiceManagementPortal()
    handler = _handler(portal)

    renewal = handler.handle_callback(_callback(CallbackAction.RENEW, 10))
    extra = handler.handle_callback(_callback(CallbackAction.EXTRA_TRAFFIC, 11))

    assert "تمدید سرویس" in renewal.messages[0].text
    assert "سیستم قیمت‌گذاری" in renewal.messages[0].text
    assert "خرید حجم اضافه" in extra.messages[0].text
    assert "مینی‌اپ" not in renewal.messages[0].text
    assert "مینی‌اپ" not in extra.messages[0].text


def test_ineligible_service_is_rejected_without_financial_mutation() -> None:
    portal = _ServiceManagementPortal()
    portal.eligible = False
    result = _handler(portal).handle_callback(_callback(CallbackAction.RENEW, 20))

    assert "قابل انجام نیست" in result.messages[0].text
    assert "پرداخت" not in result.messages[0].text
