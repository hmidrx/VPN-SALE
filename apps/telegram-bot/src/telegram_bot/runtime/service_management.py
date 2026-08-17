"""Telegram-native service management UX layered over top-up, purchase and support."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from telegram_bot.application.identity import TelegramIdentityPort
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import ConversationStoreV2
from telegram_bot.internal_api import AuthoritativePrivateApiError, PrivateApiUnavailable
from telegram_bot.portal import CustomerPortalPort
from telegram_bot.runtime.handlers import HandlerResult, IncomingUser
from telegram_bot.runtime.native_topup_destination import (
    NativeTopupDestinationBotCommandHandler,
    NativeTopupDestinationTelegramPollingRuntime,
)
from telegram_bot.service_management_api import (
    ServiceManagementPortal,
    ServiceOperationEligibility,
)
from telegram_bot.transport.polling import TelegramTransport


class ServiceManagementBotCommandHandler(NativeTopupDestinationBotCommandHandler):
    @property
    def service_management(self) -> ServiceManagementPortal:
        return cast(ServiceManagementPortal, self.portal)

    def _eligibility(
        self, user: IncomingUser, locale: str, reference: str
    ) -> tuple[ServiceOperationEligibility, ...]:
        try:
            return self.service_management.service_management_eligibility(
                self._portal_context(user, locale), reference
            )
        except (PrivateApiUnavailable, AuthoritativePrivateApiError, AttributeError):
            return ()

    @staticmethod
    def _operation(
        rows: tuple[ServiceOperationEligibility, ...], operation_type: str
    ) -> ServiceOperationEligibility | None:
        return next((row for row in rows if row.operation_type == operation_type), None)

    def _management_rows(
        self,
        reference: str,
        eligibility: tuple[ServiceOperationEligibility, ...],
    ) -> list[list[dict[str, str]]]:
        buttons: list[dict[str, str]] = []
        renewal = self._operation(eligibility, "RENEW")
        traffic = self._operation(eligibility, "ADD_TRAFFIC")
        if renewal is not None and renewal.eligible:
            buttons.append(
                {
                    "text": "🔄 تمدید سرویس",
                    "callback_data": BotCallback(CallbackAction.RENEW, reference).pack(),
                }
            )
        if traffic is not None and traffic.eligible:
            buttons.append(
                {
                    "text": "➕ خرید حجم اضافه",
                    "callback_data": BotCallback(CallbackAction.EXTRA_TRAFFIC, reference).pack(),
                }
            )
        return [buttons] if buttons else []

    def _operation_screen(
        self,
        user: IncomingUser,
        locale: str,
        reference: str,
        operation_type: str,
    ) -> HandlerResult:
        eligibility = self._eligibility(user, locale, reference)
        operation = self._operation(eligibility, operation_type)
        if operation is None:
            return self._callback_message(
                "وضعیت این عملیات در حال حاضر قابل دریافت نیست. کمی بعد دوباره تلاش کنید.",
                self.renderer.nav_rows(locale),
            )
        if not operation.eligible:
            return self._callback_message(
                "این عملیات برای وضعیت فعلی سرویس قابل انجام نیست.",
                self.renderer.nav_rows(locale),
            )
        title = "🔄 تمدید سرویس" if operation_type == "RENEW" else "➕ خرید حجم اضافه"
        if operation.requires_authoritative_quote:
            return self._callback_message(
                f"{title}\n\n"
                "سرویس شما برای این عملیات مجاز است. مبلغ نهایی باید از سیستم قیمت‌گذاری "
                "مرکزی صادر و دوباره قبل از پرداخت تأیید شود.\n\n"
                "اتصال پرداخت مستقیم این عملیات داخل ربات در مرحله بعد همین توسعه فعال می‌شود؛ "
                "برای جلوگیری از مبلغ اشتباه، ربات قیمت را حدس نمی‌زند.",
                [
                    [
                        {
                            "text": "◀️ بازگشت به سرویس",
                            "callback_data": BotCallback(
                                CallbackAction.OPEN_SERVICE, reference
                            ).pack(),
                        }
                    ],
                    *self.renderer.nav_rows(locale),
                ],
            )
        return self._callback_message(title, self.renderer.nav_rows(locale))

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action in {CallbackAction.RENEW, CallbackAction.EXTRA_TRAFFIC}:
            if not callback.value:
                return self._stale(locale)
            operation_type = "RENEW" if callback.action == CallbackAction.RENEW else "ADD_TRAFFIC"
            return self._operation_screen(user, locale, callback.value, operation_type)

        result = super()._route_callback(user, locale, callback, update_id)
        if callback.action != CallbackAction.OPEN_SERVICE or not callback.value or not result.messages:
            return result
        eligibility = self._eligibility(user, locale, callback.value)
        management_rows = self._management_rows(callback.value, eligibility)
        if not management_rows:
            return result
        first = result.messages[0]
        existing_rows = [list(row) for row in first.rows]
        insert_at = max(len(existing_rows) - 1, 0)
        for row in reversed(management_rows):
            existing_rows.insert(insert_at, row)
        return replace(
            result,
            messages=(replace(first, rows=existing_rows), *result.messages[1:]),
        )


class ServiceManagementTelegramPollingRuntime(NativeTopupDestinationTelegramPollingRuntime):
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
        self.handler = ServiceManagementBotCommandHandler(
            settings,
            identity,
            portal=portal,
            conversations=conversations,
        )
