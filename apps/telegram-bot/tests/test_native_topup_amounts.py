from datetime import UTC, datetime
from hashlib import sha256

import pytest

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    IncomingCommand,
    IncomingText,
    IncomingUser,
)
from telegram_bot.topup import MINIMUM_TOPUP_TOMAN, TOPUP_PRESETS, parse_toman_amount, toman_to_rial


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"topup-bot-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"topup-rate-limit").hexdigest(),
    )


def _user() -> IncomingUser:
    return IncomingUser(42, first_name="علی", language_code="fa")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("۱۰۰٬۰۰۰", 100_000),
        ("١٠٠،٠٠٠", 100_000),
        ("100,000", 100_000),
        (" 1 000 000 ", 1_000_000),
    ],
)
def test_parse_toman_amount_accepts_persian_arabic_and_latin_digits(
    value: str, expected: int
) -> None:
    assert parse_toman_amount(value) == expected


@pytest.mark.parametrize("value", ["99999", "۱۲.۵۰۰", "مبلغ", "-100000", ""])
def test_parse_toman_amount_rejects_invalid_or_below_minimum(value: str) -> None:
    with pytest.raises(ValueError):
        parse_toman_amount(value)


def test_presets_and_exact_rial_conversion() -> None:
    assert TOPUP_PRESETS == (100_000, 250_000, 500_000, 1_000_000, 2_000_000)
    assert toman_to_rial(MINIMUM_TOPUP_TOMAN) == 1_000_000


def test_topup_command_and_amount_state_survive_handler_recreation() -> None:
    identity = InMemoryTelegramIdentityService()
    first = BotCommandHandler(_settings(), identity)
    prompt = first.handle_command(IncomingCommand(10, "private", _user(), "/topup"))
    assert "مبلغ افزایش موجودی" in prompt.messages[0].text
    store = first.conversations
    restarted = BotCommandHandler(_settings(), identity, conversations=store)
    review = restarted.handle_text(IncomingText(11, "private", _user(), "۲۵۰٬۰۰۰"))
    assert "کارت‌به‌کارت" in review.messages[0].text
    state = store.get("tg:42", datetime.now(UTC))
    assert state.amount_toman == 250_000
    assert state.idempotency_key == "tg-topup:10"


def test_ordinary_text_outside_conversation_is_not_ignored() -> None:
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService())
    result = handler.handle_text(IncomingText(20, "private", _user(), "سلام"))
    assert result.messages[0].text == "برای ادامه از منوی ربات استفاده کنید."
