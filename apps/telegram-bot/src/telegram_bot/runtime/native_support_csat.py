"""Native support CSAT UX layered on the durable BOT-3B/BOT-3C support runtime."""

from __future__ import annotations

from dataclasses import replace

from telegram_bot.application.identity import TelegramIdentityPort, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStateV2, ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.rate_limit import RateLimitExceeded, RateLimitUnavailable
from telegram_bot.runtime.handlers import HandlerResult, IncomingText, IncomingUser
from telegram_bot.runtime.native_support import (
    NativeSupportBotCommandHandler,
    NativeSupportTelegramPollingRuntime,
)
from telegram_bot.support_api import SupportOutcomeUnknown
from telegram_bot.transport.polling import TelegramTransport


class NativeSupportCsatBotCommandHandler(NativeSupportBotCommandHandler):
    """Adds one durable satisfaction response per support resolution/reopen cycle."""

    @staticmethod
    def _parse_rate_value(value: str) -> tuple[str, int] | None:
        reference, separator, raw_score = value.partition("|")
        if not separator:
            return None
        try:
            score = int(raw_score)
        except ValueError:
            return None
        if not reference.startswith("SUP-") or not 1 <= score <= 5:
            return None
        return reference, score

    @staticmethod
    def _parse_expected(state: ConversationStateV2) -> tuple[str, int] | None:
        value = state.expected_input or ""
        parts = value.split(":", 2)
        if len(parts) != 3 or parts[0] != "csat":
            return None
        try:
            score = int(parts[2])
        except ValueError:
            return None
        if not parts[1].startswith("SUP-") or not 1 <= score <= 5:
            return None
        return parts[1], score

    def _ticket_detail(
        self,
        user: IncomingUser,
        locale: str,
        reference: str,
        cursor: str | None = None,
        previous_cursors: tuple[str, ...] = (),
    ) -> HandlerResult:
        result = super()._ticket_detail(user, locale, reference, cursor, previous_cursors)
        if cursor is not None or not result.messages:
            return result
        try:
            csat = self.support_portal.support_csat_state(
                self._portal_context(user, locale), reference
            )
        except (PrivateApiUnavailable, AuthoritativePrivateApiError, AttributeError):
            return result

        message = result.messages[0]
        text = message.text
        rows = [list(row) for row in message.rows]
        if csat.submitted and csat.score is not None:
            text += f"\n\n⭐ امتیاز ثبت‌شده شما: {csat.score} از ۵"
        elif csat.eligible:
            text += "\n\n⭐ از پاسخ پشتیبانی راضی بودید؟"
            rating_row = [
                {
                    "text": f"{score} ⭐",
                    "callback_data": BotCallback(
                        CallbackAction.SUPPORT_CSAT_RATE, f"{reference}|{score}"
                    ).pack(),
                }
                for score in range(1, 6)
            ]
            rows.insert(max(len(rows) - 1, 0), rating_row)
        return replace(
            result, messages=(replace(message, text=text[:4000], rows=rows), *result.messages[1:])
        )

    def _start_csat(self, user: IncomingUser, value: str, update_id: int) -> HandlerResult:
        parsed = self._parse_rate_value(value)
        if parsed is None:
            return self._stale("fa")
        reference, score = parsed
        context = self._portal_context(user, "fa")
        try:
            csat = self.support_portal.support_csat_state(context, reference)
        except (PrivateApiUnavailable, AuthoritativePrivateApiError):
            return self._stale("fa")
        if not csat.eligible:
            return self._ticket_detail(user, "fa", reference)

        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind="support",
                expected_input=f"csat:{reference}:{score}",
                idempotency_key=f"tg-support-csat:{update_id}:{reference}:{score}",
            ),
        )
        return self._callback_message(
            f"امتیاز {score} از ۵ انتخاب شد.\n\n"
            "اگر توضیحی دارید در یک پیام بفرستید؛ متن بازخورد فقط در سامانه پشتیبانی ثبت می‌شود.",
            [
                [
                    {
                        "text": "ثبت بدون توضیح",
                        "callback_data": BotCallback(CallbackAction.SUPPORT_CSAT_SKIP).pack(),
                    }
                ],
                [
                    {
                        "text": "لغو",
                        "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                    }
                ],
            ],
        )

    def _clear_csat_state(self, user: IncomingUser, state: ConversationStateV2) -> None:
        self.conversations.save(
            self._conversation_key(user),
            replace(
                state,
                conversation_kind=None,
                expected_input=None,
                idempotency_key=None,
            ),
        )

    def _submit_without_feedback(self, user: IncomingUser) -> HandlerResult:
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        parsed = self._parse_expected(state)
        if state.conversation_kind != "support" or parsed is None:
            return self._stale("fa")
        reference, score = parsed
        try:
            self.support_portal.submit_support_csat(
                self._portal_context(user, "fa"),
                reference,
                score,
                None,
                state.idempotency_key or f"tg-support-csat:{reference}:{score}",
            )
        except SupportOutcomeUnknown:
            return self._callback_message(
                "نتیجه ثبت امتیاز هنوز مشخص نیست. دوباره همین دکمه را بزنید؛ "
                "ثبت تکراری انجام نمی‌شود.",
                [
                    [
                        {
                            "text": "تلاش دوباره",
                            "callback_data": BotCallback(CallbackAction.SUPPORT_CSAT_SKIP).pack(),
                        }
                    ]
                ],
            )
        except AuthoritativePrivateApiError:
            return self._ticket_detail(user, "fa", reference)
        except PrivateApiUnavailable:
            return self._single("ثبت رضایت موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.", [])
        self._clear_csat_state(user, state)
        return self._ticket_detail(user, "fa", reference)

    def handle_text(self, message: IncomingText) -> HandlerResult:
        if message.chat_type != "private" or message.user is None:
            return super().handle_text(message)
        key = self._conversation_key(message.user)
        state = self.conversations.get(key, now_utc())
        parsed = self._parse_expected(state)
        if state.conversation_kind != "support" or parsed is None:
            return super().handle_text(message)
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        try:
            self.rate_limiter.check(
                "support_csat_text",
                message.user.telegram_user_id,
                self.settings.sensitive_rate_limit,
                self.settings.sensitive_rate_limit_window_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return self._single("لطفاً چند لحظه بعد دوباره تلاش کنید.", [])

        feedback = message.text.replace("\r\n", "\n").strip()
        if not feedback or len(feedback) > 800:
            return self._single("بازخورد باید بین ۱ تا ۸۰۰ نویسه باشد.", [])
        reference, score = parsed
        try:
            self.support_portal.submit_support_csat(
                self._portal_context(message.user, "fa"),
                reference,
                score,
                feedback,
                state.idempotency_key or f"tg-support-csat:{reference}:{score}",
            )
        except SupportOutcomeUnknown:
            return self._single(
                "نتیجه ثبت بازخورد هنوز مشخص نیست. همان متن را دوباره بفرستید؛ "
                "شناسه قبلی حفظ شده است.",
                [],
            )
        except AuthoritativePrivateApiError:
            return self._ticket_detail(message.user, "fa", reference)
        except PrivateApiUnavailable:
            return self._single("ثبت رضایت موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.", [])
        self._clear_csat_state(message.user, state)
        return self._ticket_detail(message.user, "fa", reference)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.SUPPORT_CSAT_RATE:
            return self._start_csat(user, callback.value, update_id)
        if callback.action == CallbackAction.SUPPORT_CSAT_SKIP:
            return self._submit_without_feedback(user)
        return super()._route_callback(user, locale, callback, update_id)


class NativeSupportCsatTelegramPollingRuntime(NativeSupportTelegramPollingRuntime):
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
        self.handler = NativeSupportCsatBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
