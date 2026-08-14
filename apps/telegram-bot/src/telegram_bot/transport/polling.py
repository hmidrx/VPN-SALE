from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    IncomingCallback,
    IncomingCommand,
    IncomingText,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.version import BOT_V2_VERSION_MARKER

LOG = logging.getLogger(__name__)


class TelegramTransport(Protocol):
    async def call(
        self, method: str, payload: dict[str, object] | None = None
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PollingStats:
    get_me_called: bool = False
    webhook_removed: bool = False
    last_offset: int = 0


class UrlLibTelegramTransport:
    def __init__(self, token: str, *, timeout: float = 35.0) -> None:
        self._base = f"https://api.telegram.org/bot{token}/"
        self._timeout = timeout

    async def call(self, method: str, payload: dict[str, object] | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self._call_blocking, method, payload or {})

    def _call_blocking(self, method: str, payload: dict[str, object]) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        request = urllib.request.Request(  # noqa: S310 - fixed HTTPS Telegram API base URL
            self._base + method,
            data=data,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                body = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Telegram API request failed: {method}") from exc
        parsed = cast(dict[str, Any], json.loads(body.decode()))
        if not parsed.get("ok"):
            raise RuntimeError(f"Telegram API rejected {method}")
        return parsed


def validate_polling(settings: BotSettings) -> None:
    if settings.mode != BotMode.POLLING:
        raise ValueError("polling mode is not enabled")
    settings.validate()


class TelegramPollingRuntime:
    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        transport: TelegramTransport | None = None,
        *,
        portal: CustomerPortalPort | None = None,
        conversations: ConversationStoreV2 | None = None,
        retry_base_seconds: float = 0.2,
        retry_max_seconds: float = 5.0,
    ) -> None:
        validate_polling(settings)
        self.settings = settings
        self.transport = transport or UrlLibTelegramTransport(settings.token)
        if settings.production_like and (portal is None or conversations is None):
            raise ValueError("production polling requires real portal and durable state")
        self.handler = BotCommandHandler(
            settings, identity, portal=portal, conversations=conversations
        )
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.offset = 0
        self.stats = PollingStats()
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        me = await self.transport.call("getMe")
        result_obj = me.get("result")
        result_dict = cast(dict[str, Any], result_obj) if isinstance(result_obj, dict) else {}
        username = _optional_str(result_dict, "username")
        LOG.info(
            "telegram polling authenticated", extra={"bot_username_configured": bool(username)}
        )
        self.stats = PollingStats(
            get_me_called=True, webhook_removed=False, last_offset=self.offset
        )
        await self.transport.call("deleteWebhook", {"drop_pending_updates": False})
        self.stats = PollingStats(True, True, self.offset)
        LOG.info(
            "telegram bot polling initialization successful",
            extra={"version_marker": BOT_V2_VERSION_MARKER, "mode": self.settings.mode.value},
        )
        backoff = self.retry_base_seconds
        while not self._stop.is_set():
            try:
                response = await self.transport.call(
                    "getUpdates",
                    {
                        "offset": self.offset or None,
                        "timeout": self.settings.polling_timeout_seconds,
                        "allowed_updates": list(self.settings.allowed_updates),
                    },
                )
                for update in _updates(response):
                    update_id = int(cast(int, update["update_id"]))
                    self.offset = max(self.offset, update_id + 1)
                    await self._dispatch(update)
                self.stats = PollingStats(True, True, self.offset)
                backoff = self.retry_base_seconds
            except asyncio.CancelledError:
                self.stop()
                raise
            except Exception as exc:  # noqa: BLE001
                LOG.warning("telegram polling transient failure: %s", type(exc).__name__)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(self.retry_max_seconds, backoff * 2)

    async def _dispatch(self, update: dict[str, Any]) -> None:
        callback = _callback_from_update(update)
        if callback is not None:
            result = self.handler.handle_callback(callback)
            answer: dict[str, object] = {"callback_query_id": callback.callback_id}
            if result.callback_notice:
                answer.update({"text": result.callback_notice, "show_alert": result.callback_alert})
            await self.transport.call("answerCallbackQuery", answer)
            chat_id, message_id = _callback_message_ref(update)
            if chat_id is None:
                return
            for message in result.messages:
                payload = _send_message_payload(chat_id, message)
                if message_id is not None:
                    try:
                        edit_payload = dict(payload)
                        edit_payload["message_id"] = message_id
                        await self.transport.call("editMessageText", edit_payload)
                        continue
                    except Exception as exc:  # noqa: BLE001 - callback stays in-place only
                        LOG.info(
                            "telegram callback edit skipped",
                            extra={"result_class": type(exc).__name__},
                        )
                else:
                    await self.transport.call("sendMessage", payload)
            return
        command = _command_from_update(update)
        if command is not None:
            result = self.handler.handle_command(command)
        else:
            text_message = _text_from_update(update)
            if text_message is None:
                return
            result = self.handler.handle_text(text_message)
        message_obj = update.get("message")
        message_data = cast(dict[str, Any], message_obj) if isinstance(message_obj, dict) else {}
        chat_obj = message_data.get("chat")
        chat = cast(dict[str, Any], chat_obj) if isinstance(chat_obj, dict) else {}
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return
        for message in result.messages:
            await self.transport.call("sendMessage", _send_message_payload(chat_id, message))


def _updates(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = response.get("result", [])
    return [item for item in result if isinstance(item, dict) and "update_id" in item]


def _command_from_update(update: dict[str, Any]) -> IncomingCommand | None:
    message_obj = update.get("message")
    if not isinstance(message_obj, dict):
        return None
    message = cast(dict[str, Any], message_obj)
    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("/"):
        return None
    command_text, _, argument = text.partition(" ")
    command = command_text.split("@", 1)[0]
    chat_obj = message.get("chat")
    chat = cast(dict[str, Any], chat_obj) if isinstance(chat_obj, dict) else {}
    user_obj = message.get("from")
    user_data = cast(dict[str, Any], user_obj) if isinstance(user_obj, dict) else None
    user = None
    if user_data and isinstance(user_data.get("id"), int):
        user = IncomingUser(
            telegram_user_id=int(user_data["id"]),
            username=user_data.get("username")
            if isinstance(user_data.get("username"), str)
            else None,
            first_name=user_data.get("first_name")
            if isinstance(user_data.get("first_name"), str)
            else None,
            last_name=user_data.get("last_name")
            if isinstance(user_data.get("last_name"), str)
            else None,
            language_code=user_data.get("language_code")
            if isinstance(user_data.get("language_code"), str)
            else None,
        )
    return IncomingCommand(
        update_id=int(cast(int, update["update_id"])),
        chat_type=_optional_str(chat, "type") or "private",
        user=user,
        command=command,
        argument=argument or None,
    )


def _text_from_update(update: dict[str, Any]) -> IncomingText | None:
    message_obj = update.get("message")
    if not isinstance(message_obj, dict):
        return None
    message = cast(dict[str, Any], message_obj)
    if not isinstance(message.get("text"), str):
        return None
    chat = (
        cast(dict[str, Any], message.get("chat")) if isinstance(message.get("chat"), dict) else {}
    )
    user_data = (
        cast(dict[str, Any], message.get("from")) if isinstance(message.get("from"), dict) else {}
    )
    if not isinstance(user_data.get("id"), int):
        return None
    user = IncomingUser(
        telegram_user_id=int(user_data["id"]),
        username=_optional_str(user_data, "username"),
        first_name=_optional_str(user_data, "first_name"),
        last_name=_optional_str(user_data, "last_name"),
        language_code=_optional_str(user_data, "language_code"),
    )
    return IncomingText(
        int(cast(int, update["update_id"])),
        _optional_str(chat, "type") or "private",
        user,
        str(message["text"]),
    )


def _send_message_payload(chat_id: int, message: OutgoingMessage) -> dict[str, object]:
    payload: dict[str, object] = {"chat_id": chat_id, "text": message.text}
    if message.rows:
        keyboard: list[list[dict[str, object]]] = []
        for row in message.rows:
            keyboard.append(
                [
                    {"text": button["text"], "web_app": {"url": button["web_app_url"]}}
                    if "web_app_url" in button
                    else dict(button)
                    for button in row
                ]
            )
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    return payload


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _callback_from_update(update: dict[str, Any]) -> IncomingCallback | None:
    obj = update.get("callback_query")
    if not isinstance(obj, dict):
        return None
    data = cast(dict[str, Any], obj)
    user_data = data.get("from") if isinstance(data.get("from"), dict) else None
    user_dict = cast(dict[str, Any], user_data) if isinstance(user_data, dict) else None
    user = None
    if user_dict and isinstance(user_dict.get("id"), int):
        user = IncomingUser(
            telegram_user_id=int(user_dict["id"]),
            username=_optional_str(user_dict, "username"),
            first_name=_optional_str(user_dict, "first_name"),
            last_name=_optional_str(user_dict, "last_name"),
            language_code=_optional_str(user_dict, "language_code"),
        )
    message_obj = data.get("message")
    message = cast(dict[str, Any], message_obj) if isinstance(message_obj, dict) else {}
    chat_obj = message.get("chat")
    chat = cast(dict[str, Any], chat_obj) if isinstance(chat_obj, dict) else {}
    return IncomingCallback(
        update_id=int(cast(int, update["update_id"])),
        callback_id=str(data.get("id", "")),
        chat_type=_optional_str(chat, "type") or "private",
        user=user,
        data=_optional_str(data, "data"),
    )


def _callback_message_ref(update: dict[str, Any]) -> tuple[int | None, int | None]:
    obj = update.get("callback_query")
    data = cast(dict[str, Any], obj) if isinstance(obj, dict) else {}
    msg_obj = data.get("message")
    msg = cast(dict[str, Any], msg_obj) if isinstance(msg_obj, dict) else {}
    chat_obj = msg.get("chat")
    chat = cast(dict[str, Any], chat_obj) if isinstance(chat_obj, dict) else {}
    chat_id = chat.get("id")
    message_id = msg.get("message_id")
    return (
        chat_id if isinstance(chat_id, int) else None,
        message_id if isinstance(message_id, int) else None,
    )
