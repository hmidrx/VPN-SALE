from __future__ import annotations

from dataclasses import dataclass

from telegram_bot.localization import t

COMMANDS = ("start", "menu", "help", "profile", "security", "language", "privacy", "cancel")


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
        "security": t(locale, "security"),
        "language": t(locale, "language_button"),
        "privacy": t(locale, "privacy_button"),
        "cancel": t(locale, "cancel"),
    }
    return tuple(BotCommandDefinition(command, labels[command]) for command in COMMANDS)
