from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class BotMetrics:
    counters: Counter[str] = field(default_factory=Counter)

    def inc(self, name: str) -> None:
        self.counters[name] += 1

    def render(self) -> str:
        return (
            "\n".join(
                f"vpnsale_bot_{name}_total {count}" for name, count in sorted(self.counters.items())
            )
            + "\n"
        )


FORBIDDEN_LOG_FIELDS = {
    "telegram_id",
    "chat_id",
    "username",
    "first_name",
    "last_name",
    "token",
    "secret",
    "initData",
    "message_text",
    "raw_update",
}


def sanitize_log_fields(fields: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in fields.items() if key not in FORBIDDEN_LOG_FIELDS}
