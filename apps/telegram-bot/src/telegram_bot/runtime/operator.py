from __future__ import annotations

from typing import cast

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.operator_api import OperatorHealth, OperatorPortal
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.rate_limit import RateLimitExceeded, RateLimitUnavailable
from telegram_bot.runtime.handlers import HandlerResult, IncomingCommand, IncomingUser
from telegram_bot.runtime.service_management import (
    ServiceManagementBotCommandHandler,
    ServiceManagementTelegramPollingRuntime,
)
from telegram_bot.transport.polling import TelegramTransport

_SIGNAL_LABELS = {
    "WORKER_HEARTBEAT_MISSING": "Worker هنوز heartbeat ثبت نکرده است",
    "WORKER_HEARTBEAT_STALE": "Heartbeat Worker قدیمی شده است",
    "WORKER_CYCLE_FAILURE_STREAK": "چند چرخه پیاپی Worker خطا داشته است",
    "WORKER_RECENT_CYCLE_FAILURE": "چرخه اخیر Worker خطا داشته است",
    "OUTBOX_FAILED": "رویداد Outbox ناموفق نهایی وجود دارد",
    "OUTBOX_STALE_CLAIMS": "Claim قدیمی Outbox وجود دارد",
    "OUTBOX_RETRYING": "رویدادهای Outbox در حال Retry هستند",
    "OUTBOX_LAGGING": "صف Outbox عقب افتاده است",
    "FULFILLMENT_FAILED": "Provisioning ناموفق نهایی وجود دارد",
    "FULFILLMENT_OPERATOR_REVIEW": "Provisioning نیازمند بررسی اپراتور است",
    "FULFILLMENT_BLOCKED": "Provisioning مسدود شده است",
    "FULFILLMENT_RETRYING": "Provisioning در حال Retry است",
    "SERVICE_OPERATION_REVIEW_REQUIRED": "عملیات سرویس نیازمند بررسی است",
    "USAGE_SYNC_DEGRADED": "همگام‌سازی مصرف افت کیفیت داشته است",
    "USAGE_DATA_STALE": "داده مصرف برخی سرویس‌ها قدیمی است",
}

_STATUS_LABELS = {
    "HEALTHY": "✅ سالم",
    "DEGRADED": "⚠️ نیازمند توجه",
    "ACTION_REQUIRED": "🚨 اقدام لازم",
}

_WORKER_LABELS = {
    "RUNNING": "✅ فعال",
    "DEGRADED": "⚠️ فعال با خطا",
    "STALE": "🚨 بدون heartbeat تازه",
    "MISSING": "🚨 heartbeat ثبت نشده",
}


class OperatorBotCommandHandler(ServiceManagementBotCommandHandler):
    @property
    def operator(self) -> OperatorPortal:
        return cast(OperatorPortal, self.portal)

    def handle_command(self, command: IncomingCommand) -> HandlerResult:
        if command.command != "/ops":
            return super().handle_command(command)
        self.metrics.inc("updates_received")
        if not self.idempotency.claim(
            command.update_id, self.settings.update_idempotency_ttl_seconds
        ):
            self.metrics.inc("duplicate_updates")
            return HandlerResult(True, True, ())
        if command.chat_type != "private" or command.user is None:
            return HandlerResult(True, False, ())
        try:
            self.rate_limiter.check(
                "ops",
                command.user.telegram_user_id,
                self.settings.command_rate_limit,
                self.settings.command_rate_limit_window_seconds,
            )
        except (RateLimitExceeded, RateLimitUnavailable):
            return HandlerResult(True, False, ())
        return self._operator_screen(command.user)

    def _operator_screen(self, user: IncomingUser) -> HandlerResult:
        try:
            health = self.operator.operator_health(user.telegram_user_id)
        except AuthoritativePrivateApiError as exc:
            if exc.status_code == 403:
                return self._single("این بخش برای حساب شما فعال نیست.", [])
            return self._single("وضعیت مدیریتی موقتاً قابل دریافت نیست.", [])
        except (PrivateApiUnavailable, AttributeError, ValueError):
            return self._single(
                "وضعیت مدیریتی موقتاً قابل دریافت نیست.",
                [
                    [
                        {
                            "text": "🔄 تلاش دوباره",
                            "callback_data": BotCallback(CallbackAction.RETRY, "ops").pack(),
                        }
                    ]
                ],
            )
        return self._render_operator_health(health)

    def _render_operator_health(self, health: OperatorHealth) -> HandlerResult:
        fulfillment_attention = (
            health.fulfillment_retry_pending
            + health.fulfillment_blocked
            + health.fulfillment_operator_review
            + health.fulfillment_failed
        )
        outbox_attention = (
            health.outbox_retrying + health.outbox_failed + health.outbox_stale_claims
        )
        lines = [
            "🛡 وضعیت عملیاتی ربات",
            "",
            f"وضعیت کلی: {_STATUS_LABELS[health.status]}",
            f"Worker: {_WORKER_LABELS[health.worker_state]}",
            f"چرخه‌های خطای پیاپی: {health.worker_consecutive_failures}",
            "",
            f"Outbox آماده ارسال: {health.outbox_pending_due}",
            f"Outbox نیازمند توجه: {outbox_attention}",
            f"Provisioning نیازمند توجه: {fulfillment_attention}",
            f"عملیات سرویس در حال اجرا: {health.service_operations_in_progress}",
            f"عملیات سرویس نیازمند بررسی: {health.service_operations_review_required}",
            f"Usage sync: {health.usage_latest_status}",
            f"Usage قدیمی: {health.usage_stale_active_accounts}",
        ]
        if health.signals:
            lines.extend(["", "سیگنال‌ها:"])
            lines.extend(f"• {_SIGNAL_LABELS[signal]}" for signal in health.signals)
        else:
            lines.extend(["", "سیگنال فعال: ندارد"])
        return self._single(
            "\n".join(lines),
            [
                [
                    {
                        "text": "🔄 بروزرسانی",
                        "callback_data": BotCallback(CallbackAction.RETRY, "ops").pack(),
                    }
                ],
                [
                    {
                        "text": "🏠 منوی مشتری",
                        "callback_data": BotCallback(CallbackAction.HOME).pack(),
                    }
                ],
            ],
        )

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action == CallbackAction.RETRY and callback.value == "ops":
            return self._operator_screen(user)
        return super()._route_callback(user, locale, callback, update_id)


class OperatorTelegramPollingRuntime(ServiceManagementTelegramPollingRuntime):
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
        self.handler = OperatorBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
