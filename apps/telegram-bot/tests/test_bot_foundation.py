from __future__ import annotations

import time
from hashlib import sha256

import pytest

from telegram_bot.application.identity import (
    AccountStatus,
    InMemoryTelegramIdentityService,
    TelegramIdentityResult,
)
from telegram_bot.application.payloads import PayloadKind, parse_start_payload
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.commands import command_definitions
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.idempotency import InMemoryUpdateIdempotency
from telegram_bot.localization import normalize_locale, t
from telegram_bot.menu import default_menu_registry
from telegram_bot.mini_app import MiniAppRoute, MiniAppUrlBuilder
from telegram_bot.observability import sanitize_log_fields
from telegram_bot.rate_limit import InMemoryBotRateLimiter, RateLimitExceeded
from telegram_bot.runtime.handlers import BotCommandHandler, IncomingCommand, IncomingUser
from telegram_bot.runtime.lifecycle import BotRuntime
from telegram_bot.transport.webhook import WebhookSecretValidator


def _test_material(label: str) -> str:
    return sha256(f"telegram-bot-test-{label}".encode()).hexdigest()


def settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=_test_material("bot"),
        mode=BotMode.WEBHOOK,
        webhook_base_url="https://bot.example.test",
        webhook_secret_token=_test_material("webhook"),
        mini_app_base_url="https://customer.example.test/app",
        mini_app_allowed_hosts=("customer.example.test",),
        rate_limit_secret=_test_material("rate"),
    )


def private_start(update_id: int = 1, arg: str | None = "v1_app_home") -> IncomingCommand:
    return IncomingCommand(
        update_id=update_id,
        chat_type="private",
        user=IncomingUser(
            telegram_user_id=42, username="name", first_name="علی", language_code="fa"
        ),
        command="/start",
        argument=arg,
    )


def test_start_payload_parser_accepts_versioned_mini_app_and_rejects_unsafe() -> None:
    assert parse_start_payload("v1_app_profile").kind == PayloadKind.MINI_APP_ROUTE
    assert not parse_start_payload("../../etc/passwd").valid
    assert not parse_start_payload("https://evil.example").valid
    assert not parse_start_payload("x" * 65).valid


def test_mini_app_builder_allows_only_safe_routes_hosts_and_queries() -> None:
    builder = MiniAppUrlBuilder(
        "https://customer.example.test/app", ("customer.example.test",), True
    )
    assert builder.build(MiniAppRoute.PROFILE) == "https://customer.example.test/app/profile"
    assert builder.build(MiniAppRoute.WALLET) == "https://customer.example.test/app/wallet"
    with pytest.raises(ValueError):
        MiniAppUrlBuilder("https://evil.example/app", ("customer.example.test",), True).build(
            MiniAppRoute.HOME
        )
    with pytest.raises(ValueError):
        MiniAppUrlBuilder(
            "http://customer.example.test/app", ("customer.example.test",), True
        ).build(MiniAppRoute.HOME)
    with pytest.raises(ValueError):
        MiniAppUrlBuilder(
            "https://customer.example.test/app?access_token=x", ("customer.example.test",), True
        ).build(MiniAppRoute.HOME)


def test_menu_registry_contains_working_items_only() -> None:
    registry = default_menu_registry()
    ids = [item.item_id for item in registry.visible(AccountStatus.ACTIVE)]
    assert ids == [
        "buy",
        "services",
        "profile",
        "wallet",
        "security",
        "support",
        "education",
        "status",
        "language",
        "privacy",
        "help",
        "refresh",
        "home",
    ]
    assert "products" not in ids


def test_locale_resolution_and_fallback() -> None:
    assert normalize_locale("fa-IR", ("fa", "en"), "fa") == "fa"
    assert normalize_locale("de", ("fa", "en"), "fa") == "fa"
    assert t("en", "open_app") == "Open customer app (optional)"
    assert t("unknown", "open_app") == "باز کردن پنل مشتری (اختیاری)"


def test_callback_data_is_versioned_and_strict() -> None:
    data = BotCallback(CallbackAction.PROFILE).pack()
    assert BotCallback.parse(data).action == CallbackAction.PROFILE
    with pytest.raises(ValueError):
        BotCallback.parse("bad")
    with pytest.raises(ValueError):
        BotCallback.parse("b:v9:menu:")
    with pytest.raises(ValueError):
        BotCallback.parse("x" * 65)


