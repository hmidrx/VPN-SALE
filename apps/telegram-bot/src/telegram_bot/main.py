from __future__ import annotations

from telegram_bot.config import BotMode, BotSettings
from telegram_bot.runtime.lifecycle import BotRuntime


def main() -> None:
    runtime = BotRuntime(BotSettings(enabled=False, mode=BotMode.DISABLED))
    print(runtime.health())


if __name__ == "__main__":
    main()
