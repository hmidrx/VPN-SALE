from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingUser
from telegram_bot.runtime.service_management import ServiceManagementBotCommandHandler
from telegram_bot.service_management_api import (
    ServiceOperationEligibility,
    ServiceOperationQuote,
    ServiceOperationQuoteOptions,
)


class _ServiceManagementPortal(InMemoryCustomerPortal):
    eligible = True

    def __init__(self) -> None:
        super().__init__()
        self.quote_calls: list[tuple[str, str, int, str]] = []

    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]:
        del context, service_reference
        return (
            ServiceOperationEligibility(
                "RENEW",
                self.eligible,
                True,
                True,
                (),
                ServiceOperationQuoteOptions("DAY", 1, 365, 1, (7, 30, 90)),
            ),
            ServiceOperationEligibility(
                "ADD_TRAFFIC",
                self.eligible,
                True,
                True,
                (),
                ServiceOperationQuoteOptions("GIB", 5, 100, 5, (5, 10, 20, 50)),
            ),
        )

    def service_operation_quote(
        self,
        context: CustomerContext,
        service_reference: str,
        operation_type: str,
        amount: int,
        idempotency_key: str,
    ) -> ServiceOperationQuote:
        del context
        self.quote_calls.append((service_reference, operation_type, amount, idempotency_key))
        return ServiceOperationQuote(
            operation_reference="op_quote_1",
            service_id="service-id",
            operation_type=operation_type,
            status="AWAITING_PAYMENT",
            amount=amount,
            price_rial=amount * 10_000,
            currency="IRR",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
            policy_version_id="policy-version-id",
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


def _callback(action: CallbackAction, update_id: int, value: str = "svc_opaque") -> IncomingCallback:
    user = IncomingUser(42, username="customer", first_name="Customer")
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        user,
        BotCallback(action, value).pack(),
    )


def _handler(portal: _ServiceManagementPortal) -> ServiceManagementBotCommandHandler:
    return ServiceManagementBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal
    )


def test_renew_and_extra_traffic_render_policy_valid_quote_options() -> None:
    portal = _ServiceManagementPortal()
    handler = _handler(portal)

    renewal = handler.handle_callback(_callback(CallbackAction.RENEW, 10))
    extra = handler.handle_callback(_callback(CallbackAction.EXTRA_TRAFFIC, 11))

    assert "تمدید سرویس" in renewal.messages[0].text
    assert "قیمت‌گذاری مرکزی" in renewal.messages[0].text
    assert "30 روز" in str(renewal.messages[0].rows)
    assert "خرید حجم اضافه" in extra.messages[0].text
    assert "20 گیگابایت" in str(extra.messages[0].rows)
    assert "مینی‌اپ" not in renewal.messages[0].text
    assert "مینی‌اپ" not in extra.messages[0].text


def test_selecting_amount_requests_and_renders_authoritative_quote() -> None:
    portal = _ServiceManagementPortal()
    result = _handler(portal).handle_callback(
        _callback(CallbackAction.RENEW_QUOTE, 12, "svc_opaque,30")
    )

    assert "قیمت تمدید سرویس" in result.messages[0].text
    assert "30 روز" in result.messages[0].text
    assert "300,000 ریال" in result.messages[0].text
    assert portal.quote_calls == [
        ("svc_opaque", "RENEW", 30, "svcq:42:12:RENEW:30")
    ]


def test_ineligible_service_is_rejected_without_financial_mutation() -> None:
    portal = _ServiceManagementPortal()
    portal.eligible = False
    result = _handler(portal).handle_callback(_callback(CallbackAction.RENEW, 20))

    assert "قابل انجام نیست" in result.messages[0].text
    assert "پرداخت" not in result.messages[0].text
    assert portal.quote_calls == []
