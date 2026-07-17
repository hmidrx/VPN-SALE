from __future__ import annotations

from dataclasses import dataclass

from telegram_bot.application.identity import (
    AccountStatus,
    RegisterOrUpdateTelegramBotUser,
    TelegramIdentityPort,
    now_utc,
)
from telegram_bot.application.payloads import parse_start_payload
from telegram_bot.config import BotSettings
from telegram_bot.idempotency import InMemoryUpdateIdempotency
from telegram_bot.localization import normalize_locale, t
from telegram_bot.menu import MenuRegistry, as_button_rows, default_menu_registry
from telegram_bot.mini_app import MiniAppUrlBuilder
from telegram_bot.observability import BotMetrics
from telegram_bot.rate_limit import InMemoryBotRateLimiter, RateLimitExceeded


@dataclass(frozen=True)
class IncomingUser:
    telegram_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None


@dataclass(frozen=True)
class IncomingCommand:
    update_id: int
    chat_type: str
    user: IncomingUser | None
    command: str
    argument: str | None = None


@dataclass(frozen=True)
class OutgoingMessage:
    text: str
    rows: list[list[dict[str, str]]]


@dataclass(frozen=True)
class HandlerResult:
    acknowledged: bool
    duplicate: bool
    messages: tuple[OutgoingMessage, ...]


class BotCommandHandler:
    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        idempotency: InMemoryUpdateIdempotency | None = None,
        rate_limiter: InMemoryBotRateLimiter | None = None,
        registry: MenuRegistry | None = None,
        metrics: BotMetrics | None = None,
    ) -> None:
        self.settings = settings
        self.identity = identity
        self.idempotency = idempotency or InMemoryUpdateIdempotency()
        self.rate_limiter = rate_limiter or InMemoryBotRateLimiter(settings.rate_limit_secret)
        self.registry = registry or default_menu_registry()
        self.metrics = metrics or BotMetrics()
        self.url_builder = MiniAppUrlBuilder(
            settings.mini_app_base_url, settings.mini_app_allowed_hosts, settings.production_like
        )

    def handle_command(self, command: IncomingCommand) -> HandlerResult:
        self.metrics.inc("updates_received")
        if not self.idempotency.claim(
            command.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            self.metrics.inc("duplicate_updates")
            return HandlerResult(True, True, ())
        if command.chat_type != "private" or command.user is None:
            return self._single(command, t(self.settings.default_locale, "group_ignored"), [])
        locale = normalize_locale(
            command.user.language_code,
            self.settings.supported_locales,
            self.settings.default_locale,
        )
        try:
            self.rate_limiter.check(
                command.command.lstrip("/"),
                command.user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
        except RateLimitExceeded:
            self.metrics.inc("rate_limits")
            return self._single(command, t(locale, "rate_limited"), [])
        if command.command == "/start":
            return self._start(command, locale)
        if command.command in {"/menu", "/profile", "/security"}:
            return self._menu(command, locale, AccountStatus.ACTIVE)
        if command.command == "/help":
            return self._single(command, t(locale, "help"), [])
        if command.command == "/language":
            return self._single(
                command, t(locale, "language"), self._menu_rows(AccountStatus.ACTIVE, locale)
            )
        if command.command == "/privacy":
            return self._single(command, t(locale, "privacy"), [])
        if command.command == "/cancel":
            return self._single(command, t(locale, "cancel"), [])
        return self._single(command, t(locale, "help"), [])

    def _start(self, command: IncomingCommand, locale: str) -> HandlerResult:
        assert command.user is not None
        payload = parse_start_payload(command.argument)
        result = self.identity.register_or_update(
            RegisterOrUpdateTelegramBotUser(
                telegram_user_id=command.user.telegram_user_id,
                username=command.user.username,
                first_name=command.user.first_name,
                last_name=command.user.last_name,
                language_code=command.user.language_code,
                bot_started=True,
                sanitized_start_payload=payload.value if payload.valid else None,
                seen_at=now_utc(),
            )
        )
        resolved_locale = normalize_locale(
            result.locale or command.user.language_code,
            self.settings.supported_locales,
            self.settings.default_locale,
        )
        if result.status not in {AccountStatus.ACTIVE, AccountStatus.PENDING}:
            return self._single(command, t(resolved_locale, "restricted"), [])
        welcome = (
            t(resolved_locale, "welcome_new" if result.created else "welcome_returning")
            + "\n\n"
            + t(resolved_locale, "menu_title")
        )
        self.metrics.inc("updates_processed")
        self.metrics.inc("command_start")
        return HandlerResult(
            True,
            False,
            (OutgoingMessage(welcome, self._menu_rows(result.status, resolved_locale)),),
        )

    def _menu(self, command: IncomingCommand, locale: str, status: AccountStatus) -> HandlerResult:
        return self._single(command, t(locale, "menu_title"), self._menu_rows(status, locale))

    def _single(
        self, _command: IncomingCommand, text: str, rows: list[list[dict[str, str]]]
    ) -> HandlerResult:
        self.metrics.inc("updates_processed")
        return HandlerResult(True, False, (OutgoingMessage(text, rows),))

    def _menu_rows(self, status: AccountStatus, locale: str) -> list[list[dict[str, str]]]:
        return as_button_rows(self.registry, status, locale, self.url_builder)
