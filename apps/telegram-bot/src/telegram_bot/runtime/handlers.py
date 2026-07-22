from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from telegram_bot.application.identity import (
    AccountStatus,
    RegisterOrUpdateTelegramBotUser,
    TelegramIdentityPort,
    now_utc,
)
from telegram_bot.application.payloads import parse_start_payload
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.idempotency import InMemoryUpdateIdempotency
from telegram_bot.localization import normalize_locale, t
from telegram_bot.menu import MenuRegistry, as_button_rows, default_menu_registry
from telegram_bot.mini_app import MiniAppUrlBuilder
from telegram_bot.observability import BotMetrics
from telegram_bot.portal import (
    CustomerContext,
    CustomerPortalPort,
    InMemoryConversationStore,
    InMemoryCustomerPortal,
    ServiceSummary,
    WalletTransaction,
    page_items,
)
from telegram_bot.rate_limit import InMemoryBotRateLimiter, RateLimitExceeded

ButtonRows = list[list[dict[str, str]]]


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
class IncomingCallback:
    update_id: int
    callback_id: str
    chat_type: str
    user: IncomingUser | None
    data: str | None


@dataclass(frozen=True)
class OutgoingMessage:
    text: str
    rows: ButtonRows


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
        portal: CustomerPortalPort | None = None,
        conversations: InMemoryConversationStore | None = None,
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
        self.portal = portal or InMemoryCustomerPortal()
        self.conversations = conversations or InMemoryConversationStore()

    def handle_command(self, command: IncomingCommand) -> HandlerResult:
        self.metrics.inc("updates_received")
        if not self.idempotency.claim(
            command.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            self.metrics.inc("duplicate_updates")
            return HandlerResult(True, True, ())
        if command.chat_type != "private" or command.user is None:
            return self._single(t(self.settings.default_locale, "group_ignored"), [])
        user = command.user
        locale = normalize_locale(
            user.language_code,
            self.settings.supported_locales,
            self.settings.default_locale,
        )
        try:
            self.rate_limiter.check(
                command.command.lstrip("/"),
                user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
        except RateLimitExceeded:
            self.metrics.inc("rate_limits")
            return self._single(t(locale, "rate_limited"), [])
        if command.command == "/start":
            return self._start(command, locale)
        if command.command == "/menu":
            return self._menu(locale, AccountStatus.ACTIVE)
        callback_map: dict[str, CallbackAction] = {
            "/profile": CallbackAction.PROFILE,
            "/services": CallbackAction.MY_SERVICES,
            "/wallet": CallbackAction.WALLET,
            "/security": CallbackAction.SECURITY,
            "/support": CallbackAction.SUPPORT,
        }
        action = callback_map.get(command.command)
        if action is not None:
            return self._handle_action(user, locale, BotCallback(action))
        if command.command == "/help":
            return self._single(t(locale, "help"), [])
        if command.command == "/language":
            return self._single(t(locale, "language"), self.menu_rows(AccountStatus.ACTIVE, locale))
        if command.command == "/privacy":
            return self._single(t(locale, "privacy"), [])
        if command.command == "/cancel":
            return self.cancel_for(user, locale)
        return self._single(t(locale, "help"), [])

    def handle_callback(self, callback: IncomingCallback) -> HandlerResult:
        self.metrics.inc("callbacks_received")
        if not self.idempotency.claim(
            callback.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if callback.chat_type != "private" or callback.user is None:
            return self._callback_message(t(self.settings.default_locale, "group_ignored"), [])
        user = callback.user
        locale = normalize_locale(
            user.language_code,
            self.settings.supported_locales,
            self.settings.default_locale,
        )
        try:
            self.rate_limiter.check(
                "callback",
                user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
            parsed = BotCallback.parse(callback.data)
        except (RateLimitExceeded, ValueError):
            return self._callback_message(t(locale, "error"), self.nav_rows(locale))
        return self._handle_action(user, locale, parsed)

    def menu_rows(self, status: AccountStatus, locale: str) -> ButtonRows:
        return as_button_rows(self.registry, status, locale, self.url_builder)

    def nav_rows(self, locale: str) -> ButtonRows:
        return [
            [
                {
                    "text": "بازگشت" if locale == "fa" else "Back",
                    "callback_data": BotCallback(CallbackAction.MENU).pack(),
                }
            ]
        ]

    def cancel_for(self, user: IncomingUser, locale: str) -> HandlerResult:
        self.conversations.cancel(self._conversation_key(user))
        return self._single(t(locale, "cancel"), self.nav_rows(locale))

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
            return self._single(t(resolved_locale, "restricted"), [])
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
            (OutgoingMessage(welcome, self.menu_rows(result.status, resolved_locale)),),
        )

    def _menu(self, locale: str, status: AccountStatus) -> HandlerResult:
        return self._single(t(locale, "menu_title"), self.menu_rows(status, locale))

    def _handle_action(
        self, user: IncomingUser, locale: str, callback: BotCallback
    ) -> HandlerResult:
        context = self._portal_context(user, locale)
        action = callback.action
        if action == CallbackAction.MENU:
            return self._callback_message(
                t(locale, "menu_title"), self.menu_rows(AccountStatus.ACTIVE, locale)
            )
        if action == CallbackAction.PROFILE:
            return self._profile(context, locale)
        if action == CallbackAction.MY_SERVICES:
            return self._services(context, callback.value, locale)
        if action == CallbackAction.OPEN_SERVICE:
            return self._service_detail(context, callback.value, locale)
        if action in {
            CallbackAction.OPEN_SUBSCRIPTION,
            CallbackAction.RENEW,
            CallbackAction.UPGRADE,
            CallbackAction.EXTRA_TRAFFIC,
            CallbackAction.BUY_SERVICE,
        }:
            return self._write_disabled(locale)
        if action == CallbackAction.WALLET:
            return self._wallet(context, callback.value, locale)
        if action == CallbackAction.TOP_UP:
            return self._callback_message(
                (
                    "روش پرداخت برای محیط TEST پیکربندی نشده است؛ "
                    "اعتبار کیف پول تکراری یا ساختگی ثبت نمی‌شود."
                ),
                self.nav_rows(locale),
            )
        if action == CallbackAction.SECURITY:
            return self._security(context, locale)
        if action == CallbackAction.CONFIRM_REVOKE:
            self.portal.revoke_session(context, callback.value)
            return self._callback_message(
                "نشست انتخاب‌شده در صورت تعلق به حساب شما لغو شد.", self.nav_rows(locale)
            )
        if action == CallbackAction.SUPPORT:
            return self._support(locale)
        if action == CallbackAction.OPEN_EDUCATION:
            return self._education(locale)
        if action == CallbackAction.STATUS:
            return self._status(locale)
        if action == CallbackAction.LANGUAGE:
            return self._language(locale)
        if action == CallbackAction.SET_LANGUAGE and callback.value in {"fa", "en"}:
            self.portal.set_language(context, callback.value)
            return self._callback_message(
                "زبان ذخیره شد." if callback.value == "fa" else "Language saved.",
                self.menu_rows(AccountStatus.ACTIVE, callback.value),
            )
        if action == CallbackAction.CANCEL:
            return self.cancel_for(user, locale)
        if action == CallbackAction.PRIVACY:
            return self._callback_message(t(locale, "privacy"), self.nav_rows(locale))
        return self._callback_message(t(locale, "help"), self.nav_rows(locale))

    def _profile(self, context: CustomerContext, locale: str) -> HandlerResult:
        profile = self.portal.profile(context)
        linked = "فعال" if profile.telegram_linked else "غیرفعال"
        text = (
            f"👤 حساب کاربری\nنام: {profile.display_name}\n"
            f"اتصال تلگرام: {linked}\nوضعیت: {profile.account_state.value}\n"
            f"ایجاد: {self._safe_date(profile.created_at)}\nزبان: {profile.language}"
        )
        return self._callback_message(text, self.nav_rows(locale))

    def _services(self, context: CustomerContext, value: str, locale: str) -> HandlerResult:
        services = self.portal.services(context)
        page = self._parse_page(value)
        shown, more = page_items(services, page, 4)
        text = "📦 سرویس‌های من\n" + "\n".join(
            self._format_service_row(service) for service in shown
        )
        rows: ButtonRows = [
            [
                {
                    "text": service.plan_name,
                    "callback_data": BotCallback(CallbackAction.OPEN_SERVICE, service.ref).pack(),
                }
            ]
            for service in shown
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
        rows.extend(self.nav_rows(locale))
        return self._callback_message(text, rows)

    def _service_detail(
        self, context: CustomerContext, service_ref: str, locale: str
    ) -> HandlerResult:
        service = self.portal.service(context, service_ref)
        if service is None:
            return self._callback_message(
                "این سرویس پیدا نشد یا متعلق به شما نیست.", self.nav_rows(locale)
            )
        rows: ButtonRows = [
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
                    "callback_data": BotCallback(CallbackAction.EXTRA_TRAFFIC, service.ref).pack(),
                }
            ],
        ]
        rows.extend(self.nav_rows(locale))
        detail = (
            f"{service.plan_name}\nوضعیت: {service.status}\n"
            f"حجم: {service.remaining_gb}/{service.total_gb}GB\nمکان: {service.location}"
        )
        return self._callback_message(detail, rows)

    def _write_disabled(self, locale: str) -> HandlerResult:
        return self._callback_message(
            (
                "محیط TEST: عملیات نوشتن/پرداخت یا تحویل کانفیگ واقعی "
                "پیکربندی نشده است و موفقیت ساختگی نمایش داده نمی‌شود."
            ),
            self.nav_rows(locale),
        )

    def _wallet(self, context: CustomerContext, value: str, locale: str) -> HandlerResult:
        balance, currency = self.portal.wallet_balance(context)
        transactions = self.portal.transactions(context)
        txs, _more = page_items(transactions, self._parse_page(value), 5)
        text = (
            "💰 کیف پول\nموجودی: "
            + self._money(balance, currency)
            + "\n"
            + "\n".join(self._format_transaction(tx) for tx in txs)
        )
        rows: ButtonRows = [
            [{"text": "افزایش موجودی", "callback_data": BotCallback(CallbackAction.TOP_UP).pack()}]
        ]
        rows.extend(self.nav_rows(locale))
        return self._callback_message(text, rows)

    def _security(self, context: CustomerContext, locale: str) -> HandlerResult:
        sessions = self.portal.sessions(context)
        rows: ButtonRows = [
            [
                {
                    "text": f"لغو {session.label}",
                    "callback_data": BotCallback(CallbackAction.CONFIRM_REVOKE, session.ref).pack(),
                }
            ]
            for session in sessions
            if not session.current
        ]
        rows.extend(self.nav_rows(locale))
        text = "🔐 نشست‌ها\n" + "\n".join(
            f"• {session.label} — آخرین مشاهده {self._safe_date(session.last_seen_at)}"
            for session in sessions
        )
        return self._callback_message(text, rows)

    def _support(self, locale: str) -> HandlerResult:
        return self._callback_message(
            (
                "🎫 پشتیبانی\nبرای ساخت تیکت: دسته‌بندی، موضوع و پیام "
                "دریافت می‌شود. /cancel در هر مرحله فعال است."
            ),
            self.nav_rows(locale),
        )

    def _education(self, locale: str) -> HandlerResult:
        return self._callback_message(
            (
                "📚 آموزش اتصال\nAndroid، iOS، Windows، macOS و Linux: "
                "راهنماهای کوتاه داخل ربات ارائه می‌شوند. از اطلاعات سرویس خود "
                "فقط پس از درخواست صریح استفاده کنید."
            ),
            self.nav_rows(locale),
        )

    def _status(self, locale: str) -> HandlerResult:
        return self._callback_message(
            (
                "📡 وضعیت سرویس\nAPI در دسترس است. "
                "تعمیرات برنامه‌ریزی‌شده‌ای برای مشتری نمایش داده نشده است."
            ),
            self.nav_rows(locale),
        )

    def _language(self, locale: str) -> HandlerResult:
        rows: ButtonRows = [
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
        ]
        rows.extend(self.nav_rows(locale))
        return self._callback_message("زبان را انتخاب کنید / Choose language", rows)

    def _single(self, text: str, rows: ButtonRows) -> HandlerResult:
        self.metrics.inc("updates_processed")
        return HandlerResult(True, False, (OutgoingMessage(text, rows),))

    def _callback_message(self, text: str, rows: ButtonRows) -> HandlerResult:
        self.metrics.inc("callbacks_processed")
        return HandlerResult(True, False, (OutgoingMessage(text, rows),))

    def _portal_context(self, user: IncomingUser, locale: str) -> CustomerContext:
        return CustomerContext(f"user-{user.telegram_user_id}", user.telegram_user_id, locale)

    def _conversation_key(self, user: IncomingUser) -> str:
        return f"tg:{user.telegram_user_id}"

    def _parse_page(self, value: str) -> int:
        if not value.isdecimal():
            return 0
        return max(0, int(value))

    def _format_service_row(self, service: ServiceSummary) -> str:
        return (
            f"• {service.plan_name} — {service.status} — "
            f"انقضا: {self._safe_date(service.expires_at)} — "
            f"{service.remaining_gb}/{service.total_gb}GB — {service.location}"
        )

    def _format_transaction(self, transaction: WalletTransaction) -> str:
        return (
            f"• {transaction.transaction_type} {transaction.status} "
            f"{self._money(transaction.amount_minor, transaction.currency)}"
        )

    def _money(self, amount: int, currency: str) -> str:
        return f"{amount:,} {currency}"

    def _safe_date(self, value: datetime | None) -> str:
        if value is None:
            return "—"
        return str(value.date())
