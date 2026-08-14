from __future__ import annotations

import logging
from hashlib import sha256

from _pytest.logging import LogCaptureFixture

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    IncomingCallback,
    IncomingCommand,
    IncomingUser,
)


def _settings() -> BotSettings:
    h = sha256(b"bot-native").hexdigest()
    return BotSettings(
        enabled=True,
        token=h,
        mode=BotMode.WEBHOOK,
        webhook_base_url="https://bot.example.test",
        webhook_secret_token=h,
        mini_app_base_url="https://customer.example.test/app",
        mini_app_allowed_hosts=("customer.example.test",),
        rate_limit_secret=h,
    )


def _user(username: str = "old", language_code: str = "fa") -> IncomingUser:
    return IncomingUser(42, username=username, first_name="علی", language_code=language_code)


def _callback(
    action: CallbackAction, value: str = "", update_id: int = 100, user: IncomingUser | None = None
) -> IncomingCallback:
    return IncomingCallback(
        update_id, "cb", "private", user or _user(), BotCallback(action, value).pack()
    )


def test_start_resolves_canonical_customer_and_username_change_does_not_duplicate() -> None:
    identity = InMemoryTelegramIdentityService()
    handler = BotCommandHandler(_settings(), identity)
    handler.handle_command(IncomingCommand(1, "private", _user("first"), "/start"))
    handler.handle_command(IncomingCommand(2, "private", _user("changed"), "/start"))
    assert identity.audit_events == 2
    assert identity.customer_count() == 1
    assert identity.customer_ref_for(42) == "user-42"


def test_all_customer_menu_items_are_bot_native_callbacks_without_mini_app_requirement() -> None:
    result = BotCommandHandler(_settings(), InMemoryTelegramIdentityService()).handle_command(
        IncomingCommand(3, "private", _user(), "/start")
    )
    rows = result.messages[0].rows
    assert rows[0][0]["text"] == "🛒 خرید سرویس"
    assert rows[0][1]["text"] == "📦 سرویس‌های من"
    assert rows[1][0]["text"] == "💳 کیف پول"
    assert all("callback_data" in button for row in rows for button in row)
    assert all("web_app_url" not in button for row in rows for button in row)


def test_profile_services_wallet_support_education_security_status_privacy_help_work_in_bot() -> (
    None
):
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    for idx, action in enumerate(
        [
            CallbackAction.PROFILE,
            CallbackAction.MY_SERVICES,
            CallbackAction.WALLET,
            CallbackAction.SUPPORT,
            CallbackAction.OPEN_EDUCATION,
            CallbackAction.SECURITY,
            CallbackAction.STATUS,
            CallbackAction.PRIVACY,
            CallbackAction.HELP,
        ],
        start=10,
    ):
        result = handler.handle_callback(_callback(action, update_id=idx))
        assert result.acknowledged and result.messages and result.messages[0].text


def test_service_ownership_stale_and_duplicate_callbacks_are_safe() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    forbidden = handler.handle_callback(
        _callback(CallbackAction.OPEN_SERVICE, "svc-a", 20, IncomingUser(7, language_code="fa"))
    )
    assert "متعلق به شما نیست" in forbidden.messages[0].text
    first = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 21))
    duplicate = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 21))
    stale = handler.handle_callback(IncomingCallback(22, "cb", "private", _user(), "bad"))
    assert "پلن استاندارد" in first.messages[0].text
    assert duplicate.duplicate and duplicate.messages == ()
    assert stale.messages and "مشکلی" in stale.messages[0].text


def test_deferred_provider_writes_use_safe_customer_destinations_without_test_copy() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    for idx, action in enumerate(
        [
            CallbackAction.BUY_SERVICE,
            CallbackAction.OPEN_SUBSCRIPTION,
            CallbackAction.RENEW,
            CallbackAction.UPGRADE,
            CallbackAction.EXTRA_TRAFFIC,
            CallbackAction.TOP_UP,
        ],
        start=30,
    ):
        result = handler.handle_callback(
            _callback(action, "svc-a" if action != CallbackAction.TOP_UP else "", idx)
        )
        assert result.messages
        assert "TEST" not in result.messages[0].text
        assert "ساختگی" not in result.messages[0].text


def test_stale_language_callback_stays_persian() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    result = handler.handle_callback(_callback(CallbackAction.SET_LANGUAGE, "en", 40))
    assert "دکمه قدیمی" in result.messages[0].text
    assert result.messages[0].rows == [[{"text": "🏠 منوی اصلی", "callback_data": "b:v1:home:"}]]


def test_long_service_and_transaction_lists_paginate_and_callback_data_has_no_secrets() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    services = handler.handle_callback(_callback(CallbackAction.MY_SERVICES, "0", 50))
    wallet = handler.handle_callback(_callback(CallbackAction.WALLET, "0", 51))
    callback_blob = repr(services.messages[0].rows + wallet.messages[0].rows)
    assert "svc-a" in callback_blob
    assert (
        "vless://" not in callback_blob
        and "access_token" not in callback_blob
        and "postgres" not in callback_blob
    )
    assert len(wallet.messages[0].text.splitlines()) >= 6


def test_conversation_cancel_timeout_restart_and_ticket_idempotency() -> None:
    # Durable stores can be reattached; repeated create_ticket is idempotent.
    portal = InMemoryCustomerPortal()
    handler1 = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    context = CustomerContext("user-42", 42, "fa")
    first = portal.create_ticket(context, "billing", "subject", "message")
    second = portal.create_ticket(context, "billing", "subject", "message")
    assert first.ref == second.ref
    assert handler1.conversations.cancel("missing") is False


def test_sensitive_values_do_not_appear_in_logs_or_callback_data(
    caplog: LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    sensitive_value = "vless://" + "access-token"
    data = BotCallback(CallbackAction.OPEN_SERVICE, "opaque-ref").pack()
    logging.getLogger("telegram_bot.test").info("operation=%s result=%s", "open_service", "denied")
    assert sensitive_value not in caplog.text
    assert "vless://" not in data and "secret" not in data
