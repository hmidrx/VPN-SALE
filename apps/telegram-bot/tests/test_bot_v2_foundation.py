from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    IncomingCallback,
    IncomingCommand,
    IncomingUser,
)
from telegram_bot.screens import ScreenId


def settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"bot-v2-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"rate").hexdigest(),
    )


def user() -> IncomingUser:
    return IncomingUser(42, username="changed", first_name="Ali <Store>", language_code="en")


def callback(action: CallbackAction, value: str = "", update_id: int = 100) -> IncomingCallback:
    return IncomingCallback(
        update_id, f"cb-{update_id}", "private", user(), BotCallback(action, value).pack()
    )


def test_start_is_persian_first_and_two_column_dashboard() -> None:
    result = BotCommandHandler(settings(), InMemoryTelegramIdentityService()).handle_command(
        IncomingCommand(1, "private", user(), "/start")
    )
    message = result.messages[0]
    assert "💳 موجودی:" in message.text
    assert "📦 سرویس فعال:" in message.text
    assert "Ali &lt;Store&gt;" in message.text
    assert "Wallet:" not in message.text
    assert len(message.rows[0]) == 2
    assert message.rows[0][0]["text"] == "🛒 خرید سرویس"
    assert message.rows[0][1]["text"] == "📦 سرویس‌های من"
    assert all("web_app_url" not in button for row in message.rows for button in row)


def test_every_visible_dashboard_button_acknowledges_and_renders_native_screen() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    start = handler.handle_command(IncomingCommand(2, "private", user(), "/start"))
    callbacks = [button["callback_data"] for row in start.messages[0].rows for button in row]
    for idx, data in enumerate(callbacks, start=10):
        result = handler.handle_callback(
            IncomingCallback(idx, f"cb-{idx}", "private", user(), data)
        )
        assert result.acknowledged
        assert result.messages
        assert "http" not in result.messages[0].text.lower()
        assert "Traceback" not in result.messages[0].text


def test_navigation_refresh_retry_back_home_language_and_web_are_handled() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    for idx, item in enumerate(
        [
            (CallbackAction.NAVIGATE, ScreenId.SETTINGS.value),
            (CallbackAction.BACK, ""),
            (CallbackAction.HOME, ""),
            (CallbackAction.REFRESH, ""),
            (CallbackAction.RETRY, ""),
            (CallbackAction.NAVIGATE, ScreenId.LANGUAGE.value),
            (CallbackAction.SET_LANGUAGE, "en"),
            (CallbackAction.OPEN_WEB_APP, ""),
            (CallbackAction.CANCEL, ""),
        ],
        start=1000,
    ):
        result = handler.handle_callback(callback(item[0], item[1], idx))
        assert result.acknowledged
        assert result.messages


def test_callback_payloads_are_versioned_short_and_malformed_safe() -> None:
    packed = BotCallback(CallbackAction.NAVIGATE, ScreenId.WALLET.value).pack()
    assert packed.startswith("b:v1:")
    assert len(packed.encode()) <= 64
    result = BotCommandHandler(settings(), InMemoryTelegramIdentityService()).handle_callback(
        IncomingCallback(70, "bad", "private", user(), "not-a-callback")
    )
    assert result.acknowledged
    assert "مشکلی" in result.messages[0].text or "قدیمی" in result.messages[0].text
