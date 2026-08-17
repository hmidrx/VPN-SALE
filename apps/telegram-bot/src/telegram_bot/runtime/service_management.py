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
    ServiceOperationPaymentResult,
    ServiceOperationQuote,
    ServiceOperationQuoteOptions,
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

    @staticmethod
    def _amount_label(amount: int, options: ServiceOperationQuoteOptions) -> str:
        return f"{amount} روز" if options.unit == "DAY" else f"{amount} گیگابایت"

    @staticmethod
    def _quote_action(operation_type: str) -> CallbackAction:
        return (
            CallbackAction.RENEW_QUOTE
            if operation_type == "RENEW"
            else CallbackAction.EXTRA_TRAFFIC_QUOTE
        )

    def _quote_rows(
        self,
        reference: str,
        operation_type: str,
        options: ServiceOperationQuoteOptions,
    ) -> list[list[dict[str, str]]]:
        buttons: list[dict[str, str]] = []
        for amount in options.suggested_amounts:
            try:
                callback_data = BotCallback(
                    self._quote_action(operation_type), f"{reference},{amount}"
                ).pack()
            except ValueError:
                continue
            buttons.append(
                {"text": self._amount_label(amount, options), "callback_data": callback_data}
            )
        return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]

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
        options = operation.quote_options
        if operation.requires_authoritative_quote and options is not None:
            unit = "روز" if options.unit == "DAY" else "گیگابایت"
            rows = self._quote_rows(reference, operation_type, options)
            if not rows:
                return self._callback_message(
                    "گزینه معتبر برای صدور قیمت در حال حاضر در دسترس نیست.",
                    self.renderer.nav_rows(locale),
                )
            return self._callback_message(
                f"{title}\n\n"
                f"مقدار موردنظر را انتخاب کنید. بازه مجاز: {options.minimum_amount:,} تا "
                f"{options.maximum_amount:,} {unit}.\n"
                f"گام مجاز: {options.increment:,} {unit}.\n\n"
                "مبلغ بعد از انتخاب، مستقیم از قیمت‌گذاری مرکزی و به‌صورت موقت صادر می‌شود.",
                [
                    *rows,
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
        return self._callback_message(
            "قیمت معتبر این عملیات در حال حاضر قابل دریافت نیست.",
            self.renderer.nav_rows(locale),
        )

    @staticmethod
    def _quote_selection(value: str) -> tuple[str, int] | None:
        reference, separator, raw_amount = value.rpartition(",")
        if not separator or not reference or not raw_amount.isascii() or not raw_amount.isdigit():
            return None
        amount = int(raw_amount)
        if amount <= 0:
            return None
        return reference, amount

    @staticmethod
    def _quote_idempotency_key(
        user: IncomingUser, update_id: int, operation_type: str, amount: int
    ) -> str:
        return f"svcq:{user.telegram_user_id}:{update_id}:{operation_type}:{amount}"

    @staticmethod
    def _payment_idempotency_key(
        user: IncomingUser, update_id: int, operation_reference: str
    ) -> str:
        return f"svcp:{user.telegram_user_id}:{update_id}:{operation_reference}"

    def _quote_screen(
        self,
        user: IncomingUser,
        locale: str,
        reference: str,
        operation_type: str,
        amount: int,
        update_id: int,
    ) -> HandlerResult:
        try:
            quote = self.service_management.service_operation_quote(
                self._portal_context(user, locale),
                reference,
                operation_type,
                amount,
                self._quote_idempotency_key(user, update_id, operation_type, amount),
            )
        except AuthoritativePrivateApiError:
            return self._callback_message(
                "قیمت این انتخاب دیگر معتبر نیست. گزینه‌های سرویس را دوباره باز کنید.",
                self.renderer.nav_rows(locale),
            )
        except (PrivateApiUnavailable, AttributeError, ValueError):
            return self._callback_message(
                "صدور قیمت موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید.",
                self.renderer.nav_rows(locale),
            )
        return self._render_quote(locale, reference, quote)

    def _render_quote(
        self, locale: str, reference: str, quote: ServiceOperationQuote
    ) -> HandlerResult:
        renewal = quote.operation_type == "RENEW"
        title = "🔄 قیمت تمدید سرویس" if renewal else "➕ قیمت حجم اضافه"
        quantity = f"{quote.amount:,} روز" if renewal else f"{quote.amount:,} گیگابایت"
        back_action = CallbackAction.RENEW if renewal else CallbackAction.EXTRA_TRAFFIC
        return self._callback_message(
            f"{title}\n\n"
            f"مقدار: {quantity}\n"
            f"مبلغ نهایی: {quote.price_rial:,} ریال\n\n"
            "این مبلغ از policy فعال سرور صادر شده و هنگام پرداخت دوباره اعتبارسنجی می‌شود. "
            "هیچ مبلغی از callback تلگرام پذیرفته نمی‌شود.",
            [
                [
                    {
                        "text": "💳 پرداخت از کیف پول",
                        "callback_data": BotCallback(
                            CallbackAction.SERVICE_OPERATION_PAY,
                            quote.operation_reference,
                        ).pack(),
                    }
                ],
                [
                    {
                        "text": "🔁 انتخاب مقدار دیگر",
                        "callback_data": BotCallback(back_action, reference).pack(),
                    }
                ],
                [
                    {
                        "text": "◀️ بازگشت به سرویس",
                        "callback_data": BotCallback(CallbackAction.OPEN_SERVICE, reference).pack(),
                    }
                ],
                *self.renderer.nav_rows(locale),
            ],
        )

    def _render_payment_success(
        self, locale: str, payment: ServiceOperationPaymentResult
    ) -> HandlerResult:
        operation_label = "تمدید سرویس" if payment.operation_type == "RENEW" else "افزایش حجم"
        state_text = (
            "درخواست وارد صف اجرای امن شد."
            if payment.status == "QUEUED"
            else "پرداخت ثبت شد و درخواست منتظر تأیید است."
        )
        return self._callback_message(
            f"✅ پرداخت {operation_label} ثبت شد\n\n"
            f"مبلغ: {payment.amount_rial:,} ریال\n"
            f"{state_text}\n\n"
            "برداشت وجه و ثبت درخواست به‌صورت اتمیک انجام شده است؛ "
            "تکرار درخواست باعث برداشت دوباره نمی‌شود.",
            [
                [
                    {
                        "text": "📦 مشاهده سرویس",
                        "callback_data": BotCallback(
                            CallbackAction.OPEN_SERVICE, payment.service_reference
                        ).pack(),
                    },
                    {
                        "text": "💰 کیف پول",
                        "callback_data": BotCallback(CallbackAction.WALLET).pack(),
                    },
                ],
                *self.renderer.nav_rows(locale),
            ],
        )

    def _payment_screen(
        self,
        user: IncomingUser,
        locale: str,
        operation_reference: str,
        update_id: int,
    ) -> HandlerResult:
        try:
            payment = self.service_management.service_operation_pay(
                self._portal_context(user, locale),
                operation_reference,
                self._payment_idempotency_key(user, update_id, operation_reference),
            )
        except AuthoritativePrivateApiError as exc:
            if exc.status_code == 402:
                return self._callback_message(
                    "موجودی کیف پول برای این پرداخت کافی نیست. "
                    "ابتدا کیف پول را شارژ کنید و سپس دوباره همین عملیات را باز کنید.",
                    [
                        [
                            {
                                "text": "➕ شارژ کیف پول",
                                "callback_data": BotCallback(CallbackAction.TOP_UP).pack(),
                            }
                        ],
                        *self.renderer.nav_rows(locale),
                    ],
                )
            return self._callback_message(
                "این قیمت یا وضعیت سرویس دیگر برای پرداخت معتبر نیست. "
                "سرویس را دوباره باز کنید و قیمت جدید بگیرید.",
                self.renderer.nav_rows(locale),
            )
        except (PrivateApiUnavailable, AttributeError, ValueError):
            return self._callback_message(
                "نتیجه پرداخت موقتاً قابل دریافت نیست. دوباره تلاش کردن امن است؛ "
                "اگر پرداخت قبلاً ثبت شده باشد، سیستم همان نتیجه را برمی‌گرداند "
                "و دوباره از کیف پول کم نمی‌کند.",
                self.renderer.nav_rows(locale),
            )
        return self._render_payment_success(locale, payment)

    def _route_callback(
        self, user: IncomingUser, locale: str, callback: BotCallback, update_id: int
    ) -> HandlerResult:
        if callback.action in {CallbackAction.RENEW, CallbackAction.EXTRA_TRAFFIC}:
            if not callback.value:
                return self._stale(locale)
            operation_type = "RENEW" if callback.action == CallbackAction.RENEW else "ADD_TRAFFIC"
            return self._operation_screen(user, locale, callback.value, operation_type)

        if callback.action in {CallbackAction.RENEW_QUOTE, CallbackAction.EXTRA_TRAFFIC_QUOTE}:
            selection = self._quote_selection(callback.value)
            if selection is None:
                return self._stale(locale)
            reference, amount = selection
            operation_type = (
                "RENEW" if callback.action == CallbackAction.RENEW_QUOTE else "ADD_TRAFFIC"
            )
            return self._quote_screen(user, locale, reference, operation_type, amount, update_id)

        if callback.action == CallbackAction.SERVICE_OPERATION_PAY:
            if not callback.value:
                return self._stale(locale)
            return self._payment_screen(user, locale, callback.value, update_id)

        result = super()._route_callback(user, locale, callback, update_id)
        if (
            callback.action != CallbackAction.OPEN_SERVICE
            or not callback.value
            or not result.messages
        ):
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
