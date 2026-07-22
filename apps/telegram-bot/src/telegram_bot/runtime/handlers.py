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
        if command.command == "/menu":
            return self._menu(command, locale, AccountStatus.ACTIVE)
        callback_map = {
            "/profile": CallbackAction.PROFILE,
            "/services": CallbackAction.MY_SERVICES,
            "/wallet": CallbackAction.WALLET,
            "/security": CallbackAction.SECURITY,
            "/support": CallbackAction.SUPPORT,
        }
        if command.command in callback_map and command.user is not None:
            return self.handle_callback(
                IncomingCallback(
                    command.update_id + 10_000_000,
                    "cmd",
                    command.chat_type,
                    command.user,
                    BotCallback(callback_map[command.command]).pack(),
                )
            )
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


# Bot-native customer portal callbacks. These methods intentionally call a
# CustomerPortalPort instead of a database adapter so customer operations share
# the platform API/application boundary used by other clients.
from telegram_bot.callbacks import BotCallback, CallbackAction  # noqa: E402
from telegram_bot.portal import (  # noqa: E402
    CustomerContext,
    CustomerPortalPort,
    InMemoryConversationStore,
    InMemoryCustomerPortal,
    page_items,
)


@dataclass(frozen=True)
class IncomingCallback:
    update_id: int
    callback_id: str
    chat_type: str
    user: IncomingUser | None
    data: str | None


def _portal_context(user: IncomingUser, locale: str) -> CustomerContext:
    return CustomerContext(f"user-{user.telegram_user_id}", user.telegram_user_id, locale)


def _nav_rows(locale: str) -> list[list[dict[str, str]]]:
    return [
        [
            {
                "text": "بازگشت" if locale == "fa" else "Back",
                "callback_data": BotCallback(CallbackAction.MENU).pack(),
            }
        ]
    ]


def _money(amount: int, currency: str) -> str:
    return f"{amount:,} {currency}"


def _safe_date(value: object) -> str:
    if hasattr(value, "date"):
        return str(value.date())
    return "—"


