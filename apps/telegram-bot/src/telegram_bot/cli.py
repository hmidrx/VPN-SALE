from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any, cast

from telegram_bot.commands import command_definitions
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.transport.polling import UrlLibTelegramTransport


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return default if value is None or value == "" else int(value)


def _env_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


def load_settings_from_environment() -> BotSettings:
    mode_value = os.environ.get("VPN_SALE_BOT_MODE", BotMode.DISABLED.value)
    return BotSettings(
        enabled=_env_bool("VPN_SALE_BOT_ENABLED"),
        token=os.environ.get("VPN_SALE_TELEGRAM_BOT_TOKEN", ""),
        username=os.environ.get("VPN_SALE_TELEGRAM_BOT_USERNAME", ""),
        display_name=os.environ.get("VPN_SALE_TELEGRAM_BOT_DISPLAY_NAME", "VPN-SALE"),
        mode=BotMode(mode_value),
        environment=os.environ.get("VPN_SALE_ENVIRONMENT", "local"),
        webhook_base_url=os.environ.get("VPN_SALE_TELEGRAM_WEBHOOK_BASE_URL", ""),
        webhook_path=os.environ.get("VPN_SALE_TELEGRAM_WEBHOOK_PATH", "/telegram/webhook"),
        webhook_secret_token=os.environ.get("VPN_SALE_TELEGRAM_WEBHOOK_SECRET_TOKEN", ""),
        webhook_max_connections=_env_int("VPN_SALE_TELEGRAM_WEBHOOK_MAX_CONNECTIONS", 40),
        webhook_request_size_limit=_env_int(
            "VPN_SALE_TELEGRAM_WEBHOOK_REQUEST_SIZE_LIMIT", 256 * 1024
        ),
        webhook_listen_host=os.environ.get("VPN_SALE_TELEGRAM_WEBHOOK_LISTEN_HOST", "127.0.0.1"),
        webhook_listen_port=_env_int("VPN_SALE_TELEGRAM_WEBHOOK_LISTEN_PORT", 8081),
        allowed_updates=_env_tuple(
            "VPN_SALE_TELEGRAM_ALLOWED_UPDATES", ("message", "callback_query")
        ),
        polling_timeout_seconds=_env_int("VPN_SALE_TELEGRAM_POLLING_TIMEOUT_SECONDS", 30),
        mini_app_base_url=os.environ.get("VPN_SALE_CUSTOMER_MINI_APP_URL", "http://localhost:3000"),
        mini_app_allowed_hosts=_env_tuple(
            "VPN_SALE_CUSTOMER_MINI_APP_ALLOWED_HOSTS", ("localhost", "127.0.0.1")
        ),
        default_locale=os.environ.get("VPN_SALE_TELEGRAM_DEFAULT_LOCALE", "fa"),
        supported_locales=_env_tuple("VPN_SALE_TELEGRAM_SUPPORTED_LOCALES", ("fa",)),
        update_idempotency_ttl_seconds=_env_int(
            "VPN_SALE_TELEGRAM_UPDATE_IDEMPOTENCY_TTL_SECONDS", 86400
        ),
        command_rate_limit=_env_int("VPN_SALE_TELEGRAM_COMMAND_RATE_LIMIT", 12),
        command_rate_limit_window_seconds=_env_int(
            "VPN_SALE_TELEGRAM_COMMAND_RATE_LIMIT_WINDOW_SECONDS", 60
        ),
        navigation_rate_limit=_env_int("VPN_SALE_TELEGRAM_NAVIGATION_RATE_LIMIT", 30),
        navigation_rate_limit_window_seconds=_env_int(
            "VPN_SALE_TELEGRAM_NAVIGATION_RATE_LIMIT_WINDOW_SECONDS", 10
        ),
        mutation_rate_limit=_env_int("VPN_SALE_TELEGRAM_MUTATION_RATE_LIMIT", 1),
        mutation_rate_limit_window_seconds=_env_int(
            "VPN_SALE_TELEGRAM_MUTATION_RATE_LIMIT_WINDOW_SECONDS", 3
        ),
        sensitive_rate_limit=_env_int("VPN_SALE_TELEGRAM_SENSITIVE_RATE_LIMIT", 12),
        sensitive_rate_limit_window_seconds=_env_int(
            "VPN_SALE_TELEGRAM_SENSITIVE_RATE_LIMIT_WINDOW_SECONDS", 60
        ),
        throttle_notice_cooldown_seconds=_env_int(
            "VPN_SALE_TELEGRAM_THROTTLE_NOTICE_COOLDOWN_SECONDS", 3
        ),
        rate_limit_secret=os.environ.get("VPN_SALE_TELEGRAM_RATE_LIMIT_KEY", ""),
        help_url=os.environ.get("VPN_SALE_TELEGRAM_HELP_URL", ""),
        privacy_url=os.environ.get("VPN_SALE_TELEGRAM_PRIVACY_URL", ""),
        internal_api_url=os.environ.get("VPN_SALE_TELEGRAM_INTERNAL_API_URL", ""),
        internal_token_file=os.environ.get("VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE", ""),
        redis_url=os.environ.get("VPN_SALE_REDIS_URL", ""),
    )


async def _run_management_command(
    settings: BotSettings, command: str, *, drop_pending_updates: bool
) -> dict[str, object]:
    transport = UrlLibTelegramTransport(settings.token)
    if command == "configure-webhook":
        response = await transport.call(
            "setWebhook",
            {
                "url": settings.webhook_url,
                "secret_token": settings.webhook_secret_token,
                "max_connections": settings.webhook_max_connections,
                "allowed_updates": list(settings.allowed_updates),
                "drop_pending_updates": drop_pending_updates,
            },
        )
        return {"command": command, "configured": bool(response.get("result"))}
    if command == "remove-webhook":
        response = await transport.call(
            "deleteWebhook", {"drop_pending_updates": drop_pending_updates}
        )
        return {"command": command, "removed": bool(response.get("result"))}
    if command == "inspect-webhook":
        response = await transport.call("getWebhookInfo")
        result_obj = response.get("result")
        result = cast(dict[str, Any], result_obj) if isinstance(result_obj, dict) else {}
        url = result.get("url")
        pending = result.get("pending_update_count")
        return {
            "command": command,
            "configured": isinstance(url, str) and bool(url),
            "pending_update_count": pending if isinstance(pending, int) else 0,
        }
    if command == "register-commands":
        definitions = command_definitions(settings.default_locale)
        response = await transport.call(
            "setMyCommands",
            {
                "commands": [
                    {"command": definition.command, "description": definition.description}
                    for definition in definitions
                ]
            },
        )
        return {
            "command": command,
            "registered": bool(response.get("result")),
            "count": len(definitions),
        }
    raise ValueError("unsupported Telegram management command")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="telegram-bot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect-webhook")
    remove = sub.add_parser("remove-webhook")
    remove.add_argument("--drop-pending-updates", action="store_true")
    sub.add_parser("register-commands")
    configure = sub.add_parser("configure-webhook")
    configure.add_argument("--drop-pending-updates", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings_from_environment()
    settings.validate()
    drop_pending_updates = bool(getattr(args, "drop_pending_updates", False))
    result = asyncio.run(
        _run_management_command(
            settings, str(args.command), drop_pending_updates=drop_pending_updates
        )
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
