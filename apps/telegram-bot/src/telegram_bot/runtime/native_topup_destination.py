"""Native manual card-transfer destination flow layered over the Telegram purchase runtime."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from telegram_bot.application.identity import TelegramIdentityPort, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.runtime.handlers import (
    ButtonRows,
    HandlerResult,
    IncomingReceipt,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.runtime.native_purchase_options import (
    NativePurchaseBotCommandHandler,
    NativePurchaseTelegramPollingRuntime,
)
from telegram_bot.topup_destination_api import (
    ManualTopupDestination,
    NativeTopupDestinationPortal,
)
from telegram_bot.transport.polling import TelegramTransport


class NativeTopupDestinationBotCommandHandler(NativePurchaseBotCommandHandler):
    @property
    def native_topup_destination(self) -> NativeTopupDestinationPortal:
        return cast(NativeTopupDestinationPortal, self.portal)

    @staticmethod
    def _strip_web_app_rows(rows: ButtonRows) -> ButtonRows:
        return [
            [button for button in row if "web_app_url" not in button]
            for row in rows
            if any("web_app_url" not in button for button in row)
        ]

    @classmethod
    def _strip_web_app_result(cls, result: HandlerResult) -> HandlerResult:
        return replace(
            result,
            messages=tuple(
                OutgoingMessage(message.text, cls._strip_web_app_rows(message.rows))
                for message in result.messages
            ),
        )

    @staticmethod
    def _destination_lines(destination: ManualTopupDestination) -> list[str]:
        if destination.mode != "DIRECT_CARD" or not destination.formatted_card_number:
            return []
        lines = ["", "💳 اطلاعات واریز", f"شماره کارت: {destination.formatted_card_number}"]
        if destination.card_holder_name:
            lines.append(f"به نام: {destination.card_holder_name}")
        lines.append("بعد از واریز، تصویر فیش را همین‌جا ارسال کنید.")
        return lines

    def _direct_card_rows(self, reference: str) -> ButtonRows:
        return [
            [
                {
                    "text": "📎 ارسال فیش",
                    "callback_data": BotCallback(CallbackAction.SEND_RECEIPT, reference).pack(),
                },
                self._cancel_topup_button(reference),
            ],
            [
                {
                    "text": "🔄 وضعیت درخواست",
                    "callback_data": BotCallback(
                        CallbackAction.OPEN_MANUAL_TOPUP, reference
                    ).pack(),
                },
                {
                    "text": "🏠 منوی اصلی",
                    "callback_data": BotCallback(CallbackAction.HOME).pack(),
                },
            ],
        ]

    def _destination_for(
        self, user: IncomingUser, locale: str, reference: str
    ) -> ManualTopupDestination | None:
        try:
            return self.native_topup_destination.manual_topup_destination(
                self._portal_context(user, locale), reference
            )
        except Exception:  # noqa: BLE001 - do not expose destination transport details
            return None

    def handle_receipt(self, message: IncomingReceipt) -> HandlerResult:
        return self._strip_web_app_result(super().handle_receipt(message))

    def _manual_topup_detail(
        self, user: IncomingUser, locale: str, reference: str
    ) -> HandlerResult:
        result = self._strip_web_app_result(super()._manual_topup_detail(user, locale, reference))
        if not result.messages:
            return result
        request = self.portal.manual_topup(self._portal_context(user, locale), reference)
        if request is None or request.status not in {"AWAITING_RECEIPT", "NEEDS_RESUBMISSION"}:
            return result
        destination = self._destination_for(user, locale, reference)
        if destination is None:
            return result
        lines = self._destination_lines(destination)
        if not lines:
            return result
        first = result.messages[0]
        return replace(
            result,
            messages=(OutgoingMessage(first.text + "\n" + "\n".join(lines), first.rows),)
            + result.messages[1:],
        )

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        result = super()._route_callback(user, locale, callback, update_id)
        if callback.action != CallbackAction.CONFIRM_TOP_UP:
            return result
        result = self._strip_web_app_result(result)
        state = self.conversations.get(self._conversation_key(user), now_utc())
        reference = state.active_manual_topup_reference
        if not reference or not result.messages:
            return result
        destination = self._destination_for(user, locale, reference)
        if destination is None:
            first = result.messages[0]
            fallback_rows: ButtonRows = [
                [
                    {
                        "text": "🎫 پشتیبانی",
                        "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                    },
                    self._cancel_topup_button(reference),
                ],
                [
                    {
                        "text": "🔄 وضعیت درخواست",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_MANUAL_TOPUP, reference
                        ).pack(),
                    }
                ],
            ]
            return replace(
                result,
                messages=(
                    OutgoingMessage(
                        first.text
                        + "\n\nاطلاعات واریز موقتاً قابل نمایش نیست؛ از پشتیبانی دریافت کنید.",
                        fallback_rows,
                    ),
                )
                + result.messages[1:],
            )
        if destination.mode != "DIRECT_CARD":
            return result
        first = result.messages[0]
        return replace(
            result,
            messages=(
                OutgoingMessage(
                    first.text + "\n" + "\n".join(self._destination_lines(destination)),
                    self._direct_card_rows(reference),
                ),
            )
            + result.messages[1:],
        )


class NativeTopupDestinationTelegramPollingRuntime(NativePurchaseTelegramPollingRuntime):
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
        self.handler = NativeTopupDestinationBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
