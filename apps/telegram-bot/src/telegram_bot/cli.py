from __future__ import annotations

import argparse

from telegram_bot.commands import command_definitions
from telegram_bot.config import BotMode, BotSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="telegram-bot")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect-webhook")
    sub.add_parser("remove-webhook")
    sub.add_parser("register-commands")
    configure = sub.add_parser("configure-webhook")
    configure.add_argument("--drop-pending-updates", action="store_true")
    args = parser.parse_args(argv)
    settings = BotSettings(
        enabled=True,
        mode=BotMode.WEBHOOK,
        token="configured-token",  # noqa: S106
        webhook_base_url="https://example.invalid",
        webhook_secret_token="configured-secret",  # noqa: S106
        mini_app_base_url="https://example.invalid",
        mini_app_allowed_hosts=("example.invalid",),
    )
    settings.validate()
    if args.command == "register-commands":
        print({"commands": [cmd.command for cmd in command_definitions(settings.default_locale)]})
    else:
        print(
            {
                "command": args.command,
                "webhook_url": settings.webhook_url,
                "secret": "<redacted>",
                "token": "<redacted>",
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
