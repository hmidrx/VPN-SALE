"""Truthful customer-facing purchase lifecycle rendering for production polling."""

from __future__ import annotations

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.formatting import format_date
from telegram_bot.portal import CustomerPortalPort, PurchaseResult
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    HandlerResult,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.transport.polling import TelegramPollingRuntime, TelegramTransport


def purchase_status_text(result: PurchaseResult) -> str:
    """Render only states that the private API has authoritatively established."""
    state = result.fulfillment_status
    if result.refunded or state == "REFUNDED":
        return "ساخت سرویس کامل نشد و مبلغ سفارش به کیف پول شما بازگردانده شد."
    if state == "OPERATOR_REVIEW":
        return (
            "⚠️ وضعیت ساخت سرویس نیازمند بررسی اپراتور است.\n"
            "تا مشخص شدن وضعیت ارائه‌دهنده، سرویس فعال اعلام نمی‌شود و بازپرداخت خودکار "
            "بر اساس یک نتیجه نامطمئن انجام نخواهد شد.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    if state == "PENDING_DELIVERY":
        return (
            "🟡 ساخت سرویس در ارائه‌دهنده تأیید شده است، اما تحویل کانفیگ هنوز آماده نیست.\n"
            "سرویس تا آماده شدن مسیر تحویل، فعال اعلام نمی‌شود.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    if state == "ACTIVE" and result.service_reference:
        return (
            f"✅ سرویس شما فعال شد\n\nنام سرویس: {result.plan.title}\n"
            f"موقعیت: {result.plan.location_label}\n"
            f"اعتبار تا: {format_date(result.expires_at)}\n"
            f"حجم: {result.plan.traffic_gb:,} گیگابایت\n"
            f"شناسه: {result.service_reference[-8:]}"
        )
    if state == "PROVISIONING":
        return (
            "⏳ سفارش پرداخت شده و ساخت سرویس در حال انجام است.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    return (
        "⏳ سفارش هنوز آماده تحویل نیست.\n"
        f"شناسه سفارش: {result.order_reference[-8:]}"
    )


class TruthfulPurchaseBotCommandHandler(BotCommandHandler):
    """Keep the existing purchase mutation flow, then replace only status copy."""

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        result = super()._route_callback(user, locale, callback, update_id)
        if callback.action not in {CallbackAction.CONFIRM_PURCHASE, CallbackAction.PURCHASE_STATUS}:
            return result

        order_reference = callback.value if callback.action == CallbackAction.PURCHASE_STATUS else ""
        if not order_reference:
            state = self.conversations.get(self._conversation_key(user), self._now())
            order_reference = state.active_order_reference or ""
        if not order_reference:
            return result
        purchase = self.portal.purchase_order(self._portal_context(user, locale), order_reference)
        if purchase is None or not result.messages:
            return result
        messages = list(result.messages)
        first = messages[0]
        messages[0] = OutgoingMessage(purchase_status_text(purchase), first.rows)
        return HandlerResult(
            result.acknowledged,
            result.duplicate,
            tuple(messages),
            result.callback_notice,
            result.callback_alert,
        )

    @staticmethod
    def _now():
        from telegram_bot.application.identity import now_utc

        return now_utc()


class TruthfulTelegramPollingRuntime(TelegramPollingRuntime):
    """Production polling runtime with lifecycle-aware purchase rendering."""

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
        self.handler = TruthfulPurchaseBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
