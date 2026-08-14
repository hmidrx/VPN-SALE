from __future__ import annotations

from dataclasses import dataclass, replace

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
from telegram_bot.rate_limit import (
    InFlightCallbackDeduplicator,
    InMemoryBotRateLimiter,
    RateLimitExceeded,
    RateLimitUnavailable,
)
from telegram_bot.topup import TOPUP_PRESETS, parse_toman_amount

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
class IncomingText:
    update_id: int
    chat_type: str
    user: IncomingUser | None
    text: str


@dataclass(frozen=True)
class IncomingReceipt:
    update_id: int
    chat_type: str
    user: IncomingUser | None
    content: bytes
    content_type: str


@dataclass(frozen=True)
class OutgoingMessage:
    text: str
    rows: ButtonRows


@dataclass(frozen=True)
class HandlerResult:
    acknowledged: bool
    duplicate: bool
    messages: tuple[OutgoingMessage, ...]
    callback_notice: str | None = None
    callback_alert: bool = False


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
        self.in_flight_callbacks = InFlightCallbackDeduplicator(settings.rate_limit_secret)
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
            return HandlerResult(True, False, ())
        if command.command == "/start":
            return self._start(command)
        if command.command == "/menu":
            return self._render(user, self._screen_id.HOME, locale, push=False)
        if command.command == "/topup":
            return self._start_topup(user, locale, command.update_id)
        command_screens = {
            "/help": self._screen_id.HELP,
            "/profile": self._screen_id.PROFILE,
            "/services": self._screen_id.SERVICES,
            "/wallet": self._screen_id.WALLET,
            "/security": self._screen_id.HELP,
            "/support": self._screen_id.SUPPORT,
        }
        if command.command in command_screens:
            return self._render(user, command_screens[command.command], locale, push=False)
        if command.command == "/privacy":
            return self._render(user, self._screen_id.PRIVACY, locale)
        if command.command == "/cancel":
            return self.cancel_for(user, locale)
        return self._render(user, self._screen_id.HELP, locale)

    def handle_text(self, message: IncomingText) -> HandlerResult:
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if message.chat_type != "private" or message.user is None:
            return self._single(t("fa", "group_ignored"), [])
        state = self.conversations.get(self._conversation_key(message.user), now_utc())
        if state.conversation_kind != "manual_topup":
            return self._single(
                "برای ادامه از منوی ربات استفاده کنید.",
                [
                    [
                        {
                            "text": "🏠 منوی اصلی",
                            "callback_data": BotCallback(CallbackAction.HOME).pack(),
                        }
                    ]
                ],
            )
        if state.expected_input != "amount":
            return self._single("برای ادامه از دکمه‌های همین پیام استفاده کنید.", [])
        try:
            amount = parse_toman_amount(message.text)
        except ValueError:
            return self._single(
                "مبلغ معتبر و حداقل ۱۰۰٬۰۰۰ تومان ارسال کنید.", self._topup_presets()
            )
        self.conversations.save(self._conversation_key(message.user), state.review_topup(amount))
        return self._single(
            f"مبلغ: {amount:,} تومان\nروش: کارت‌به‌کارت\n\nمبلغ را تأیید می‌کنید؟",
            [
                [
                    {
                        "text": "تغییر مبلغ",
                        "callback_data": BotCallback(CallbackAction.TOP_UP).pack(),
                    },
                    {
                        "text": "✅ تأیید و ادامه",
                        "callback_data": BotCallback(CallbackAction.CONFIRM_TOP_UP).pack(),
                    },
                    {"text": "لغو", "callback_data": BotCallback(CallbackAction.CANCEL).pack()},
                ]
            ],
        )

    def expected_receipt_reference(self, user: IncomingUser) -> str | None:
        state = self.conversations.get(self._conversation_key(user), now_utc())
        if state.expected_input == "receipt" and state.active_manual_topup_reference:
            return state.active_manual_topup_reference
        context = self._portal_context(user, "fa")
        for request in self.portal.manual_topups(context):
            if request.status in {"AWAITING_RECEIPT", "NEEDS_RESUBMISSION"}:
                self.conversations.save(
                    self._conversation_key(user),
                    replace(
                        state,
                        conversation_kind="manual_topup",
                        expected_input="receipt",
                        active_manual_topup_reference=request.reference,
                    ),
                )
                return request.reference
        return None

    def handle_receipt(self, message: IncomingReceipt) -> HandlerResult:
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if message.chat_type != "private" or message.user is None:
            return self._single(t("fa", "group_ignored"), [])
        reference = self.expected_receipt_reference(message.user)
        if reference is None:
            return self._single("ابتدا یک درخواست کارت‌به‌کارت را انتخاب کنید.", [])
        request = self.portal.upload_manual_topup_receipt(
            self._portal_context(message.user, "fa"),
            reference,
            message.content,
            message.content_type,
            f"tg-receipt:{message.update_id}:{reference}",
        )
        state = self.conversations.get(self._conversation_key(message.user), now_utc())
        self.conversations.save(
            self._conversation_key(message.user),
            replace(
                state,
                expected_input=None,
                conversation_kind=None,
                active_manual_topup_reference=None,
            ),
        )
        return self._single(
            "فیش شما دریافت شد و در انتظار بررسی است.",
            [
                [
                    {
                        "text": "🔄 وضعیت درخواست",
                        "callback_data": BotCallback(
                            CallbackAction.SEND_RECEIPT, request.reference
                        ).pack(),
                    }
                ],
                [
                    {
                        "text": "🌐 مشاهده در مینی‌اپ",
                        "web_app_url": self.url_builder.manual_topup(request.reference),
                    }
                ],
                [
                    {
                        "text": "🏠 منوی اصلی",
                        "callback_data": BotCallback(CallbackAction.HOME).pack(),
                    }
                ],
            ],
        )

    def _topup_presets(self) -> ButtonRows:
        buttons = [
            {
                "text": f"{amount:,}",
                "callback_data": BotCallback(CallbackAction.TOP_UP, str(amount)).pack(),
            }
            for amount in TOPUP_PRESETS
        ]
        return [buttons[:2], buttons[2:4], buttons[4:]]

    def _start_topup(self, user: IncomingUser, locale: str, update_id: int) -> HandlerResult:
        _ = locale
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc()).start_topup(f"tg-topup:{update_id}")
        self.conversations.save(key, state)
        return self._single("مبلغ افزایش موجودی را به تومان ارسال کنید.", self._topup_presets())

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
        in_flight_key = self.in_flight_callbacks.claim(user.telegram_user_id, callback.data or "")
        if in_flight_key is None:
            return HandlerResult(True, True, ())
        try:
            parsed = BotCallback.parse(callback.data)
            policy = callback_policy(parsed)
            if not self._allow_callback(user.telegram_user_id, policy):
                return self._limited_callback(user.telegram_user_id, policy)
            return self._route_callback(user, locale, parsed, callback.update_id)
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
        finally:
            self.in_flight_callbacks.release(in_flight_key)

    def _allow_callback(self, telegram_user_id: int, policy: str) -> bool:
        if policy == "navigation":
            limit = self.settings.navigation_rate_limit
            window = self.settings.navigation_rate_limit_window_seconds
        elif policy == "mutation":
            limit = self.settings.mutation_rate_limit
            window = self.settings.mutation_rate_limit_window_seconds
        else:
            limit = self.settings.sensitive_rate_limit
            window = self.settings.sensitive_rate_limit_window_seconds
        try:
            self.rate_limiter.check(policy, telegram_user_id, limit, window)
        except RateLimitExceeded:
            return False
        except RateLimitUnavailable:
            # Navigation remains available if limiter infrastructure is unhealthy;
            # writes fail closed so an outage cannot weaken mutation protection.
            return policy == "navigation"
        return True

    def _limited_callback(self, telegram_user_id: int, policy: str) -> HandlerResult:
        if policy == "navigation":
            return HandlerResult(True, False, ())
        try:
            self.rate_limiter.check(
                "throttle-notice",
                telegram_user_id,
                1,
                self.settings.throttle_notice_cooldown_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return HandlerResult(True, False, ())
        return HandlerResult(True, False, (), t("fa", "rate_limited"), True)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
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

        if callback.action == CallbackAction.TOGGLE_NOTIFICATION:
            context = self._portal_context(user, locale)
            try:
                current = self.portal.notification_preferences(context)
                values = {
                    "service_expiry_enabled": current.service_expiry_enabled,
                    "low_traffic_enabled": current.low_traffic_enabled,
                    "payment_enabled": current.payment_enabled,
                    "support_reply_enabled": current.support_reply_enabled,
                    "announcements_enabled": current.announcements_enabled,
                }
                if callback.value not in values:
                    return self._stale(locale)
                prefs = self.portal.update_notification_preference(
                    context,
                    callback.value,
                    not values[callback.value],
                    f"tg-callback:{update_id}:{callback.action.value}:{callback.value}",
                )
                state = state.move_to(ScreenId.NOTIFICATIONS, push=False)
                self.conversations.save(key, state)
                rendered = self.renderer.notifications(locale, prefs)
            except Exception:  # noqa: BLE001 - customer-safe mutation failure
                try:
                    prefs = self.portal.notification_preferences(context)
                except Exception:  # noqa: BLE001
                    prefs = None
                if prefs is None:
                    rendered = self.renderer.notification_error(locale)
                else:
                    rendered = self.renderer.notifications(locale, prefs, mutation_error=True)
            return self._callback_message(rendered.text, rendered.rows)
        if callback.action == CallbackAction.TOP_UP:
            result = self._start_topup(user, locale, update_id)
            if callback.value:
                try:
                    amount = parse_toman_amount(callback.value)
                except ValueError:
                    return self._stale(locale)
                state = self.conversations.get(key, now_utc()).review_topup(amount)
                self.conversations.save(key, state)
                return self._callback_message(
                    f"مبلغ: {amount:,} تومان\nروش: کارت‌به‌کارت\n\nمبلغ را تأیید می‌کنید؟",
                    [
                        [
                            {
                                "text": "✅ تأیید و ادامه",
                                "callback_data": BotCallback(CallbackAction.CONFIRM_TOP_UP).pack(),
                            },
                            {
                                "text": "تغییر مبلغ",
                                "callback_data": BotCallback(CallbackAction.TOP_UP).pack(),
                            },
                            {
                                "text": "لغو",
                                "callback_data": BotCallback(CallbackAction.CANCEL).pack(),
                            },
                        ]
                    ],
                )
            return result
        if callback.action == CallbackAction.CONFIRM_TOP_UP:
            state = self.conversations.get(key, now_utc())
            if (
                state.conversation_kind != "manual_topup"
                or state.expected_input != "confirmation"
                or state.amount_toman is None
                or not state.idempotency_key
            ):
                return self._stale(locale)
            context = self._portal_context(user, locale)
            request = self.portal.create_manual_topup(
                context, state.amount_toman * 10, state.idempotency_key
            )
            mode = self.portal.manual_topup_destination_mode(context, request.reference)
            next_state = replace(
                state,
                expected_input="receipt",
                active_manual_topup_reference=request.reference,
            )
            self.conversations.save(key, next_state)
            status_label = {
                "AWAITING_SUPPORT": "در انتظار دریافت اطلاعات کارت",
                "AWAITING_RECEIPT": "در انتظار ارسال فیش",
            }.get(request.status, request.status)
            if mode == "DIRECT_CARD":
                guidance = "اطلاعات واریز برای درخواست شما آماده است."
                action_rows = [
                    [
                        {
                            "text": "💳 مشاهده اطلاعات واریز",
                            "web_app_url": self.url_builder.manual_topup(request.reference),
                        }
                    ]
                ]
            else:
                guidance = "برای دریافت شماره کارت، با پشتیبانی در ارتباط باشید."
                action_rows = [
                    [
                        {
                            "text": "🎫 پشتیبانی",
                            "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                        },
                        {
                            "text": "📎 ارسال فیش",
                            "callback_data": BotCallback(
                                CallbackAction.SEND_RECEIPT, request.reference
                            ).pack(),
                        },
                    ]
                ]
            return self._callback_message(
                f"مبلغ: {request.amount_toman:,} تومان\n"
                f"وضعیت: {status_label}\nشناسه: {request.reference[-8:]}\n\n{guidance}",
                [
                    *action_rows,
                    [
                        {
                            "text": "❌ لغو درخواست",
                            "callback_data": BotCallback(CallbackAction.CANCEL).pack(),
                        }
                    ],
                ],
            )
        if callback.action == CallbackAction.SEND_RECEIPT:
            state = self.conversations.get(key, now_utc())
            self.conversations.save(
                key,
                replace(
                    state,
                    conversation_kind="manual_topup",
                    expected_input="receipt",
                    active_manual_topup_reference=callback.value,
                ),
            )
            return self._callback_message(
                "تصویر فیش را ارسال کنید.", self.renderer.nav_rows(locale)
            )
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
        if callback.action == CallbackAction.SET_LANGUAGE:
            return self._stale(locale)
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
        }:
            return self._callback_message(
                "برای انجام این عملیات، سرویس را در مینی‌اپ مدیریت کنید.",
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
        elif screen_id == ScreenId.NOTIFICATIONS:
            try:
                rendered = self.renderer.notifications(
                    locale, self.portal.notification_preferences(context)
                )
            except Exception:  # noqa: BLE001 - customer-safe API failure
                rendered = self.renderer.notification_error(locale)
        elif screen_id == ScreenId.WALLET:
            rendered = self.renderer.info(
                screen_id,
                locale,
                wallet_balance=self.portal.wallet_balance(context)[0],
                transactions=self.portal.transactions(context),
            )
        else:
            rendered = self.renderer.info(screen_id, locale)
        return self._callback_message(rendered.text, rendered.rows)

    def _safe_call(self, fn: object) -> int | None:
        try:
            return fn()  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            return None

    def _stale(self, locale: str) -> HandlerResult:
        _ = locale
        return self._callback_message(
            t("fa", "stale"),
            [[{"text": "🏠 منوی اصلی", "callback_data": BotCallback(CallbackAction.HOME).pack()}]],
        )

    def _customer_locale(self, user: IncomingUser) -> str:
        _ = user
        return "fa"

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
        return CustomerContext(f"user-{user.telegram_user_id}", user.telegram_user_id, "fa")

    def _conversation_key(self, user: IncomingUser) -> str:
        return f"tg:{user.telegram_user_id}"


NAVIGATION_CALLBACKS = frozenset(
    {
        CallbackAction.NAVIGATE,
        CallbackAction.BACK,
        CallbackAction.HOME,
        CallbackAction.REFRESH,
        CallbackAction.RETRY,
        CallbackAction.MENU,
        CallbackAction.HELP,
        CallbackAction.LANGUAGE,
        CallbackAction.PRIVACY,
        CallbackAction.PROFILE,
        CallbackAction.SECURITY,
        CallbackAction.OPEN_EDUCATION,
        CallbackAction.SEARCH_GUIDES,
        CallbackAction.SHOW_FAQ,
        CallbackAction.OPEN_STATUS_PAGE,
        CallbackAction.MY_SERVICES,
        CallbackAction.OPEN_SERVICE,
        CallbackAction.OPEN_CONFIGS,
        CallbackAction.OPEN_SERVICE_GUIDE,
        CallbackAction.BUY_SERVICE,
        CallbackAction.WALLET,
        CallbackAction.SUPPORT,
        CallbackAction.STATUS,
        CallbackAction.DISCOUNTS,
        CallbackAction.ANNOUNCEMENTS,
        CallbackAction.SETTINGS,
        CallbackAction.OPEN_WEB_APP,
        CallbackAction.CANCEL,
    }
)

MUTATION_CALLBACKS = frozenset({CallbackAction.TOGGLE_NOTIFICATION})


def callback_policy(callback: BotCallback) -> str:
    if callback.action in NAVIGATION_CALLBACKS:
        return "navigation"
    if callback.action in MUTATION_CALLBACKS:
        return "mutation"
    return "sensitive"
