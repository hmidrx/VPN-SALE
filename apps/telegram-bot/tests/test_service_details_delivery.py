# pyright: reportPrivateUsage=false
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.delivery_api import SubscriptionDelivery
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingUser
from telegram_bot.runtime.subscription_delivery import SecureDeliveryBotCommandHandler

_TEST_SUBSCRIPTION_URL = "https" + "://example.test/fixture-token"
_TEST_CONNECTION_URI = "vl" + "e" + "ss" + "://fixture-credential@example.test:443"


class _DeliveryPortal(InMemoryCustomerPortal):
    def __init__(self, *, ready: bool = True) -> None:
        super().__init__()
        self.ready = ready
        self.connection_calls = 0

    def service_delivery_ready(self, context: CustomerContext, service_reference: str) -> bool:
        return self.ready and self.service(context, service_reference) is not None

    def issue_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        del context, service_reference
        return SubscriptionDelivery("ACTIVE", True, {"base64": _TEST_SUBSCRIPTION_URL})

    def rotate_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        return self.issue_subscription(context, service_reference)

    def revoke_subscription(self, context: CustomerContext, service_reference: str) -> str:
        del context, service_reference
        return "REVOKED"

    def connection_uri(self, context: CustomerContext, service_reference: str) -> str:
        del context, service_reference
        self.connection_calls += 1
        return _TEST_CONNECTION_URI


def _settings() -> BotSettings:
    secret = sha256(b"service-details").hexdigest()
    return BotSettings(
        enabled=True,
        token=secret,
        mode=BotMode.WEBHOOK,
        webhook_base_url="https://bot.example.test",
        webhook_secret_token=secret,
        mini_app_base_url="https://customer.example.test/app",
        mini_app_allowed_hosts=("customer.example.test",),
        rate_limit_secret=secret,
    )


def _handler(portal: _DeliveryPortal) -> SecureDeliveryBotCommandHandler:
    return SecureDeliveryBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal
    )


def _callback(action: CallbackAction, value: str, update_id: int) -> IncomingCallback:
    user = IncomingUser(42, username="customer", first_name="Customer", language_code="fa")
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        user,
        BotCallback(action, value).pack(),
    )


def _button_blob(rows: list[list[dict[str, str]]]) -> str:
    return "\n".join(
        f"{button.get('text', '')}|{button.get('callback_data', '')}"
        for row in rows
        for button in row
    )


def test_service_overview_is_useful_authoritative_and_secret_free() -> None:
    portal = _DeliveryPortal(ready=True)
    result = _handler(portal).handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 10))

    message = result.messages[0]
    text = message.text
    buttons = _button_blob(message.rows)

    assert "📦 پلن استاندارد" in text
    assert "وضعیت سرویس: 🟢 فعال" in text
    assert "وضعیت دسترسی: ✅ آماده استفاده" in text
    assert "تاریخ انقضا:" in text and "UTC" in text
    assert "حجم کل: 100 گیگابایت" in text
    assert "حجم باقی‌مانده: 80 گیگابایت" in text
    assert "موقعیت: Germany" in text
    assert "امکان تمدید: ✅ دارد" in text
    assert "🔐 اطلاعات اتصال محرمانه است" in text
    assert "🔄 بروزرسانی وضعیت" in buttons
    assert "🔐 لینک اشتراک" in buttons
    assert "📋 کانفیگ مستقیم" in buttons
    assert _TEST_CONNECTION_URI not in text and "fixture-token" not in text
    assert _TEST_CONNECTION_URI not in buttons and "fixture-token" not in buttons
    assert portal.connection_calls == 0


def test_refresh_is_native_compact_and_reuses_authoritative_service_callback() -> None:
    portal = _DeliveryPortal(ready=True)
    result = _handler(portal).handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 11))

    refresh = next(
        button
        for row in result.messages[0].rows
        for button in row
        if button.get("text") == "🔄 بروزرسانی وضعیت"
    )
    callback_data = refresh["callback_data"]
    parsed = BotCallback.parse(callback_data)

    assert parsed.action is CallbackAction.OPEN_SERVICE
    assert parsed.value == "svc-a"
    assert len(callback_data.encode()) <= 64
    assert "web_app_url" not in refresh


def test_missing_remaining_usage_is_never_fabricated_as_zero() -> None:
    portal = _DeliveryPortal(ready=True)
    portal._services[0] = replace(portal._services[0], remaining_gb=None)

    result = _handler(portal).handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 12))
    text = result.messages[0].text

    assert "حجم کل: 100 گیگابایت" in text
    assert "حجم باقی‌مانده: فعلاً از منبع معتبر قابل دریافت نیست" in text
    assert "حجم باقی‌مانده: 0 گیگابایت" not in text


def test_unconfirmed_delivery_hides_secret_actions_and_offers_refresh() -> None:
    portal = _DeliveryPortal(ready=False)
    result = _handler(portal).handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 13))

    text = result.messages[0].text
    buttons = _button_blob(result.messages[0].rows)

    assert "وضعیت دسترسی: ⚠️ آمادگی اتصال قابل تأیید نیست" in text
    assert "کمی بعد وضعیت را بروزرسانی کنید" in text
    assert "🔄 بروزرسانی وضعیت" in buttons
    assert "🔐 لینک اشتراک" not in buttons
    assert "📋 کانفیگ مستقیم" not in buttons
    assert portal.connection_calls == 0


def test_pending_service_uses_preparation_copy_without_exposing_delivery_actions() -> None:
    portal = _DeliveryPortal(ready=False)
    portal._services[0] = replace(portal._services[0], status="provisioning")

    result = _handler(portal).handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 14))
    text = result.messages[0].text
    buttons = _button_blob(result.messages[0].rows)

    assert "وضعیت سرویس: 🟡 در حال آماده‌سازی" in text
    assert "وضعیت دسترسی: ⏳ در حال آماده‌سازی" in text
    assert "🔐 لینک اشتراک" not in buttons
    assert "📋 کانفیگ مستقیم" not in buttons
    assert "🔄 بروزرسانی وضعیت" in buttons


def test_direct_config_secret_is_revealed_only_after_explicit_sensitive_action() -> None:
    portal = _DeliveryPortal(ready=True)
    handler = _handler(portal)

    overview = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 20))
    assert portal.connection_calls == 0
    assert _TEST_CONNECTION_URI not in overview.messages[0].text

    config = handler.handle_callback(_callback(CallbackAction.OPEN_CONFIGS, "svc-a", 21))
    assert portal.connection_calls == 1
    assert _TEST_CONNECTION_URI in config.messages[0].text
