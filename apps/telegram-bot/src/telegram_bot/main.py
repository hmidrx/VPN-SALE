from __future__ import annotations

import asyncio
import signal

from telegram_bot.cli import load_settings_from_environment
from telegram_bot.config import BotMode
from telegram_bot.runtime.lifecycle import BotRuntime


async def _serve_until_stopped(runtime: BotRuntime) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    runtime.running = True
    await stop.wait()
    await runtime.shutdown()


def main() -> None:
    settings = load_settings_from_environment()
    try:
        settings.validate()
    except ValueError as exc:
        raise SystemExit(f"invalid Telegram bot configuration: {exc}") from exc
    runtime = BotRuntime(settings)
    print(runtime.health(), flush=True)
    if not settings.enabled or settings.mode == BotMode.DISABLED:
        return
    asyncio.run(_serve_until_stopped(runtime))


if __name__ == "__main__":
    main()
