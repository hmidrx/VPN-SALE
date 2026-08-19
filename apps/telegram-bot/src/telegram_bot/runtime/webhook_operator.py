from __future__ import annotations

from typing import Any

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.runtime.operator import OperatorBotCommandHandler, OperatorTelegramPollingRuntime
from telegram_bot.transport.polling import TelegramTransport, UrlLibTelegramTransport


class OperatorTelegramWebhookRuntime(OperatorTelegramPollingRuntime):
    """Reuse the production command/update dispatcher without starting long polling."""

    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        transport: TelegramTransport | None = None,
        *,
        portal: CustomerPortalPort | None = None,
        conversations: ConversationStoreV2 | None = None,
    ) -> None:
        if settings.mode != BotMode.WEBHOOK:
            raise ValueError("webhook mode is not enabled")
        settings.validate()
        if settings.production_like and (portal is None or conversations is None):
            raise ValueError("production webhook requires real portal and durable state")
        self.settings = settings
        self.transport = transport or UrlLibTelegramTransport(settings.token)
        self.handler = OperatorBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )

    async def dispatch_update(self, update: dict[str, Any]) -> None:
        await self._dispatch(update)
