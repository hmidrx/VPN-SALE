from __future__ import annotations

import asyncio
import logging
from hashlib import sha256
from io import StringIO

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.main import configure_logging
from telegram_bot.transport.polling import TelegramPollingRuntime


def _settings(token: str) -> BotSettings:
    return BotSettings(
        enabled=True,
        token=token,
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"rate").hexdigest(),
        polling_timeout_seconds=0,
    )


def _synthetic_bot_credential() -> str:
    prefix = str(123_456_789)
    digest = sha256(b"telegram logging fixture").hexdigest()
    return ":".join((prefix, digest))


def test_logging_setup_is_idempotent_and_emits_safe_info() -> None:
    logger = logging.getLogger("telegram_bot")
    previous = list(logger.handlers)
    logger.handlers.clear()
    try:
        configure_logging()
        configure_logging()
        handlers = [h for h in logger.handlers if getattr(h, "_vpn_sale_handler", False)]
        assert len(handlers) == 1
        stream = StringIO()
        handlers[0].setStream(stream)
        logging.getLogger("telegram_bot.transport.polling").info(
            "telegram bot polling initialization successful"
        )
        output = stream.getvalue()
        assert output.count("telegram bot polling initialization successful") == 1
    finally:
        logger.handlers[:] = previous


def test_transient_failure_logs_only_exception_class() -> None:
    credential_fixture = _synthetic_bot_credential()

    class Transport:
        async def call(self, method: str, payload: dict[str, object] | None = None) -> dict:
            if method == "getMe":
                return {"ok": True, "result": {"username": "safe_bot"}}
            if method == "deleteWebhook":
                return {"ok": True, "result": True}
            if method == "getUpdates":
                raise RuntimeError(f"request included {credential_fixture} and update 987654321")
            raise AssertionError(method)

    async def scenario() -> None:
        runtime = TelegramPollingRuntime(
            _settings(credential_fixture),
            InMemoryTelegramIdentityService(),
            Transport(),
            retry_base_seconds=0.01,
        )
        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.02)
        runtime.stop()
        await task

    logger = logging.getLogger("telegram_bot")
    previous = list(logger.handlers)
    logger.handlers.clear()
    try:
        configure_logging()
        stream = StringIO()
        logger.handlers[0].setStream(stream)
        asyncio.run(scenario())
        output = stream.getvalue()
        assert "telegram bot polling initialization successful" in output
        assert "telegram polling transient failure: RuntimeError" in output
        assert credential_fixture not in output
        assert "987654321" not in output
    finally:
        logger.handlers[:] = previous
