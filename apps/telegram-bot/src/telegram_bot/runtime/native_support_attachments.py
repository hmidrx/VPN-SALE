# pyright: reportPrivateUsage=false
"""Safe customer image attachments layered on native support + CSAT."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from telegram_bot.application.identity import TelegramIdentityPort, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.localization import t
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.rate_limit import RateLimitExceeded, RateLimitUnavailable
from telegram_bot.runtime.handlers import (
    HandlerResult,
    IncomingReceipt,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.runtime.native_support_csat import (
    NativeSupportCsatBotCommandHandler,
    NativeSupportCsatTelegramPollingRuntime,
)
from telegram_bot.support_api import SupportOutcomeUnknown
from telegram_bot.transport.polling import (
    TelegramTransport,
    _message_chat,
    _send_message_payload,
)

_MAX_IMAGE_BYTES = 5 * 1024 * 1024


class NativeSupportAttachmentBotCommandHandler(NativeSupportCsatBotCommandHandler):
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
        message = result.messages[0]
        rows = [list(row) for row in message.rows]
        attachment_row = [
            {
                "text": "📎 ارسال تصویر",
                "callback_data": BotCallback(CallbackAction.SUPPORT_ATTACHMENT, reference).pack(),
            }
        ]
        rows.insert(max(len(rows) - 1, 0), attachment_row)
        return replace(result, messages=(replace(message, rows=rows), *result.messages[1:]))

    def _start_attachment(self, user: IncomingUser, reference: str, update_id: int) -> HandlerResult:
        ticket = self.support_portal.support_ticket(self._portal_context(user, "fa"), reference)
        if ticket is None or ticket.status in {"SPAM", "ARCHIVED"}:
            return self._stale("fa")
        key = self._conversation_key(user)
        state = self.conversations.get(key, now_utc())
        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind="support",
                expected_input=f"attachment:{reference}",
                idempotency_key=f"tg-support-attachment:{update_id}:{reference}",
                active_support_reference=reference,
            ),
        )
        return self._callback_message(
            "یک تصویر JPEG، PNG یا WebP تا حداکثر ۵ مگابایت ارسال کنید.\n"
            "فایل قبل از ذخیره بررسی و بازنویسی می‌شود تا metadata آن حذف شود.",
            [
                [
                    {
                        "text": "لغو",
                        "callback_data": BotCallback(CallbackAction.CANCEL_CONVERSATION).pack(),
                    }
                ]
            ],
        )

    def expected_support_attachment_reference(self, user: IncomingUser) -> str | None:
        state = self.conversations.get(self._conversation_key(user), now_utc())
        expected = state.expected_input or ""
        if state.conversation_kind != "support" or not expected.startswith("attachment:"):
            return None
        reference = expected.removeprefix("attachment:")
        return reference if reference.startswith("SUP-") and len(reference) <= 32 else None

    def handle_support_attachment(self, message: IncomingReceipt) -> HandlerResult:
        if not self.idempotency.claim(
            message.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            return HandlerResult(True, True, ())
        if message.chat_type != "private" or message.user is None:
            return self._single(t("fa", "group_ignored"), [])
        reference = self.expected_support_attachment_reference(message.user)
        if reference is None:
            return self._single("ابتدا از داخل تیکت گزینه «ارسال تصویر» را انتخاب کنید.", [])
        try:
            self.rate_limiter.check(
                "support_attachment",
                message.user.telegram_user_id,
                self.settings.sensitive_rate_limit,
                self.settings.sensitive_rate_limit_window_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return self._single("لطفاً چند لحظه بعد دوباره تلاش کنید.", [])

        key = self._conversation_key(message.user)
        state = self.conversations.get(key, now_utc())
        try:
            ticket = self.support_portal.upload_support_attachment(
                self._portal_context(message.user, "fa"),
                reference,
                message.content,
                message.content_type,
                state.idempotency_key or f"tg-support-attachment:{reference}",
            )
        except SupportOutcomeUnknown:
            return self._single(
                "نتیجه ارسال تصویر هنوز مشخص نیست. همان تصویر را دوباره بفرستید؛ "
                "شناسه قبلی حفظ شده و فایل تکراری ساخته نمی‌شود.",
                [],
            )
        except AuthoritativePrivateApiError:
            return self._single(
                "تصویر پذیرفته نشد. فقط JPEG، PNG یا WebP معتبر تا ۵ مگابایت ارسال کنید.",
                [],
            )
        except PrivateApiUnavailable:
            return self._single("ارسال تصویر موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.", [])

        self.conversations.save(
            key,
            replace(
                state,
                conversation_kind=None,
                expected_input=None,
                idempotency_key=None,
                active_support_reference=ticket.reference,
                support_message_cursor=None,
                support_message_next_cursor=None,
                support_message_previous_cursors=(),
            ),
        )
        return self._ticket_detail(message.user, "fa", ticket.reference)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.SUPPORT_ATTACHMENT:
            if not callback.value:
                return self._stale(locale)
            try:
                return self._start_attachment(user, callback.value, update_id)
            except (PrivateApiUnavailable, AuthoritativePrivateApiError):
                return self._stale(locale)
        return super()._route_callback(user, locale, callback, update_id)


class NativeSupportAttachmentTelegramPollingRuntime(NativeSupportCsatTelegramPollingRuntime):
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
        self.handler = NativeSupportAttachmentBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )

    async def _dispatch_receipt(
        self,
        update: dict[str, Any],
        receipt: tuple[IncomingUser, str, str, int | None],
    ) -> None:
        handler = cast(NativeSupportAttachmentBotCommandHandler, self.handler)
        user, file_id, content_type, file_size = receipt
        if handler.expected_support_attachment_reference(user) is None:
            await super()._dispatch_receipt(update, receipt)
            return

        chat_id, chat_type = _message_chat(update)
        if chat_id is None:
            return
        if file_size is not None and file_size > _MAX_IMAGE_BYTES:
            result = HandlerResult(
                True,
                False,
                (OutgoingMessage("حجم تصویر باید حداکثر ۵ مگابایت باشد.", []),),
            )
        else:
            try:
                metadata = await self.transport.call("getFile", {"file_id": file_id})
                file_result = metadata.get("result")
                if not isinstance(file_result, dict):
                    raise RuntimeError("Telegram download failed")
                file_data = cast(dict[str, Any], file_result)
                file_path = file_data.get("file_path")
                if not isinstance(file_path, str):
                    raise RuntimeError("Telegram download failed")
                content = await self.transport.download_file(file_path, _MAX_IMAGE_BYTES)
                result = handler.handle_support_attachment(
                    IncomingReceipt(
                        int(cast(int, update["update_id"])),
                        chat_type,
                        user,
                        content,
                        content_type,
                    )
                )
            except Exception:  # noqa: BLE001 - Telegram metadata and paths stay private
                result = HandlerResult(
                    True,
                    False,
                    (OutgoingMessage("دریافت تصویر انجام نشد؛ دوباره تلاش کنید.", []),),
                )
        for outgoing in result.messages:
            await self.transport.call("sendMessage", _send_message_payload(chat_id, outgoing))
