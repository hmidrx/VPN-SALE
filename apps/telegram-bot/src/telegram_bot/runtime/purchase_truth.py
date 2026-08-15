"""Truthful customer-facing purchase lifecycle rendering for production polling."""

from __future__ import annotations

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.delivery_portal import SensitiveDeliveryPortalPort
from telegram_bot.formatting import format_date
from telegram_bot.portal import CustomerPortalPort, PurchaseResult
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    HandlerResult,
    IncomingUser,
    OutgoingMessage,
)
from telegram_bot.transport.polling import TelegramPollingRuntime, TelegramTransport

_MAX_DELIVERY_MESSAGE_BYTES = 3500
_MAX_DELIVERY_LINKS = 8


def purchase_status_text(result: PurchaseResult) -> str:
    """Render only states that the private API has authoritatively established."""
    state = result.purchase_state
    service_reference = result.service_reference
    if result.refunded or state == "REFUNDED":
        return "ساخت سرویس کامل نشد و مبلغ سفارش به کیف پول شما بازگردانده شد."
    if state == "OPERATOR_REVIEW":
        return (
            "⚠️ وضعیت ساخت سرویس نیازمند بررسی اپراتور است.\n"
            "تا مشخص شدن وضعیت ارائه‌دهنده، سرویس فعال اعلام نمی‌شود و بازپرداخت خودکار "
            "بر اساس یک نتیجه نامطمئن انجام نخواهد شد.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    if (
        state == "ACTIVE"
        and result.service_lifecycle == "ACTIVE"
        and result.delivery_ready
        and service_reference is not None
    ):
        return (
            f"✅ سرویس شما فعال شد\n\nنام سرویس: {result.plan.title}\n"
            f"موقعیت: {result.plan.location_label}\n"
            f"اعتبار تا: {format_date(result.expires_at)}\n"
            f"حجم: {result.plan.traffic_gb:,} گیگابایت\n"
            f"شناسه: {service_reference[-8:]}"
        )
    if state == "PENDING_DELIVERY" or service_reference is not None:
        return (
            "🟡 ساخت سرویس در ارائه‌دهنده تأیید شده است، اما تحویل کانفیگ هنوز آماده نیست.\n"
            "سرویس تا آماده شدن مسیر تحویل، فعال اعلام نمی‌شود.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    if state == "PROVISIONING":
        return (
            "⏳ سفارش پرداخت شده و ساخت سرویس در حال انجام است.\n"
            f"شناسه سفارش: {result.order_reference[-8:]}"
        )
    return "⏳ سفارش هنوز آماده تحویل نیست.\n" f"شناسه سفارش: {result.order_reference[-8:]}"


def _delivery_text(links: tuple[str, ...]) -> str:
    if not links:
        return "کانفیگ هنوز آماده نمایش نیست."
    lines = ["🔐 کانفیگ سرویس", ""]
    used = len("\n".join(lines).encode())
    shown = 0
    for link in links[:_MAX_DELIVERY_LINKS]:
        candidate = f"`{link}`"
        size = len((candidate + "\n\n").encode())
        if used + size > _MAX_DELIVERY_MESSAGE_BYTES:
            break
        lines.extend([candidate, ""])
        used += size
        shown += 1
    if shown == 0:
        return "کانفیگ برای نمایش مستقیم در پیام بیش از حد بزرگ است."
    if shown < len(links):
        lines.append(f"{len(links) - shown} کانفیگ دیگر در این پیام نمایش داده نشد.")
    lines.append("این اطلاعات را فقط در برنامه VPN مورد اعتماد خود وارد کنید.")
    return "\n".join(lines)


class TruthfulPurchaseBotCommandHandler(BotCommandHandler):
    """Keep commerce authoritative and reveal credentials only after explicit customer action."""

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.OPEN_SUBSCRIPTION:
            service = self.portal.service(self._portal_context(user, locale), callback.value)
            if service is None or service.status.casefold() != "active":
                return self._callback_message(
                    "این سرویس فعال و آماده تحویل نیست.", self.renderer.nav_rows(locale)
                )
            if not isinstance(self.portal, SensitiveDeliveryPortalPort):
                return self._callback_message(
                    "مسیر امن نمایش کانفیگ در دسترس نیست.", self.renderer.nav_rows(locale)
                )
            try:
                links = self.portal.service_delivery_links(
                    self._portal_context(user, locale), callback.value
                )
            except Exception:  # noqa: BLE001 - never leak private API/provider details
                return self._callback_message(
                    "دریافت امن کانفیگ موقتاً ممکن نیست. کمی بعد دوباره تلاش کنید.",
                    self.renderer.nav_rows(locale),
                )
            return self._callback_message(_delivery_text(links), self.renderer.nav_rows(locale))

        result = super()._route_callback(user, locale, callback, update_id)

        if callback.action == CallbackAction.OPEN_SERVICE and result.messages:
            service = self.portal.service(self._portal_context(user, locale), callback.value)
            if service is not None and service.status.casefold() == "active":
                messages = list(result.messages)
                first = messages[0]
                rows = list(first.rows)
                rows.insert(
                    0,
                    [
                        {
                            "text": "🔐 نمایش کانفیگ",
                            "callback_data": BotCallback(
                                CallbackAction.OPEN_SUBSCRIPTION, service.ref
                            ).pack(),
                        }
                    ],
                )
                messages[0] = OutgoingMessage(first.text, rows)
                return HandlerResult(
                    result.acknowledged,
                    result.duplicate,
                    tuple(messages),
                    result.callback_notice,
                    result.callback_alert,
                )
            return result

        if callback.action not in {CallbackAction.CONFIRM_PURCHASE, CallbackAction.PURCHASE_STATUS}:
            return result

        order_reference = (
            callback.value if callback.action == CallbackAction.PURCHASE_STATUS else ""
        )
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
        rows = list(first.rows)
        if (
            purchase.purchase_state == "ACTIVE"
            and purchase.service_lifecycle == "ACTIVE"
            and purchase.delivery_ready
            and purchase.service_reference
        ):
            rows.insert(
                0,
                [
                    {
                        "text": "🔐 نمایش کانفیگ",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_SUBSCRIPTION, purchase.service_reference
                        ).pack(),
                    }
                ],
            )
        messages[0] = OutgoingMessage(purchase_status_text(purchase), rows)
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
