"""Native durable support UX layered on account security and secure delivery."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from telegram_bot.application.identity import TelegramIdentityPort, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.localization import t
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.rate_limit import RateLimitExceeded, RateLimitUnavailable
from telegram_bot.runtime.account_security import (
    AccountSecurityBotCommandHandler,
    AccountSecurityTelegramPollingRuntime,
)
from telegram_bot.runtime.handlers import (
    HandlerResult,
    IncomingCommand,
    IncomingText,
    IncomingUser,
)
from telegram_bot.screens import safe_date, safe_text
from telegram_bot.support_api import (
    NativeSupportPortal,
    SupportOutcomeUnknown,
    SupportTicket,
)
from telegram_bot.transport.polling import TelegramTransport


class NativeSupportBotCommandHandler(AccountSecurityBotCommandHandler):
    @property
    def support_portal(self) -> NativeSupportPortal:
        return cast(NativeSupportPortal, self.portal)

    @staticmethod
    def _status(value: str) -> str:
        return {
            "NEW": "جدید",
            "OPEN": "باز",
            "ASSIGNED": "ارجاع‌شده",
            "IN_PROGRESS": "در حال بررسی",
            "WAITING_FOR_CUSTOMER": "منتظر پاسخ شما",
            "WAITING_FOR_SUPPORT": "منتظر پاسخ پشتیبانی",
            "ESCALATED": "ارجاع ویژه",
            "RESOLVED": "حل‌شده",
            "CLOSED": "بسته",
            "REOPENED": "بازگشایی‌شده",
            "SPAM": "بسته‌شده",
            "ARCHIVED": "بایگانی",
        }.get(value, "در حال بررسی")

    def _support_home(self) -> HandlerResult:
        return self._callback_message(
            "💬 پشتیبانی\n\n"
            "از همین ربات می‌توانید تیکت ثبت کنید، پاسخ‌های پشتیبانی را ببینید و ادامه گفتگو را ارسال کنید.",
            [
                [
                    {
                        "text": "📝 تیکت جدید",
                        "callback_data": BotCallback(CallbackAction.SUPPORT_NEW).pack(),
                    },
                    {
                        "text": "📋 تیکت‌های من",
                        "callback_data": BotCallback(CallbackAction.SUPPORT_TICKETS).pack(),
                    },
                ],
                [
                    {
                        "text": "🏠 منوی اصلی",
                        "callback_data": BotCallback(CallbackAction.HOME).pack(),
                    }
                ],
            ],
        )

    def _ticket_list(self, user: IncomingUser, locale: str) -> HandlerResult:
        try:
            tickets = self.support_portal.support_tickets(self._portal_context(user, locale))
        except Exception:  # noqa: BLE001 - private API boundary
            return self._callback_message(
                "⚠️ دریافت تیکت‌ها ممکن نشد. کمی بعد دوباره تلاش کنید.",
                [
                    [
                        {
                            "text": "🔄 تلاش دوباره",
                            "callback_data": BotCallback(CallbackAction.SUPPORT_TICKETS).pack(),
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
        if not tickets:
            return self._callback_message(
                "هنوز تیکتی ثبت نکرده‌اید.",
                [
                    [
                        {
                            "text": "📝 ثبت تیکت",
                            "callback_data": BotCallback(CallbackAction.SUPPORT_NEW).pack(),
                        }
                    ],
                    [
                        {
                            "text": "◀️ پشتیبانی",
                            "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                        }
                    ],
                ],
            )
        lines = ["📋 تیکت‌های من"]
        rows: list[list[dict[str, str]]] = []
        for ticket in tickets[:10]:
            lines.append(
                f"\n• {safe_text(ticket.subject[:80])}\n"
                f"وضعیت: {self._status(ticket.status)} | {safe_date(ticket.updated_at)}"
            )
            rows.append(
                [
                    {
                        "text": f"مشاهده {ticket.reference[-8:]}",
                        "callback_data": BotCallback(
                            CallbackAction.SUPPORT_OPEN, ticket.reference
                        ).pack(),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "📝 تیکت جدید",
                    "callback_data": BotCallback(CallbackAction.SUPPORT_NEW).pack(),
                },
                {
                    "text": "🏠 منوی اصلی",
                    "callback_data": BotCallback(CallbackAction.HOME).pack(),
                },
            ]
        )
        return self._callback_message("\n".join(lines), rows)

    def _ticket_detail(self, user: IncomingUser, locale: str, reference: str) -> HandlerResult:
        try:
            ticket = self.support_portal.support_ticket(self._portal_context(user, locale), reference)
        except Exception:  # noqa: BLE001
            ticket = None
        if ticket is None:
            return self._callback_message(
                "این تیکت پیدا نشد یا دیگر در دسترس نیست.",
                [
                    [
                        {
                            "text": "📋 تیکت‌های من",
                            "callback_data": BotCallback(CallbackAction.SUPPORT_TICKETS).pack(),
                        }
                    ]
                ],
            )
        lines = [
            f"🎫 {safe_text(ticket.subject)}",
            f"وضعیت: {self._status(ticket.status)}",
            f"شناسه: {ticket.reference[-8:]}",
        ]
        for message in ticket.messages[-8:]:
            sender = "شما" if message.sender_type == "CUSTOMER" else "پشتیبانی"
            body = safe_text(message.body[:600])
            lines.extend(["", f"{sender} — {safe_date(message.created_at)}", body])
        rows: list[list[dict[str, str]]] = []
        if ticket.status not in {"SPAM", "ARCHIVED"}:
            rows.append(
                [
                    {
                        "text": "✉️ پاسخ به تیکت",
                        "callback_data": BotCallback(
                            CallbackAction.SUPPORT_REPLY, ticket.reference
                        ).pack(),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "📋 تیکت‌های من",
                    "callback_data": BotCallback(CallbackAction.SUPPORT_TICKETS).pack(),
                },
                {
                    "text": "🏠 منوی اصلی",
                    "callback_data": BotCallback(CallbackAction.HOME).pack(),
                },
            ]
        )
        return self._callback_message("\n".join(lines)[:3900], rows)

    def _start_new_ticket(self, user: IncomingUser, update_id: int) -> HandlerResult:
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind="support",
                expected_input="new",
                idempotency_key=f"tg-support-new:{update_id}",
            ),
        )
        return self._callback_message(
            "موضوع را در خط اول و توضیحات را از خط دوم به بعد بفرستید.\n\n"
            "مثال:\nمشکل اتصال سرویس\nاز امروز اتصال برقرار نمی‌شود.",
            [
                [
                    {
                        "text": "لغو",
                        "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                    }
                ]
            ],
        )

    def _start_reply(self, user: IncomingUser, reference: str, update_id: int) -> HandlerResult:
        ticket = self.support_portal.support_ticket(self._portal_context(user, "fa"), reference)
        if ticket is None:
            return self._stale("fa")
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind="support",
                expected_input=f"reply:{reference}",
                idempotency_key=f"tg-support-reply:{update_id}:{reference}",
            ),
        )
        return self._callback_message(
            f"پاسخ خود را برای «{safe_text(ticket.subject[:100])}» ارسال کنید.",
            [
                [
                    {
                        "text": "لغو",
                        "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                    }
                ]
            ],
        )

    def handle_command(self, command: IncomingCommand) -> HandlerResult:
        if command.command != "/support":
            return super().handle_command(command)
        self.metrics.inc("updates_received")
        if not self.idempotency.claim(
            command.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if command.chat_type != "private" or command.user is None:
            return self._single(t("fa", "group_ignored"), [])
        return self._support_home()

    def handle_text(self, message: IncomingText) -> HandlerResult:
        if message.chat_type != "private" or message.user is None:
            return super().handle_text(message)
        key = self._conversation_key(message.user)
        state = self.conversations.get(key, now_utc())
        if state.conversation_kind != "support":
            return super().handle_text(message)
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        try:
            self.rate_limiter.check(
                "support_text",
                message.user.telegram_user_id,
                self.settings.sensitive_rate_limit,
                self.settings.sensitive_rate_limit_window_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return self._single("لطفاً چند لحظه بعد دوباره تلاش کنید.", [])
        text = message.text.replace("\r\n", "\n").strip()
        context = self._portal_context(message.user, "fa")
        try:
            if state.expected_input == "new":
                parts = text.split("\n", 1)
                if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                    return self._single(
                        "خط اول باید موضوع و خط‌های بعدی باید توضیحات تیکت باشند.", []
                    )
                subject, body = parts[0].strip(), parts[1].strip()
                if len(subject) > 160 or len(body) > 4000:
                    return self._single("متن تیکت بیش از حد مجاز است.", [])
                ticket = self.support_portal.create_support_ticket(
                    context,
                    subject,
                    body,
                    state.idempotency_key or f"tg-support-new:{message.update_id}",
                )
            elif state.expected_input and state.expected_input.startswith("reply:"):
                reference = state.expected_input.removeprefix("reply:")
                if not text or len(text) > 4000:
                    return self._single("پاسخ باید بین ۱ تا ۴۰۰۰ نویسه باشد.", [])
                ticket = self.support_portal.reply_support_ticket(
                    context,
                    reference,
                    text,
                    state.idempotency_key or f"tg-support-reply:{message.update_id}:{reference}",
                )
            else:
                return super().handle_text(message)
        except SupportOutcomeUnknown:
            return self._single(
                "نتیجه ارسال هنوز مشخص نیست. همان پیام را دوباره ارسال کنید؛ "
                "شناسه قبلی حفظ شده و تیکت/پیام تکراری ساخته نمی‌شود.",
                [],
            )
        except AuthoritativePrivateApiError:
            return self._single("ارسال تیکت از طرف سرور پذیرفته نشد. متن را بررسی کنید.", [])
        except PrivateApiUnavailable:
            return self._single("پشتیبانی موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.", [])
        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind=None,
                expected_input=None,
                idempotency_key=None,
            ),
        )
        return self._ticket_detail(message.user, "fa", ticket.reference)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.SUPPORT:
            return self._support_home()
        if callback.action == CallbackAction.SUPPORT_TICKETS:
            return self._ticket_list(user, locale)
        if callback.action == CallbackAction.SUPPORT_NEW:
            return self._start_new_ticket(user, update_id)
        if callback.action == CallbackAction.SUPPORT_OPEN:
            if not callback.value:
                return self._stale(locale)
            return self._ticket_detail(user, locale, callback.value)
        if callback.action == CallbackAction.SUPPORT_REPLY:
            if not callback.value:
                return self._stale(locale)
            try:
                return self._start_reply(user, callback.value, update_id)
            except (PrivateApiUnavailable, AuthoritativePrivateApiError):
                return self._stale(locale)
        return super()._route_callback(user, locale, callback, update_id)


class NativeSupportTelegramPollingRuntime(AccountSecurityTelegramPollingRuntime):
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
        self.handler = NativeSupportBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
