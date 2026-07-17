from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock


class AccountStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    DEACTIVATED = "DEACTIVATED"


@dataclass(frozen=True)
class RegisterOrUpdateTelegramBotUser:
    telegram_user_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    bot_started: bool
    sanitized_start_payload: str | None
    seen_at: datetime


@dataclass(frozen=True)
class TelegramIdentityResult:
    user_id: str
    status: AccountStatus
    created: bool
    locale: str | None


class TelegramIdentityPort:
    def register_or_update(
        self, command: RegisterOrUpdateTelegramBotUser
    ) -> TelegramIdentityResult: ...
    def mark_bot_blocked(self, telegram_user_id: int) -> None: ...


class InMemoryTelegramIdentityService(TelegramIdentityPort):
    def __init__(self) -> None:
        self._records: dict[int, TelegramIdentityResult] = {}
        self._blocked: set[int] = set()
        self.audit_events = 0
        self._lock = Lock()

    def register_or_update(
        self, command: RegisterOrUpdateTelegramBotUser
    ) -> TelegramIdentityResult:
        with self._lock:
            existing = self._records.get(command.telegram_user_id)
            created = existing is None
            result = existing or TelegramIdentityResult(
                user_id=f"user-{command.telegram_user_id}",
                status=AccountStatus.ACTIVE,
                created=True,
                locale=command.language_code,
            )
            result = TelegramIdentityResult(
                result.user_id, result.status, created, command.language_code
            )
            self._records[command.telegram_user_id] = result
            self._blocked.discard(command.telegram_user_id)
            self.audit_events += 1
            return result

    def mark_bot_blocked(self, telegram_user_id: int) -> None:
        with self._lock:
            self._blocked.add(telegram_user_id)


def now_utc() -> datetime:
    return datetime.now(UTC)
