from __future__ import annotations

import threading
from dataclasses import replace
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    HandlerResult,
    IncomingCallback,
    IncomingUser,
)
from telegram_bot.screens import ScreenId


def settings(**changes: object) -> BotSettings:
    base = BotSettings(
        enabled=True,
        token=sha256(b"callback-policy-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"callback-policy-rate").hexdigest(),
    )
    return replace(base, **changes)


def callback(
    action: CallbackAction, update_id: int, *, uid: int = 42, value: str = ""
) -> IncomingCallback:
    return IncomingCallback(
        update_id,
        f"callback-{update_id}",
        "private",
        IncomingUser(uid, first_name="کاربر", language_code="fa"),
        BotCallback(action, value).pack(),
    )


def test_rapid_navigation_has_a_generous_independent_bucket() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    actions = [
        (CallbackAction.NAVIGATE, ScreenId.SETTINGS.value),
        (CallbackAction.NAVIGATE, ScreenId.NOTIFICATIONS.value),
        (CallbackAction.BACK, ""),
        (CallbackAction.HOME, ""),
        (CallbackAction.REFRESH, ""),
    ]
    results = [
        handler.handle_callback(callback(action, 100 + index, value=value))
        for index, (action, value) in enumerate(actions * 5)
    ]
    assert all(result.messages for result in results)
    assert all(result.callback_notice is None for result in results)
    assert all("بیش از حد مجاز" not in result.messages[0].text for result in results)


class CountingPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def update_notification_preference(
        self,
        context: CustomerContext,
        key: str,
        enabled: bool,
        idempotency_key: str,
    ):
        self.writes += 1
        return super().update_notification_preference(context, key, enabled, idempotency_key)


def test_repeated_toggle_accepts_one_write_and_one_persian_notice_per_cooldown() -> None:
    portal = CountingPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    results = [
        handler.handle_callback(
            callback(
                CallbackAction.TOGGLE_NOTIFICATION,
                200 + index,
                value="payment_enabled",
            )
        )
        for index in range(5)
    ]
    assert portal.writes == 1
    notices = [result.callback_notice for result in results if result.callback_notice]
    assert notices == ["لطفاً چند لحظه صبر کنید."]
    assert all(result.callback_alert for result in results if result.callback_notice)
    assert all(
        "درخواست‌ها بیش از حد مجاز است" not in message.text
        for result in results
        for message in result.messages
    )


def test_customer_rate_limit_buckets_are_independent() -> None:
    portal = CountingPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    first = handler.handle_callback(
        callback(CallbackAction.TOGGLE_NOTIFICATION, 300, uid=42, value="payment_enabled")
    )
    second = handler.handle_callback(
        callback(CallbackAction.TOGGLE_NOTIFICATION, 301, uid=84, value="payment_enabled")
    )
    assert first.messages and second.messages
    assert portal.writes == 2


def test_duplicate_update_id_never_repeats_mutation() -> None:
    portal = CountingPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    update = callback(CallbackAction.TOGGLE_NOTIFICATION, 400, value="announcements_enabled")
    first = handler.handle_callback(update)
    duplicate = handler.handle_callback(update)
    assert first.messages
    assert duplicate.duplicate and not duplicate.messages
    assert portal.writes == 1


def test_sensitive_callbacks_remain_limited_without_internal_customer_text() -> None:
    handler = BotCommandHandler(settings(sensitive_rate_limit=1), InMemoryTelegramIdentityService())
    first = handler.handle_callback(callback(CallbackAction.TOP_UP, 500))
    rejected = handler.handle_callback(callback(CallbackAction.RENEW, 501, value="service"))
    assert first.messages
    assert not rejected.messages
    assert rejected.callback_notice == "لطفاً چند لحظه صبر کنید."
    assert all(term not in rejected.callback_notice for term in ("429", "Retry-After", "HTTP"))


def test_identical_in_flight_callback_is_deduplicated() -> None:
    entered = threading.Event()
    release = threading.Event()

    class SlowPortal(InMemoryCustomerPortal):
        def services(self, context: CustomerContext):  # type: ignore[no-untyped-def]
            entered.set()
            release.wait(timeout=2)
            return super().services(context)

    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=SlowPortal())
    results: list[HandlerResult] = []

    def render() -> None:
        results.append(handler.handle_callback(callback(CallbackAction.MY_SERVICES, 600)))

    thread = threading.Thread(target=render)
    thread.start()
    assert entered.wait(timeout=2)
    duplicate = handler.handle_callback(callback(CallbackAction.MY_SERVICES, 601))
    release.set()
    thread.join(timeout=2)
    assert duplicate.duplicate and not duplicate.messages
    assert len(results) == 1 and results[0].messages
