from __future__ import annotations

import asyncio
import hmac
import json
import logging
from contextlib import suppress
from typing import Any, Protocol, cast

from telegram_bot.config import BotSettings
from telegram_bot.observability import BotMetrics

HEADER = "x-telegram-bot-api-secret-token"
LOG = logging.getLogger(__name__)
_HEADER_LIMIT = 16 * 1024
_READ_TIMEOUT_SECONDS = 10.0


class WebhookUpdateDispatcher(Protocol):
    async def dispatch_update(self, update: dict[str, Any]) -> None: ...


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


class TelegramWebhookServer:
    """Minimal private HTTP ingress for Telegram updates behind the reverse proxy."""

    def __init__(
        self,
        settings: BotSettings,
        dispatcher: WebhookUpdateDispatcher,
        *,
        metrics: BotMetrics | None = None,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.dispatcher = dispatcher
        self.metrics = metrics or BotMetrics()
        self.validator = WebhookSecretValidator(settings, self.metrics)
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("Telegram webhook server is already running")
        self._server = await asyncio.start_server(
            self._handle_connection,
            self.settings.webhook_listen_host,
            self.settings.webhook_listen_port,
        )
        LOG.info(
            "telegram webhook ingress listening",
            extra={
                "listen_port": self.settings.webhook_listen_port,
                "webhook_path": self.settings.webhook_path,
            },
        )

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def serve_until(self, stop: asyncio.Event) -> None:
        await self.start()
        try:
            await stop.wait()
        finally:
            await self.close()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            status, payload = await asyncio.wait_for(
                self._handle_request(reader), timeout=_READ_TIMEOUT_SECONDS
            )
        except TimeoutError:
            status, payload = 408, {"ok": False}
        except (ConnectionError, asyncio.IncompleteReadError, ValueError):
            status, payload = 400, {"ok": False}
        except Exception as exc:  # noqa: BLE001 - never expose request/update details
            LOG.warning("telegram webhook dispatch failed: %s", type(exc).__name__)
            self.metrics.inc("webhook_dispatch_failure")
            status, payload = 503, {"ok": False}
        try:
            writer.write(_http_response(status, payload))
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def _handle_request(self, reader: asyncio.StreamReader) -> tuple[int, dict[str, bool]]:
        request_line = await reader.readline()
        if not request_line or len(request_line) > 4096:
            return 400, {"ok": False}
        try:
            method_raw, target_raw, version_raw = request_line.decode("ascii").strip().split(" ", 2)
        except (UnicodeDecodeError, ValueError):
            return 400, {"ok": False}
        if version_raw not in {"HTTP/1.0", "HTTP/1.1"}:
            return 400, {"ok": False}

        headers: dict[str, str] = {}
        header_bytes = 0
        while True:
            line = await reader.readline()
            header_bytes += len(line)
            if header_bytes > _HEADER_LIMIT:
                return 431, {"ok": False}
            if line in {b"\r\n", b"\n"}:
                break
            if not line:
                return 400, {"ok": False}
            try:
                name, value = line.decode("latin-1").split(":", 1)
            except ValueError:
                return 400, {"ok": False}
            headers[name.strip().lower()] = value.strip()

        path = target_raw.partition("?")[0]
        if method_raw == "GET" and path == "/healthz":
            return 200, {"ok": True}
        if path != self.settings.webhook_path:
            return 404, {"ok": False}
        if method_raw != "POST":
            return 405, {"ok": False}
        if not self.validator.validate(headers.get(HEADER)):
            return 403, {"ok": False}
        content_type = headers.get("content-type", "").partition(";")[0].strip().lower()
        if content_type != "application/json":
            return 415, {"ok": False}
        try:
            content_length = int(headers.get("content-length", ""))
        except ValueError:
            return 411, {"ok": False}
        if content_length < 2:
            return 400, {"ok": False}
        if content_length > self.settings.webhook_request_size_limit:
            return 413, {"ok": False}
        body = await reader.readexactly(content_length)
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return 400, {"ok": False}
        if not isinstance(parsed, dict):
            return 400, {"ok": False}
        update = cast(dict[str, Any], parsed)
        if not isinstance(update.get("update_id"), int):
            return 400, {"ok": False}
        await self.dispatcher.dispatch_update(update)
        self.metrics.inc("webhook_updates_received")
        return 200, {"ok": True}


def _http_response(status: int, payload: dict[str, bool]) -> bytes:
    reason = {
        200: "OK",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        408: "Request Timeout",
        411: "Length Required",
        413: "Payload Too Large",
        415: "Unsupported Media Type",
        431: "Request Header Fields Too Large",
        503: "Service Unavailable",
    }.get(status, "Error")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return (
        f"HTTP/1.1 {status} {reason}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "\r\n"
    ).encode("ascii") + body