def test_update_idempotency_first_duplicate_and_ttl() -> None:
    idem = InMemoryUpdateIdempotency()
    assert idem.claim(100, 1)
    assert not idem.claim(100, 1)
    time.sleep(1.01)
    assert idem.claim(100, 1)


def test_rate_limit_key_is_hmac_hardened_and_enforced() -> None:
    limiter = InMemoryBotRateLimiter(_test_material("limiter"))
    key = limiter.key_for("start", 123456)
    assert "123456" not in key
    limiter.check("start", 123456, 1, 60)
    with pytest.raises(RateLimitExceeded):
        limiter.check("start", 123456, 1, 60)


def test_command_registration_inventory() -> None:
    commands = [cmd.command for cmd in command_definitions("fa")]
    assert commands == [
        "start",
        "menu",
        "help",
        "profile",
        "services",
        "wallet",
        "security",
        "support",
        "language",
        "privacy",
        "cancel",
    ]


def test_webhook_secret_validation_constant_time_interface() -> None:
    validator = WebhookSecretValidator(settings())
    assert validator.validate(_test_material("webhook"))
    assert not validator.validate(None)
    assert not validator.validate("wrong")


def test_start_new_returning_duplicate_no_duplicate_audit_or_welcome() -> None:
    identity = InMemoryTelegramIdentityService()
    handler = BotCommandHandler(settings(), identity)
    first = handler.handle_command(private_start(1))
    duplicate = handler.handle_command(private_start(1))
    returning = handler.handle_command(private_start(2))
    assert first.messages and "آماده" in first.messages[0].text
    assert duplicate.duplicate and duplicate.messages == ()
    assert returning.messages and "خوش برگشتید" in returning.messages[0].text
    assert identity.audit_events == 2


def test_start_handles_unicode_missing_username_missing_language_and_bad_payload() -> None:
    identity = InMemoryTelegramIdentityService()
    handler = BotCommandHandler(settings(), identity)
    cmd = IncomingCommand(3, "private", IncomingUser(99, first_name="测试"), "/start", "bad/url")
    result = handler.handle_command(cmd)
    assert result.acknowledged and result.messages


def test_group_chat_behavior_does_not_expose_customer_menu() -> None:
    result = BotCommandHandler(settings(), InMemoryTelegramIdentityService()).handle_command(
        IncomingCommand(4, "group", IncomingUser(42), "/start")
    )
    assert result.messages and result.messages[0].rows == []


def test_account_status_restrictions_hide_mini_app() -> None:
    class SuspendedIdentity(InMemoryTelegramIdentityService):
        def register_or_update(self, command):  # type: ignore[no-untyped-def,reportUnknownParameterType]
            return TelegramIdentityResult("u", AccountStatus.SUSPENDED, False, "fa")

    result = BotCommandHandler(settings(), SuspendedIdentity()).handle_command(private_start(5))
    assert result.messages and result.messages[0].rows == []
    assert "محدود" in result.messages[0].text


def test_commands_help_profile_security_language_privacy_cancel() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    for idx, command in enumerate(
        ["/menu", "/help", "/profile", "/security", "/language", "/privacy", "/cancel"], start=10
    ):
        result = handler.handle_command(
            IncomingCommand(idx, "private", IncomingUser(42, language_code="fa"), command)
        )
        assert result.acknowledged and result.messages


def test_customer_menu_uses_bot_native_callbacks_not_required_web_app_urls() -> None:
    result = BotCommandHandler(settings(), InMemoryTelegramIdentityService()).handle_command(
        private_start(20)
    )
    rows = result.messages[0].rows
    assert rows[0][0]["callback_data"]
    assert all("web_app_url" not in button for row in rows for button in row)


def test_sanitized_logs_remove_identity_and_secret_fields() -> None:
    safe = sanitize_log_fields(
        {"handler": "start", "telegram_id": 42, "token": _test_material("log"), "chat_id": 100}
    )
    assert safe == {"handler": "start"}


def test_runtime_disabled_health_is_honest_and_webhook_ready_validates() -> None:
    disabled = BotRuntime(BotSettings())
    assert disabled.health()["mode"] == "disabled"
    assert not disabled.ready().ready
    assert BotRuntime(settings()).ready().ready


def test_bot_blocked_state_can_be_marked_and_cleared_by_update() -> None:
    identity = InMemoryTelegramIdentityService()
    identity.mark_bot_blocked(42)
    BotCommandHandler(settings(), identity).handle_command(private_start(30))
    assert 42 not in identity._blocked  # test fake inspection only
