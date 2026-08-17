# pyright: reportPrivateUsage=false
from __future__ import annotations

import urllib.error
from hashlib import sha256
from io import BytesIO

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivatePlatformClient
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingUser
from telegram_bot.runtime.service_management import ServiceManagementBotCommandHandler
from telegram_bot.service_management_api import (
    ServiceOperationPaymentResult,
    ServiceOperationQuote,
)


class _RejectingPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.quote_code: str | None = None
        self.payment_code: str | None = None

    def service_operation_quote(
        self,
        context: CustomerContext,
        service_reference: str,
        operation_type: str,
        amount: int,
        idempotency_key: str,
    ) -> ServiceOperationQuote:
        del context, service_reference, operation_type, amount, idempotency_key
        raise AuthoritativePrivateApiError(409, self.quote_code)

    def service_operation_pay(
        self,
        context: CustomerContext,
        operation_reference: str,
        idempotency_key: str,
    ) -> ServiceOperationPaymentResult:
        del context, operation_reference, idempotency_key
        raise AuthoritativePrivateApiError(409, self.payment_code)


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"safe-rejection-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"safe-rejection-rate-limit").hexdigest(),
    )


def _handler(portal: _RejectingPortal) -> ServiceManagementBotCommandHandler:
    return ServiceManagementBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal
    )


def _callback(action: CallbackAction, value: str, update_id: int) -> IncomingCallback:
    user = IncomingUser(42, username="customer", first_name="Customer")
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        user,
        BotCallback(action, value).pack(),
    )


def _http_error(body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://internal.example.test",
        409,
        "Conflict",
        None,
        BytesIO(body),
    )


def test_private_api_preserves_only_bounded_machine_safe_detail() -> None:
    assert (
        PrivatePlatformClient._safe_http_rejection_code(
            _http_error(b'{"detail":"service_operation_in_progress"}')
        )
        == "service_operation_in_progress"
    )
    assert (
        PrivatePlatformClient._safe_http_rejection_code(
            _http_error(b'{"detail":"SERVICE_OPERATION_IN_PROGRESS"}')
        )
        is None
    )
    assert (
        PrivatePlatformClient._safe_http_rejection_code(
            _http_error(b'{"detail":"secret:do-not-expose"}')
        )
        is None
    )
    assert (
        PrivatePlatformClient._safe_http_rejection_code(
            _http_error(b'{"detail":{"code":"service_operation_in_progress"}}')
        )
        is None
    )
    assert PrivatePlatformClient._safe_http_rejection_code(_http_error(b"not-json")) is None
    assert (
        PrivatePlatformClient._safe_http_rejection_code(
            _http_error(b'{"detail":"' + (b"a" * 5000) + b'"}')
        )
        is None
    )


def test_authoritative_error_keeps_status_and_safe_code_without_raw_body() -> None:
    error = AuthoritativePrivateApiError(409, "service_operation_review_required")

    assert error.status_code == 409
    assert error.safe_code == "service_operation_review_required"
    assert "service_operation_review_required" not in str(error)


def test_quote_race_blocker_routes_back_to_service_without_payment_action() -> None:
    portal = _RejectingPortal()
    portal.quote_code = "service_operation_in_progress"

    result = _handler(portal).handle_callback(
        _callback(CallbackAction.RENEW_QUOTE, "svc_opaque,30", 30)
    )

    text = result.messages[0].text
    rows = str(result.messages[0].rows)
    assert "هم‌زمان یک عملیات دیگر" in text
    assert "دوباره پرداخت نکنید" in text
    assert "بررسی دوباره سرویس" in rows
    assert "پرداخت از کیف پول" not in rows
    assert "service_operation_in_progress" not in text


def test_payment_race_review_blocker_routes_to_support_and_services() -> None:
    portal = _RejectingPortal()
    portal.payment_code = "service_operation_review_required"

    result = _handler(portal).handle_callback(
        _callback(
            CallbackAction.SERVICE_OPERATION_PAY,
            "cccccccc-cccc-4ccc-8ccc-ccccccccccc1",
            31,
        )
    )

    message = result.messages[0]
    text = message.text
    rows = str(message.rows)
    callbacks = [button.get("callback_data") for row in message.rows for button in row]
    assert "نیازمند بررسی" in text
    assert "دوباره پرداخت نکنید" in text
    assert "پشتیبانی" in rows
    assert BotCallback(CallbackAction.MY_SERVICES).pack() in callbacks
    assert "پرداخت از کیف پول" not in rows
    assert "service_operation_review_required" not in text


def test_unrecognized_authoritative_code_keeps_existing_generic_customer_copy() -> None:
    portal = _RejectingPortal()
    portal.payment_code = "service_changed_since_quote"

    result = _handler(portal).handle_callback(
        _callback(
            CallbackAction.SERVICE_OPERATION_PAY,
            "cccccccc-cccc-4ccc-8ccc-ccccccccccc1",
            32,
        )
    )

    assert "قیمت یا وضعیت سرویس دیگر برای پرداخت معتبر نیست" in result.messages[0].text
    assert "service_changed_since_quote" not in result.messages[0].text
