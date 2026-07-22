from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.formatting import format_date, format_toman, format_traffic_gb
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    HandlerResult,
    IncomingCallback,
    IncomingCommand,
    IncomingUser,
)
from telegram_bot.screens import ScreenId

FORBIDDEN_UI = ("Language saved.", "English", "Back", "Home", "Refresh", "Cancel")


def _settings() -> BotSettings:
    h = sha256(b"persian-only").hexdigest()
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


def _user(first_name: str = 'Sara & <Dev> "quoted" 😊', lang: str | None = "en") -> IncomingUser:
    return IncomingUser(42, username="latin_user", first_name=first_name, language_code=lang)


def _start(handler: BotCommandHandler, update_id: int = 1, user: IncomingUser | None = None):
    return handler.handle_command(IncomingCommand(update_id, "private", user or _user(), "/start"))


def _callback(
    data: str, update_id: int = 100, user: IncomingUser | None = None
) -> IncomingCallback:
    return IncomingCallback(update_id, f"cb-{update_id}", "private", user or _user(), data)


def _visible_text(result: HandlerResult) -> str:
    message = result.messages[0]
    labels = "\n".join(button["text"] for row in message.rows for button in row)
    return f"{message.text}\n{labels}"


def test_start_is_persian_for_new_and_legacy_english_customer_without_duplicates() -> None:
    identity = InMemoryTelegramIdentityService()
    handler = BotCommandHandler(_settings(), identity)
    first = _start(handler, 1, _user(lang="en-US"))
    second = _start(handler, 2, _user(first_name="Legacy", lang="en"))
    assert "🚀 فروشگاه VPN" in first.messages[0].text
    assert "🚀 فروشگاه VPN" in second.messages[0].text
    assert "Wallet:" not in second.messages[0].text
    assert identity.customer_count() == 1
    assert identity.customer_ref_for(42) == "user-42"


def test_dashboard_and_settings_have_no_language_choice_or_english_button() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    dashboard = _start(handler)
    settings_data = BotCallback(CallbackAction.NAVIGATE, ScreenId.SETTINGS.value).pack()
    settings = handler.handle_callback(_callback(settings_data, 2))
    assert "🌐 English" not in _visible_text(dashboard)
    assert "زبان" not in _visible_text(settings)
    assert "Language" not in _visible_text(settings)


def test_navigation_labels_are_exact_persian_vocabulary() -> None:
    rows = BotCommandHandler(_settings(), InMemoryTelegramIdentityService()).nav_rows("en")
    assert rows == [
        [
            {"text": "◀️ بازگشت", "callback_data": "b:v1:back:"},
            {"text": "🏠 منوی اصلی", "callback_data": "b:v1:home:"},
        ],
        [
            {"text": "🔄 بروزرسانی", "callback_data": "b:v1:ref:"},
            {"text": "❌ لغو", "callback_data": "b:v1:cancel:"},
        ],
    ]


def test_profile_omits_locale_code_and_escapes_names() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    profile = handler.handle_callback(
        _callback(BotCallback(CallbackAction.NAVIGATE, ScreenId.PROFILE.value).pack())
    )
    text = profile.messages[0].text
    assert "زبان انتخابی" not in text
    assert "en" not in text
    assert "&lt;" not in text  # portal profile is server-provided Persian placeholder here
    home = _start(handler, 2)
    assert "Sara &amp; &lt;Dev&gt; &quot;quoted&quot; 😊" in home.messages[0].text


def test_stale_language_callbacks_are_acknowledged_with_home_only() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    result = handler.handle_callback(
        _callback(BotCallback(CallbackAction.SET_LANGUAGE, "en").pack())
    )
    assert result.acknowledged
    assert "دکمه قدیمی" in result.messages[0].text
    assert result.messages[0].rows == [[{"text": "🏠 منوی اصلی", "callback_data": "b:v1:home:"}]]


def test_persian_survives_restart_with_shared_conversation_store() -> None:
    store = DurableMemoryConversationStore()
    identity = InMemoryTelegramIdentityService()
    first = BotCommandHandler(_settings(), identity, conversations=store)
    first.handle_callback(
        _callback(BotCallback(CallbackAction.NAVIGATE, ScreenId.SETTINGS.value).pack())
    )
    restarted = BotCommandHandler(_settings(), identity, conversations=store)
    result = _start(restarted, 200)
    assert "🚀 فروشگاه VPN" in result.messages[0].text
    assert not any(term in _visible_text(result) for term in FORBIDDEN_UI)


def test_persian_formatters_for_money_traffic_and_jalali_dates() -> None:
    assert format_toman(1234567) == "۱,۲۳۴,۵۶۷ تومان"
    assert format_traffic_gb(80) == "۸۰ گیگابایت"
    assert format_date(datetime(2026, 1, 1, tzinfo=UTC)) == "۱۴۰۴/۱۰/۱۱"


def test_customer_visible_text_audit_all_rendered_screens() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    results = [_start(handler, 1)]
    callbacks = [button["callback_data"] for row in results[0].messages[0].rows for button in row]
    callbacks.extend(
        [
            BotCallback(CallbackAction.BACK).pack(),
            BotCallback(CallbackAction.HOME).pack(),
            BotCallback(CallbackAction.REFRESH).pack(),
            BotCallback(CallbackAction.CANCEL).pack(),
            BotCallback(CallbackAction.SET_LANGUAGE, "en").pack(),
        ]
    )
    for idx, data in enumerate(callbacks, start=10):
        result = handler.handle_callback(_callback(data, idx))
        assert result.acknowledged
        assert result.messages
        visible = _visible_text(result)
        assert not any(term in visible for term in FORBIDDEN_UI)
        assert "telegram_bot." not in visible
        assert "vless://" not in visible
        assert "access-token" not in visible
