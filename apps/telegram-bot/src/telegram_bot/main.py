from __future__ import annotations

import asyncio
import logging
import signal

from telegram_bot.cli import load_settings_from_environment
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import RedisConversationStore
from telegram_bot.operator_api import OperatorPrivatePlatformClient
from telegram_bot.runtime.lifecycle import BotRuntime
from telegram_bot.runtime.operator import OperatorTelegramPollingRuntime
from telegram_bot.runtime.subscription_delivery import PrivacyAwareTelegramTransport
from telegram_bot.runtime.webhook_operator import OperatorTelegramWebhookRuntime
from telegram_bot.transport.webhook import TelegramWebhookServer


def configure_logging() -> None:
    """Install one production-safe handler without enabling HTTP debug output."""
    logger = logging.getLogger("telegram_bot")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not any(getattr(handler, "_vpn_sale_handler", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        handler._vpn_sale_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    for noisy_logger in ("urllib3", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def _install_stop_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)


async def _run_polling(settings: BotSettings) -> None:
    platform = OperatorPrivatePlatformClient(
        settings.internal_api_url, settings.internal_token_file
    )
    polling = OperatorTelegramPollingRuntime(
        settings,
        platform,
        PrivacyAwareTelegramTransport(settings.token),
        portal=platform,
        conversations=RedisConversationStore(settings.redis_url),
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, polling.stop)
    await polling.run()


async def _run_webhook(settings: BotSettings) -> None:
    platform = OperatorPrivatePlatformClient(
        settings.internal_api_url, settings.internal_token_file
    )
    dispatcher = OperatorTelegramWebhookRuntime(
        settings,
        platform,
        PrivacyAwareTelegramTransport(settings.token),
        portal=platform,
        conversations=RedisConversationStore(settings.redis_url),
    )
    server = TelegramWebhookServer(settings, dispatcher)
    stop = asyncio.Event()
    _install_stop_signals(stop)
    await server.serve_until(stop)


def main() -> None:
    configure_logging()
    settings = load_settings_from_environment()
    try:
        settings.validate()
    except ValueError as exc:
        raise SystemExit(f"invalid Telegram bot configuration: {exc}") from exc
    runtime = BotRuntime(settings)
    print(runtime.health(), flush=True)
    if not settings.enabled or settings.mode == BotMode.DISABLED:
        return
    if settings.mode == BotMode.POLLING:
        asyncio.run(_run_polling(settings))
        return
    if settings.mode == BotMode.WEBHOOK:
        asyncio.run(_run_webhook(settings))
        return
    raise SystemExit("unsupported Telegram bot mode")


if __name__ == "__main__":
    main()
