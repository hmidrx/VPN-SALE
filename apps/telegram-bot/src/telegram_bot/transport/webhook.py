from __future__ import annotations

import hmac

from telegram_bot.config import BotSettings
from telegram_bot.observability import BotMetrics

HEADER = "x-telegram-bot-api-secret-token"


class WebhookSecretValidator:
    def __init__(self, settings: BotSettings, metrics: BotMetrics | None = None) -> None:
        self.settings = settings
        self.metrics = metrics or BotMetrics()

    def validate(self, presented: str | None) -> bool:
        ok = bool(presented) and hmac.compare_digest(
            presented or "", self.settings.webhook_secret_token
        )
        if not ok:
            self.metrics.inc("webhook_secret_rejection")
        return ok