def _patch_handler_class() -> None:
    old_init = BotCommandHandler.__init__

    def __init__(
        self,
        *args,
        portal: CustomerPortalPort | None = None,
        conversations: InMemoryConversationStore | None = None,
        **kwargs,
    ):  # type: ignore[no-untyped-def]
        old_init(self, *args, **kwargs)
        self.portal = portal or InMemoryCustomerPortal()
        self.conversations = conversations or InMemoryConversationStore()

    def handle_callback(self: BotCommandHandler, callback: IncomingCallback) -> HandlerResult:
        self.metrics.inc("callbacks_received")
        if not self.idempotency.claim(
            callback.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if callback.chat_type != "private" or callback.user is None:
            return self._single_callback(t(self.settings.default_locale, "group_ignored"), [])
        locale = normalize_locale(
            callback.user.language_code,
            self.settings.supported_locales,
            self.settings.default_locale,
        )
        try:
            self.rate_limiter.check(
                "callback",
                callback.user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
            parsed = BotCallback.parse(callback.data)
        except (RateLimitExceeded, ValueError):
            return self._single_callback(t(locale, "error"), _nav_rows(locale))
        context = _portal_context(callback.user, locale)
        action = parsed.action
        if action == CallbackAction.MENU:
            return self._single_callback(
                t(locale, "menu_title"), self._menu_rows(AccountStatus.ACTIVE, locale)
            )
        if action == CallbackAction.PROFILE:
            profile = self.portal.profile(context)
            linked = "فعال" if profile.telegram_linked else "غیرفعال"
            text = (
                f"👤 حساب کاربری\nنام: {profile.display_name}\n"
                f"اتصال تلگرام: {linked}\nوضعیت: {profile.account_state.value}\n"
                f"ایجاد: {_safe_date(profile.created_at)}\nزبان: {profile.language}"
            )
            return self._single_callback(text, _nav_rows(locale))
        if action == CallbackAction.MY_SERVICES:
            services = self.portal.services(context)
            page = int(parsed.value or 0)
            shown, more = page_items(services, page, 4)
            text = "📦 سرویس‌های من\n" + "\n".join(
                f"• {s.plan_name} — {s.status} — انقضا: {_safe_date(s.expires_at)} "
                f"— {s.remaining_gb}/{s.total_gb}GB — {s.location}"
                for s in shown
            )
            rows = [
                [
                    {
                        "text": s.plan_name,
                        "callback_data": BotCallback(CallbackAction.OPEN_SERVICE, s.ref).pack(),
                    }
                ]
                for s in shown
            ]
            if more:
                rows.append(
                    [
                        {
                            "text": "بعدی",
                            "callback_data": BotCallback(
                                CallbackAction.MY_SERVICES, str(page + 1)
                            ).pack(),
                        }
                    ]
                )
            rows += _nav_rows(locale)
            return self._single_callback(text, rows)
        if action == CallbackAction.OPEN_SERVICE:
            service = self.portal.service(context, parsed.value)
            if service is None:
                return self._single_callback(
                    "این سرویس پیدا نشد یا متعلق به شما نیست.", _nav_rows(locale)
                )
            rows = [
                [
                    {
                        "text": "نمایش اشتراک",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_SUBSCRIPTION, service.ref
                        ).pack(),
                    }
                ],
                [
                    {
                        "text": "آموزش اتصال",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_SERVICE_GUIDE, service.ref
                        ).pack(),
                    }
                ],
                [
                    {
                        "text": "تمدید",
                        "callback_data": BotCallback(CallbackAction.RENEW, service.ref).pack(),
                    }
                ],
                [
                    {
                        "text": "ارتقا",
                        "callback_data": BotCallback(CallbackAction.UPGRADE, service.ref).pack(),
                    }
                ],
                [
                    {
                        "text": "خرید ترافیک اضافه",
                        "callback_data": BotCallback(
                            CallbackAction.EXTRA_TRAFFIC, service.ref
                        ).pack(),
                    }
                ],
            ] + _nav_rows(locale)
            detail = (
                f"{service.plan_name}\nوضعیت: {service.status}\n"
                f"حجم: {service.remaining_gb}/{service.total_gb}GB\n"
                f"مکان: {service.location}"
            )
            return self._single_callback(detail, rows)
        if action in {
            CallbackAction.OPEN_SUBSCRIPTION,
            CallbackAction.RENEW,
            CallbackAction.UPGRADE,
            CallbackAction.EXTRA_TRAFFIC,
            CallbackAction.BUY_SERVICE,
        }:
            return self._single_callback(
                (
                    "محیط TEST: عملیات نوشتن/پرداخت یا تحویل کانفیگ واقعی "
                    "پیکربندی نشده است و موفقیت ساختگی نمایش داده نمی‌شود."
                ),
                _nav_rows(locale),
            )
        if action == CallbackAction.WALLET:
            balance, currency = self.portal.wallet_balance(context)
            txs, more = page_items(self.portal.transactions(context), int(parsed.value or 0), 5)
            text = (
                "💰 کیف پول\nموجودی: "
                + _money(balance, currency)
                + "\n"
                + "\n".join(
                    f"• {tx.transaction_type} {tx.status} {_money(tx.amount_minor, tx.currency)}"
                    for tx in txs
                )
            )
            rows = [
                [
                    {
                        "text": "افزایش موجودی",
                        "callback_data": BotCallback(CallbackAction.TOP_UP).pack(),
                    }
                ]
            ] + _nav_rows(locale)
            return self._single_callback(text, rows)
        if action == CallbackAction.TOP_UP:
            return self._single_callback(
                (
                    "روش پرداخت برای محیط TEST پیکربندی نشده است؛ "
                    "اعتبار کیف پول تکراری یا ساختگی ثبت نمی‌شود."
                ),
                _nav_rows(locale),
            )
        if action == CallbackAction.SECURITY:
            sessions = self.portal.sessions(context)
            rows = [
                [
                    {
                        "text": f"لغو {s.label}",
                        "callback_data": BotCallback(CallbackAction.CONFIRM_REVOKE, s.ref).pack(),
                    }
                ]
                for s in sessions
                if not s.current
            ] + _nav_rows(locale)
            return self._single_callback(
                "🔐 نشست‌ها\n"
                + "\n".join(
                    f"• {s.label} — آخرین مشاهده {_safe_date(s.last_seen_at)}" for s in sessions
                ),
                rows,
            )
        if action == CallbackAction.CONFIRM_REVOKE:
            self.portal.revoke_session(context, parsed.value)
            return self._single_callback(
                "نشست انتخاب‌شده در صورت تعلق به حساب شما لغو شد.", _nav_rows(locale)
            )
        if action == CallbackAction.SUPPORT:
            return self._single_callback(
                (
                    "🎫 پشتیبانی\nبرای ساخت تیکت: دسته‌بندی، موضوع و پیام "
                    "دریافت می‌شود. /cancel در هر مرحله فعال است."
                ),
                _nav_rows(locale),
            )
        if action == CallbackAction.OPEN_EDUCATION:
            return self._single_callback(
                (
                    "📚 آموزش اتصال\nAndroid، iOS، Windows، macOS و Linux: "
                    "راهنماهای کوتاه داخل ربات ارائه می‌شوند. از اطلاعات سرویس خود "
                    "فقط پس از درخواست صریح استفاده کنید."
                ),
                _nav_rows(locale),
            )
        if action == CallbackAction.STATUS:
            return self._single_callback(
                (
                    "📡 وضعیت سرویس\nAPI در دسترس است. "
                    "تعمیرات برنامه‌ریزی‌شده‌ای برای مشتری نمایش داده نشده است."
                ),
                _nav_rows(locale),
            )
        if action == CallbackAction.LANGUAGE:
            rows = [
                [
                    {
                        "text": "فارسی",
                        "callback_data": BotCallback(CallbackAction.SET_LANGUAGE, "fa").pack(),
                    },
                    {
                        "text": "English",
                        "callback_data": BotCallback(CallbackAction.SET_LANGUAGE, "en").pack(),
                    },
                ]
            ] + _nav_rows(locale)
            return self._single_callback("زبان را انتخاب کنید / Choose language", rows)
        if action == CallbackAction.SET_LANGUAGE and parsed.value in {"fa", "en"}:
            self.portal.set_language(context, parsed.value)
            return self._single_callback(
                "زبان ذخیره شد." if parsed.value == "fa" else "Language saved.",
                self._menu_rows(AccountStatus.ACTIVE, parsed.value),
            )
        if action == CallbackAction.PRIVACY:
            return self._single_callback(t(locale, "privacy"), _nav_rows(locale))
        return self._single_callback(t(locale, "help"), _nav_rows(locale))

    def _single_callback(
        self: BotCommandHandler, text: str, rows: list[list[dict[str, str]]]
    ) -> HandlerResult:
        self.metrics.inc("callbacks_processed")
        return HandlerResult(True, False, (OutgoingMessage(text, rows),))

    BotCommandHandler.__init__ = __init__  # type: ignore[method-assign]
    BotCommandHandler.handle_callback = handle_callback  # type: ignore[attr-defined]
    BotCommandHandler._single_callback = _single_callback  # type: ignore[attr-defined]


_patch_handler_class()
