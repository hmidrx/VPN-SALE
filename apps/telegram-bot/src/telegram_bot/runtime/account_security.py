"""Native account-session management layered on the secure delivery bot runtime."""

from __future__ import annotations

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.localization import t
from telegram_bot.portal import CustomerPortalPort, SessionSummary
from telegram_bot.rate_limit import RateLimitExceeded, RateLimitUnavailable
from telegram_bot.runtime.handlers import (
    HandlerResult,
    IncomingCommand,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.runtime.subscription_delivery import (
    SecureDeliveryBotCommandHandler,
    SecureDeliveryTelegramPollingRuntime,
)
from telegram_bot.screens import ScreenId, safe_date, safe_text
from telegram_bot.transport.polling import TelegramTransport


class AccountSecurityBotCommandHandler(SecureDeliveryBotCommandHandler):
    """Manage real customer web sessions without exposing database session identifiers."""

    @staticmethod
    def _button_label(value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        return (cleaned[:24] + "…") if len(cleaned) > 24 else (cleaned or "نشست وب")

    def _security_view(
        self, user: IncomingUser, locale: str, *, notice: str | None = None
    ) -> tuple[str, list[list[dict[str, str]]]]:
        context = self._portal_context(user, locale)
        try:
            sessions = self.portal.sessions(context)
        except Exception:  # noqa: BLE001 - customer-safe private API boundary
            return (
                "⚠️ دریافت نشست‌های فعال حساب ممکن نشد.\nچند لحظه دیگر دوباره تلاش کنید.",
                [
                    [
                        {
                            "text": "🔄 تلاش دوباره",
                            "callback_data": BotCallback(CallbackAction.SECURITY).pack(),
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
        lines = ["🔐 امنیت حساب", "", "نشست‌های فعال نسخه وب:"]
        if notice:
            lines = [notice, "", *lines]
        rows: list[list[dict[str, str]]] = []
        if not sessions:
            lines.extend(["", "نشست فعال وبی برای این حساب پیدا نشد."])
        for session in sessions[:20]:
            suffix = " — نشست فعلی" if session.current else ""
            lines.append(
                f"• {safe_text(session.label)} — آخرین فعالیت: {safe_date(session.last_seen_at)}{suffix}"
            )
            if not session.current:
                rows.append(
                    [
                        {
                            "text": f"🚪 خروج از {self._button_label(session.label)}",
                            "callback_data": BotCallback(
                                CallbackAction.REVOKE_SESSION, session.ref
                            ).pack(),
                        }
                    ]
                )
        lines.extend(
            [
                "",
                "ربات تلگرام از نشست وب استفاده نمی‌کند؛ بستن نشست‌های وب باعث خروج ربات نمی‌شود.",
            ]
        )
        rows.extend(
            [
                [
                    {
                        "text": "👤 حساب من",
                        "callback_data": BotCallback(CallbackAction.PROFILE).pack(),
                    },
                    {
                        "text": "🏠 منوی اصلی",
                        "callback_data": BotCallback(CallbackAction.HOME).pack(),
                    },
                ]
            ]
        )
        return "\n".join(lines), rows

    def handle_command(self, command: IncomingCommand) -> HandlerResult:
        if command.command != "/security":
            return super().handle_command(command)
        self.metrics.inc("updates_received")
        if not self.idempotency.claim(
            command.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            self.metrics.inc("duplicate_updates")
            return HandlerResult(True, True, ())
        if command.chat_type != "private" or command.user is None:
            return self._single(t("fa", "group_ignored"), [])
        user = command.user
        try:
            self.rate_limiter.check(
                "security",
                user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return HandlerResult(True, False, ())
        text, rows = self._security_view(user, "fa")
        return self._single(text, rows)

    def _render(
        self, user: IncomingUser, screen: object, locale: str, *, push: bool = True
    ) -> HandlerResult:
        result = super()._render(user, screen, locale, push=push)
        screen_id = screen if isinstance(screen, ScreenId) else ScreenId.HOME
        if screen_id != ScreenId.PROFILE or len(result.messages) != 1:
            return result
        message = result.messages[0]
        security_row = [
            {
                "text": "🔐 امنیت حساب و نشست‌ها",
                "callback_data": BotCallback(CallbackAction.SECURITY).pack(),
            }
        ]
        return HandlerResult(
            result.acknowledged,
            result.duplicate,
            (OutgoingMessage(message.text, [security_row, *message.rows]),),
            result.callback_notice,
            result.callback_alert,
        )

    @staticmethod
    def _find_session(sessions: list[SessionSummary], reference: str) -> SessionSummary | None:
        return next((item for item in sessions if item.ref == reference), None)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        context = self._portal_context(user, locale)
        if callback.action == CallbackAction.SECURITY:
            text, rows = self._security_view(user, locale)
            return self._callback_message(text, rows)

        if callback.action == CallbackAction.REVOKE_SESSION:
            if not callback.value:
                return self._stale(locale)
            try:
                session = self._find_session(self.portal.sessions(context), callback.value)
            except Exception:  # noqa: BLE001 - customer-safe private API boundary
                session = None
            if session is None or session.current:
                return self._stale(locale)
            return self._callback_message(
                "با این کار نشست انتخاب‌شده از نسخه وب خارج می‌شود.\n\n"
                f"نشست: {safe_text(session.label)}\n"
                "آیا مطمئن هستید؟",
                [
                    [
                        {
                            "text": "✅ بله، خارج شود",
                            "callback_data": BotCallback(
                                CallbackAction.CONFIRM_REVOKE, callback.value
                            ).pack(),
                        },
                        {
                            "text": "◀️ انصراف",
                            "callback_data": BotCallback(CallbackAction.SECURITY).pack(),
                        },
                    ]
                ],
            )

        if callback.action == CallbackAction.CONFIRM_REVOKE:
            if not callback.value:
                return self._stale(locale)
            try:
                revoked = self.portal.revoke_session(context, callback.value)
            except AuthoritativePrivateApiError:
                revoked = False
            except PrivateApiUnavailable:
                # Revocation is idempotent. Reconcile with a safe GET rather than repeating the
                # mutation after an ambiguous transport failure.
                try:
                    revoked = self._find_session(self.portal.sessions(context), callback.value) is None
                except Exception:  # noqa: BLE001
                    return self._callback_message(
                        "نتیجه خروج از نشست هنوز مشخص نیست. درخواست خودکار تکرار نشد.\n"
                        "کمی بعد نشست‌های فعال را دوباره بررسی کنید.",
                        [
                            [
                                {
                                    "text": "🔄 بررسی نشست‌ها",
                                    "callback_data": BotCallback(CallbackAction.SECURITY).pack(),
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
            notice = (
                "✅ نشست انتخاب‌شده با موفقیت بسته شد."
                if revoked
                else "این نشست دیگر فعال نیست یا پیدا نشد."
            )
            text, rows = self._security_view(user, locale, notice=notice)
            return self._callback_message(text, rows)

        return super()._route_callback(user, locale, callback, update_id)


class AccountSecurityTelegramPollingRuntime(SecureDeliveryTelegramPollingRuntime):
    """Production polling runtime with secure delivery and native account-session controls."""

    def __init__(
        self,
        settings: BotSettings,
        identity: TelegramIdentityPort,
        transport: TelegramTransport | None = None,
        *,
        portal: CustomerPortalPort | None = None,
        conversations: ConversationStoreV2 | None = None,
        retry_base_seconds: float = 0.2,
        retry_max_seconds: float = 5.0,
    ) -> None:
        super().__init__(
            settings,
            identity,
            transport,
            portal=portal,
            conversations=conversations,
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
        self.handler = AccountSecurityBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
