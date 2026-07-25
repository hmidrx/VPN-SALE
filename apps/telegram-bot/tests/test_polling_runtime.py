from __future__ import annotations

import asyncio
from dataclasses import replace
from hashlib import sha256
from typing import Any, cast

import pytest

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.transport.polling import TelegramPollingRuntime


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"rate").hexdigest(),
        polling_timeout_seconds=0,
    )


class FakeTransport:
    def __init__(self, updates: list[dict[str, Any]]) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.updates = updates

    async def call(self, method: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        self.calls.append((method, payload or {}))
        if method == "getMe":
            return {"ok": True, "result": {"id": 1, "username": "vpnsale_bot"}}
        if method == "deleteWebhook":
            return {"ok": True, "result": True}
        if method == "getUpdates":
            result, self.updates = self.updates, []
            if not result:
                raise asyncio.CancelledError
            return {"ok": True, "result": result}
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": 1}}
        raise AssertionError(method)


def test_polling_getme_webhook_offset_start_menu_and_duplicate() -> None:
    async def scenario() -> None:
        updates = [
            {
                "update_id": 10,
                "message": {
                    "chat": {"id": 100, "type": "private"},
                    "from": {
                        "id": 42,
                        "username": "alice",
                        "first_name": "Alice",
                        "language_code": "en",
                    },
                    "text": "/start v1_app_home",
                },
            },
            {
                "update_id": 10,
                "message": {
                    "chat": {"id": 100, "type": "private"},
                    "from": {"id": 42},
                    "text": "/start",
                },
            },
        ]
        transport = FakeTransport(updates)
        runtime = TelegramPollingRuntime(_settings(), InMemoryTelegramIdentityService(), transport)
        with pytest.raises(asyncio.CancelledError):
            await runtime.run()
        methods = [name for name, _ in transport.calls]
        assert methods[:3] == ["getMe", "deleteWebhook", "getUpdates"]
        assert runtime.offset == 11
        sent = [payload for name, payload in transport.calls if name == "sendMessage"]
        assert len(sent) == 1
        markup = cast(dict[str, Any], sent[0]["reply_markup"])
        keyboard = cast(list[list[dict[str, Any]]], markup["inline_keyboard"])
        assert keyboard[0][0]["callback_data"].startswith("b:v1:")

    asyncio.run(scenario())


def test_polling_invalid_production_config_rejected() -> None:
    bad = BotSettings(
        enabled=True,
        token=sha256(b"bad-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="PRODUCTION",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
    )
    with pytest.raises(ValueError):
        TelegramPollingRuntime(bad, InMemoryTelegramIdentityService(), FakeTransport([]))


def test_callback_throttle_is_alert_only_and_never_sends_chat_message() -> None:
    class CallbackTransport(FakeTransport):
        async def call(
            self, method: str, payload: dict[str, object] | None = None
        ) -> dict[str, Any]:
            self.calls.append((method, payload or {}))
            return {"ok": True, "result": True}

    class TestRuntime(TelegramPollingRuntime):
        async def dispatch(self, update: dict[str, Any]) -> None:
            await self._dispatch(update)

    async def scenario() -> None:
        configured = replace(_settings(), mutation_rate_limit=0)
        transport = CallbackTransport([])
        runtime = TestRuntime(configured, InMemoryTelegramIdentityService(), transport)
        await runtime.dispatch(
            {
                "update_id": 90,
                "callback_query": {
                    "id": "callback-90",
                    "from": {"id": 42, "first_name": "کاربر"},
                    "data": BotCallback(
                        CallbackAction.TOGGLE_NOTIFICATION, "payment_enabled"
                    ).pack(),
                    "message": {"message_id": 7, "chat": {"id": 100, "type": "private"}},
                },
            }
        )
        answers = [
            payload for method, payload in transport.calls if method == "answerCallbackQuery"
        ]
        assert answers == [
            {
                "callback_query_id": "callback-90",
                "text": "لطفاً چند لحظه صبر کنید.",
                "show_alert": True,
            }
        ]
        assert not any(method == "sendMessage" for method, _ in transport.calls)

    asyncio.run(scenario())
