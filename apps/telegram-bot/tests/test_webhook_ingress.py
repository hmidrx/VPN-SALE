from __future__ import annotations

import asyncio
import json
import socket
from hashlib import sha256
from typing import Any

from telegram_bot.config import BotMode, BotSettings
from telegram_bot.transport.webhook import HEADER, TelegramWebhookServer


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _settings(port: int) -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"webhook-test-bot").hexdigest(),
        mode=BotMode.WEBHOOK,
        environment="TEST",
        webhook_base_url="https://bot.example.test",
        webhook_path="/telegram/webhook",
        webhook_secret_token=sha256(b"webhook-test-secret").hexdigest(),
        webhook_listen_host="127.0.0.1",
        webhook_listen_port=port,
        mini_app_base_url="https://customer.example.test",
        mini_app_allowed_hosts=("customer.example.test",),
        rate_limit_secret=sha256(b"webhook-test-rate").hexdigest(),
    )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    async def dispatch_update(self, update: dict[str, Any]) -> None:
        self.updates.append(update)


async def _request(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    writer.write_eof()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


def _post(path: str, body: bytes, secret: str | None, *, content_length: int | None = None) -> bytes:
    headers = [
        f"POST {path} HTTP/1.1",
        "Host: bot.example.test",
        "Content-Type: application/json",
        f"Content-Length: {len(body) if content_length is None else content_length}",
    ]
    if secret is not None:
        headers.append(f"{HEADER}: {secret}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body


def test_webhook_accepts_authenticated_update_and_health_is_public_safe() -> None:
    async def scenario() -> None:
        port = _free_port()
        settings = _settings(port)
        dispatcher = RecordingDispatcher()
        server = TelegramWebhookServer(settings, dispatcher)
        await server.start()
        try:
            update = {
                "update_id": 101,
                "message": {
                    "chat": {"id": 1001, "type": "private"},
                    "from": {"id": 42},
                    "text": "/start",
                },
            }
            body = json.dumps(update).encode()
            response = await _request(
                port, _post(settings.webhook_path, body, settings.webhook_secret_token)
            )
            assert response.startswith(b"HTTP/1.1 200 OK\r\n")
            assert dispatcher.updates == [update]

            health = await _request(
                port,
                b"GET /healthz HTTP/1.1\r\nHost: telegram-bot\r\n\r\n",
            )
            assert health.startswith(b"HTTP/1.1 200 OK\r\n")
            assert settings.webhook_secret_token.encode() not in health
            assert settings.token.encode() not in health
        finally:
            await server.close()

    asyncio.run(scenario())


def test_webhook_rejects_missing_or_wrong_secret_without_dispatch() -> None:
    async def scenario() -> None:
        port = _free_port()
        settings = _settings(port)
        dispatcher = RecordingDispatcher()
        server = TelegramWebhookServer(settings, dispatcher)
        await server.start()
        try:
            body = b'{"update_id":102}'
            missing = await _request(port, _post(settings.webhook_path, body, None))
            wrong = await _request(port, _post(settings.webhook_path, body, "wrong"))
            assert missing.startswith(b"HTTP/1.1 403 Forbidden\r\n")
            assert wrong.startswith(b"HTTP/1.1 403 Forbidden\r\n")
            assert dispatcher.updates == []
        finally:
            await server.close()

    asyncio.run(scenario())


def test_webhook_rejects_bad_json_wrong_path_and_oversized_body() -> None:
    async def scenario() -> None:
        port = _free_port()
        settings = _settings(port)
        dispatcher = RecordingDispatcher()
        server = TelegramWebhookServer(settings, dispatcher)
        await server.start()
        try:
            malformed = await _request(
                port,
                _post(settings.webhook_path, b"{bad", settings.webhook_secret_token),
            )
            wrong_path = await _request(
                port,
                _post("/not-telegram", b'{"update_id":103}', settings.webhook_secret_token),
            )
            oversized = await _request(
                port,
                _post(
                    settings.webhook_path,
                    b"{}",
                    settings.webhook_secret_token,
                    content_length=settings.webhook_request_size_limit + 1,
                ),
            )
            assert malformed.startswith(b"HTTP/1.1 400 Bad Request\r\n")
            assert wrong_path.startswith(b"HTTP/1.1 404 Not Found\r\n")
            assert oversized.startswith(b"HTTP/1.1 413 Payload Too Large\r\n")
            assert dispatcher.updates == []
        finally:
            await server.close()

    asyncio.run(scenario())
