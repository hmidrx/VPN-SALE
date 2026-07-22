from __future__ import annotations

from dataclasses import dataclass

from telegram_bot.application.identity import (
    AccountStatus,
    RegisterOrUpdateTelegramBotUser,
    TelegramIdentityPort,
    now_utc,
)
from telegram_bot.application.payloads import parse_start_payload
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2, DurableMemoryConversationStore
from telegram_bot.idempotency import InMemoryUpdateIdempotency
from telegram_bot.localization import t
from telegram_bot.menu import MenuRegistry, default_menu_registry
from telegram_bot.mini_app import MiniAppUrlBuilder
from telegram_bot.observability import BotMetrics
from telegram_bot.portal import (
    CustomerContext,
    CustomerPortalPort,
    InMemoryCustomerPortal,
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
        conversations: ConversationStoreV2 | None = None,
    ) -> None:
        from telegram_bot.renderer import ScreenRenderer
        from telegram_bot.screens import DashboardData, ScreenId

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
        self.conversations = conversations or DurableMemoryConversationStore()
        self.renderer = ScreenRenderer()
        self._screen_id = ScreenId
        self._dashboard_data = DashboardData

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
        locale = self._customer_locale(user)
        try:
            self.rate_limiter.check(
                command.command.lstrip("/"),
                user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
        except RateLimitExceeded:
            return self._single(t(locale, "rate_limited"), [])
        if command.command == "/start":
            return self._start(command)
        if command.command in {"/menu", "/help"}:
            return self._render(user, self._screen_id.HOME, locale, push=False)
        if command.command == "/language":
            return self._render(user, self._screen_id.LANGUAGE, locale)
        if command.command == "/privacy":
            return self._render(user, self._screen_id.PRIVACY, locale)
        if command.command == "/cancel":
            return self.cancel_for(user, locale)
        return self._render(user, self._screen_id.HELP, locale)

    def handle_callback(self, callback: IncomingCallback) -> HandlerResult:
        self.metrics.inc("callbacks_received")
        if not self.idempotency.claim(
            callback.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        locale = self.settings.default_locale
        if callback.chat_type != "private" or callback.user is None:
            return self._callback_message(t(locale, "group_ignored"), [])
        user = callback.user
        locale = self._customer_locale(user)
        try:
            self.rate_limiter.check(
                "callback",
                user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
            parsed = BotCallback.parse(callback.data)
            return self._route_callback(user, locale, parsed)
        except RateLimitExceeded:
            return self._callback_message(t(locale, "rate_limited"), self.renderer.nav_rows(locale))
        except Exception:  # noqa: BLE001 - customer-safe boundary
            return self._callback_message(
                t(locale, "error"),
                [
                    [
                        {
                            "text": "🔄 تلاش دوباره",
                            "callback_data": BotCallback(CallbackAction.RETRY).pack(),
                        },
                        {
                            "text": "🏠 منوی اصلی",
                            "callback_data": BotCallback(CallbackAction.HOME).pack(),
                        },
                    ]
                ],
            )

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback
    ) -> HandlerResult:
        from telegram_bot.screens import ScreenId

        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        routes = {
            CallbackAction.BUY_SERVICE: ScreenId.BUY,
            CallbackAction.MY_SERVICES: ScreenId.SERVICES,
            CallbackAction.WALLET: ScreenId.WALLET,
            CallbackAction.DISCOUNTS: ScreenId.DISCOUNTS,
            CallbackAction.SUPPORT: ScreenId.SUPPORT,
            CallbackAction.OPEN_EDUCATION: ScreenId.EDUCATION,
            CallbackAction.PROFILE: ScreenId.PROFILE,
            CallbackAction.SETTINGS: ScreenId.SETTINGS,
            CallbackAction.STATUS: ScreenId.STATUS,
            CallbackAction.ANNOUNCEMENTS: ScreenId.ANNOUNCEMENTS,
            CallbackAction.LANGUAGE: ScreenId.LANGUAGE,
            CallbackAction.PRIVACY: ScreenId.PRIVACY,
            CallbackAction.HELP: ScreenId.HELP,
        }
        if callback.action == CallbackAction.NAVIGATE:
            try:
                return self._render(user, ScreenId(callback.value), locale)
            except ValueError:
                return self._stale(locale)
        if callback.action == CallbackAction.BACK:
            new_state = state.back()
            self.conversations.save(key, new_state)
            return self._render(user, new_state.current_screen, locale, push=False)
        if callback.action in {CallbackAction.HOME, CallbackAction.MENU}:
            return self._render(user, ScreenId.HOME, locale, push=False)
        if callback.action in {CallbackAction.REFRESH, CallbackAction.RETRY}:
            return self._render(user, state.current_screen, locale, push=False)
        if callback.action == CallbackAction.CANCEL:
            return self.cancel_for(user, locale)
        if callback.action == CallbackAction.SET_LANGUAGE and callback.value in {"fa", "en"}:
            context = self._portal_context(user, callback.value)
            self.portal.set_language(context, callback.value)
            result = self._render(user, state.current_screen, callback.value, push=False)
            prefix = "زبان ذخیره شد.\n\n" if callback.value == "fa" else "Language saved.\n\n"
            if result.messages:
                msg = result.messages[0]
                return HandlerResult(True, False, (OutgoingMessage(prefix + msg.text, msg.rows),))
            return result
        if callback.action == CallbackAction.OPEN_WEB_APP:
            return self._callback_message(
                "🌐 نسخه وب اختیاری است و ربات بدون وب‌سایت قابل استفاده است.",
                self.renderer.nav_rows(locale),
            )
        if callback.action == CallbackAction.OPEN_SERVICE:
            service = self.portal.service(self._portal_context(user, locale), callback.value)
            if service is None:
                return self._callback_message(
                    "این سرویس پیدا نشد یا متعلق به شما نیست.", self.renderer.nav_rows(locale)
                )
            return self._callback_message(
                f"{service.plan_name}\nوضعیت: {service.status}", self.renderer.nav_rows(locale)
            )
        if callback.action in {
            CallbackAction.OPEN_SUBSCRIPTION,
            CallbackAction.RENEW,
            CallbackAction.UPGRADE,
            CallbackAction.EXTRA_TRAFFIC,
            CallbackAction.TOP_UP,
        }:
            return self._callback_message(
                "محیط TEST: عملیات نوشتن/پرداخت یا تحویل کانفیگ واقعی پیکربندی نشده است.",
                self.renderer.nav_rows(locale),
            )
        screen = routes.get(callback.action)
        if screen is None:
            return self._stale(locale)
        return self._render(user, screen, locale)

    def _start(self, command: IncomingCommand) -> HandlerResult:
        assert command.user is not None
        payload = parse_start_payload(command.argument)
        result = self.identity.register_or_update(
            RegisterOrUpdateTelegramBotUser(
                command.user.telegram_user_id,
                command.user.username,
                command.user.first_name,
                command.user.last_name,
                self.settings.default_locale,
                True,
                payload.value if payload.valid else None,
                now_utc(),
            )
        )
        if result.status not in {AccountStatus.ACTIVE, AccountStatus.PENDING}:
            return self._single(t(self.settings.default_locale, "restricted"), [])
        return self._render(
            command.user, self._screen_id.HOME, self.settings.default_locale, push=False
        )

    def _render(
        self, user: IncomingUser, screen: object, locale: str, *, push: bool = True
    ) -> HandlerResult:
        from telegram_bot.screens import DashboardData, ScreenId

        screen_id = screen if isinstance(screen, ScreenId) else ScreenId.HOME
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc()).move_to(screen_id, push=push)
        self.conversations.save(key, state)
        context = self._portal_context(user, locale)
        if screen_id == ScreenId.HOME:
            profile = self.portal.profile(context)
            services = self.portal.services(context)
            active = [s for s in services if s.status == "active"]
            nearest = min((s.expires_at for s in active if s.expires_at is not None), default=None)
            data = DashboardData(
                user.first_name or profile.display_name,
                self._safe_call(lambda: self.portal.wallet_balance(context)[0]),
                len(active),
                nearest,
                len(self.portal.tickets(context)),
            )
            rendered = self.renderer.render_home(data, locale)
        elif screen_id == ScreenId.PROFILE:
            rendered = self.renderer.info(screen_id, locale, profile=self.portal.profile(context))
        elif screen_id == ScreenId.SERVICES:
            rendered = self.renderer.info(screen_id, locale, services=self.portal.services(context))
        else:
            rendered = self.renderer.info(screen_id, locale)
        return self._callback_message(rendered.text, rendered.rows)

    def _safe_call(self, fn: object) -> int | None:
        try:
            return fn()  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            return None

    def _stale(self, locale: str) -> HandlerResult:
        return self._callback_message(
            "این دکمه قدیمی است. لطفاً منو را بروزرسانی کنید."
            if locale == "fa"
            else "This button is stale. Please refresh.",
            self.renderer.nav_rows(locale),
        )

    def _customer_locale(self, user: IncomingUser) -> str:
        return self.settings.default_locale

    def menu_rows(self, status: AccountStatus, locale: str) -> ButtonRows:
        return self.renderer.home_rows(locale)

    def nav_rows(self, locale: str) -> ButtonRows:
        return self.renderer.nav_rows(locale)

    def cancel_for(self, user: IncomingUser, locale: str) -> HandlerResult:
        self.conversations.cancel(self._conversation_key(user))
        return self._single(t(locale, "cancel"), self.renderer.nav_rows(locale))

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
