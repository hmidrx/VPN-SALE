from __future__ import annotations

from hashlib import sha256

import pytest

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal, NotificationPreferences
from telegram_bot.runtime.handlers import BotCommandHandler, IncomingCallback, IncomingUser
from telegram_bot.screens import ScreenId


def settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"notification-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"rate").hexdigest(),
    )


def user(uid: int = 42) -> IncomingUser:
    return IncomingUser(uid, first_name="کاربر", language_code="fa")


def incoming(data: str, update_id: int = 100, uid: int = 42) -> IncomingCallback:
    return IncomingCallback(update_id, f"cb-{update_id}", "private", user(uid), data)


def open_settings(handler: BotCommandHandler) -> object:
    return handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.SETTINGS.value).pack(), 10)
    )


def test_settings_notifications_button_navigates_and_does_not_retry() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    result = open_settings(handler)
    button = next(b for row in result.messages[0].rows for b in row if b["text"] == "🔔 اعلان‌ها")
    parsed = BotCallback.parse(button["callback_data"])
    assert parsed.action is CallbackAction.NAVIGATE
    assert parsed.value == ScreenId.NOTIFICATIONS.value
    assert parsed.action is not CallbackAction.RETRY

    clicked = handler.handle_callback(incoming(button["callback_data"], 11))
    assert clicked.acknowledged
    assert "🔔 تنظیمات اعلان‌ها" in clicked.messages[0].text
    assert "⚙️ تنظیمات" not in clicked.messages[0].text


def test_notifications_screen_is_persian_and_lists_all_preferences() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    result = handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value).pack())
    )
    text = result.messages[0].text
    for label in [
        "پایان اعتبار سرویس",
        "کمبود حجم",
        "پرداخت‌ها و تراکنش‌ها",
        "پاسخ پشتیبانی",
        "اطلاعیه‌های مهم",
    ]:
        assert label in text
    assert "enabled" not in text
    assert "service_expiry" not in text
    assert all(
        len(b["callback_data"].encode()) <= 64 for row in result.messages[0].rows for b in row
    )


@pytest.mark.parametrize(
    "key",
    [
        "service_expiry_enabled",
        "low_traffic_enabled",
        "payment_enabled",
        "support_reply_enabled",
        "announcements_enabled",
    ],
)
def test_toggle_each_preference_persists_once_and_duplicate_is_idempotent(key: str) -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    data = BotCallback(CallbackAction.TOGGLE_NOTIFICATION, key).pack()
    first = handler.handle_callback(incoming(data, 200))
    duplicate = handler.handle_callback(incoming(data, 200))
    assert first.acknowledged and duplicate.acknowledged
    prefs = portal.notification_preferences(CustomerContext("user-42", 42, "fa"))
    assert getattr(prefs, key) is False

    restarted = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    rendered = restarted.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value).pack(), 201)
    )
    assert "❌" in rendered.messages[0].text


def test_api_failure_and_mutation_failure_are_customer_safe() -> None:
    class FailingPortal(InMemoryCustomerPortal):
        def notification_preferences(self, context: CustomerContext) -> NotificationPreferences:
            raise RuntimeError("database url secret should not leak")

    handler = BotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=FailingPortal()
    )
    result = handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value).pack(), 300)
    )
    assert "⚠️ در دریافت تنظیمات اعلان‌ها مشکلی پیش آمد." in result.messages[0].text
    assert "database" not in result.messages[0].text.lower()

    class MutationFailPortal(InMemoryCustomerPortal):
        def update_notification_preference(self, context, key, enabled, idempotency_key):  # type: ignore[no-untyped-def]
            raise RuntimeError("api failure")

    handler = BotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=MutationFailPortal()
    )
    result = handler.handle_callback(
        incoming(BotCallback(CallbackAction.TOGGLE_NOTIFICATION, "payment_enabled").pack(), 301)
    )
    assert "⚠️ تغییر تنظیمات ذخیره نشد." in result.messages[0].text
    assert "✅ پرداخت‌ها" in "\n".join(b["text"] for r in result.messages[0].rows for b in r)


def test_back_home_and_refresh_navigation_for_notifications() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.SETTINGS.value).pack(), 401)
    )
    handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value).pack(), 402)
    )
    back = handler.handle_callback(incoming(BotCallback(CallbackAction.BACK).pack(), 403))
    assert "⚙️ تنظیمات" in back.messages[0].text
    home = handler.handle_callback(incoming(BotCallback(CallbackAction.HOME).pack(), 404))
    assert "💳 موجودی:" in home.messages[0].text
    portal.update_notification_preference(
        CustomerContext("user-42", 42, "fa"), "payment_enabled", False, "external"
    )
    handler.handle_callback(
        incoming(BotCallback(CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value).pack(), 405)
    )
    refresh = handler.handle_callback(incoming(BotCallback(CallbackAction.REFRESH).pack(), 406))
    assert "❌ پرداخت‌ها و تراکنش‌ها" in refresh.messages[0].text


def test_customer_preferences_are_isolated_between_customers() -> None:
    portal = InMemoryCustomerPortal()
    portal.update_notification_preference(
        CustomerContext("user-a", 100, "fa"), "payment_enabled", False, "idem-a"
    )

    prefs_a = portal.notification_preferences(CustomerContext("user-a", 100, "fa"))
    prefs_b = portal.notification_preferences(CustomerContext("user-b", 200, "fa"))

    assert prefs_a.payment_enabled is False
    assert prefs_b.payment_enabled is True
