from __future__ import annotations

from dataclasses import dataclass

from telegram_bot.localization import t

COMMANDS = (
    "start",
    "menu",
    "help",
    "profile",
    "services",
    "wallet",
    "security",
    "support",
    "privacy",
    "cancel",
)


@dataclass(frozen=True)
class BotCommandDefinition:
    command: str
    description: str


def command_definitions(locale: str = "fa") -> tuple[BotCommandDefinition, ...]:
    labels = {
        "start": t(locale, "open_app"),
        "menu": t(locale, "refresh"),
        "help": t(locale, "help_button"),
        "profile": t(locale, "profile"),
        "services": t(locale, "my_services"),
        "wallet": t(locale, "wallet"),
        "support": t(locale, "support"),
        "security": t(locale, "security"),
        "privacy": t(locale, "privacy_button"),
        "cancel": t(locale, "cancel"),
    }
    return tuple(BotCommandDefinition(command, labels[command]) for command in COMMANDS)
