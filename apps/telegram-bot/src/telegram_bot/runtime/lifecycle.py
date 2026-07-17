from __future__ import annotations

from dataclasses import dataclass

from telegram_bot.config import BotMode, BotSettings
from telegram_bot.observability import BotMetrics


@dataclass
class BotRuntimeStatus:
    mode: BotMode
    enabled: bool
    ready: bool
    detail: str


class BotRuntime:
    def __init__(self, settings: BotSettings, metrics: BotMetrics | None = None) -> None:
        self.settings = settings
        self.metrics = metrics or BotMetrics()
        self.running = False

    def health(self) -> dict[str, object]:
        return {
            "service": "telegram-bot",
            "enabled": self.settings.enabled,
            "mode": self.settings.mode.value,
        }

    def ready(self) -> BotRuntimeStatus:
        if not self.settings.enabled or self.settings.mode == BotMode.DISABLED:
            return BotRuntimeStatus(self.settings.mode, self.settings.enabled, False, "disabled")
        try:
            self.settings.validate()
        except ValueError as exc:
            return BotRuntimeStatus(self.settings.mode, self.settings.enabled, False, str(exc))
        return BotRuntimeStatus(self.settings.mode, self.settings.enabled, True, "ready")

    async def shutdown(self) -> None:
        self.running = False
