from __future__ import annotations

from telegram_bot.config import BotMode, BotSettings


def validate_polling(settings: BotSettings) -> None:
    if settings.mode != BotMode.POLLING:
        raise ValueError("polling mode is not enabled")
    settings.validate()
