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
    ServiceOperationStatus,
)
from telegram_bot.transport.polling import TelegramTransport

_REVIEW_STATUSES = frozenset(
    {
        "PARTIALLY_APPLIED",
        "FAILED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "MANUAL_REVIEW",
        "CANCELLED",
        "EXPIRED",
    }
)
_BLOCKER_IN_PROGRESS = "SERVICE_OPERATION_IN_PROGRESS"
_BLOCKER_REVIEW_REQUIRED = "SERVICE_OPERATION_REVIEW_REQUIRED"
_SERVICE_NOT_ELIGIBLE = "SERVICE_NOT_ELIGIBLE"
_POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"


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

    @staticmethod
    def _reason_codes(rows: tuple[ServiceOperationEligibility, ...]) -> frozenset[str]:
        return frozenset(code for row in rows for code in row.safe_reason_codes)

    def _management_rows(
        self,
        reference: str,
        eligibility: tuple[ServiceOperationEligibility, ...],
    ) -> list[list[dict[str, str]]]:
        reason_codes = self._reason_codes(eligibility)
        if _BLOCKER_REVIEW_REQUIRED in reason_codes:
            return [
                [
                    {
                        "text": "⚠️ عملیات قبلی نیازمند بررسی است",
                        "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                    }
                ]
            ]
        if _BLOCKER_IN_PROGRESS in reason_codes:
            return [
                [
                    {
                        "text": "⏳ عملیات سرویس در حال انجام است",
                        "callback_data": BotCallback(CallbackAction.OPEN_SERVICE, reference).pack(),
                    }
                ]
            ]

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
    def _ineligible_copy(operation: ServiceOperationEligibility) -> str:
        reason_codes = frozenset(operation.safe_reason_codes)
        if _BLOCKER_REVIEW_REQUIRED in reason_codes:
            return (
                "⚠️ نتیجه عملیات قبلی این سرویس نیاز به بررسی دارد.\n\n"
                "تا مشخص‌شدن نتیجه نهایی، برای تمدید یا خرید حجم اضافه دوباره پرداخت نکنید. "
                "در صورت نیاز از بخش پشتیبانی پیگیری کنید."
            )
        if _BLOCKER_IN_PROGRESS in reason_codes:
            return (
                "⏳ یک عملیات دیگر برای این سرویس در حال انجام است.\n\n"
                "تا نهایی‌شدن آن، درخواست یا پرداخت جدید ثبت نکنید. "
                "کمی بعد وضعیت سرویس را دوباره بررسی کنید."
            )
        if _SERVICE_NOT_ELIGIBLE in reason_codes:
            return "این عملیات برای وضعیت فعلی سرویس قابل انجام نیست."
        if _POLICY_UNAVAILABLE in reason_codes:
            return "قیمت‌گذاری این عملیات موقتاً در دسترس نیست. کمی بعد دوباره تلاش کنید."
        return "این عملیات برای وضعیت فعلی سرویس قابل انجام نیست."

    def _ineligible_rows(
        self,
        locale: str,
        reference: str,
        operation: ServiceOperationEligibility,
    ) -> list[list[dict[str, str]]]:
        rows: list[list[dict[str, str]]] = []
        reason_codes = frozenset(operation.safe_reason_codes)
        if _BLOCKER_REVIEW_REQUIRED in reason_codes:
            rows.append(
                [
                    {
                        "text": "💬 پشتیبانی",
                        "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "🔄 بررسی دوباره سرویس",
                    "callback_data": BotCallback(CallbackAction.OPEN_SERVICE, reference).pack(),
                }
            ]
        )
        return [*rows, *self.renderer.nav_rows(locale)]

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
                self._ineligible_copy(operation),
                self._ineligible_rows(locale, reference, operation),
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
            "از این مرحله به بعد وضعیت واقعی اجرا را از دکمه پیگیری ببینید. "
            "تکرار پرداخت لازم نیست و باعث نتیجه سریع‌تر نمی‌شود.",
            [
                [
                    {
                        "text": "⏳ پیگیری وضعیت",
                        "callback_data": BotCallback(
                            CallbackAction.SERVICE_OPERATION_STATUS,
                            payment.operation_reference,
                        ).pack(),
                    }
                ],
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

    @staticmethod
    def _status_copy(status: ServiceOperationStatus) -> tuple[str, str]:
        if status.status == "AWAITING_PAYMENT":
            return "⏳ منتظر پرداخت", "این درخواست هنوز پرداخت نشده است."
        if status.status == "PENDING_APPROVAL":
            return (
                "🕓 منتظر تأیید",
                "پرداخت ثبت شده و درخواست منتظر تأیید است. نیازی به پرداخت دوباره نیست.",
            )
        if status.status == "QUEUED":
            return (
                "🕓 در صف اجرا",
                "پرداخت ثبت شده و درخواست در صف اجرای امن است. نیازی به پرداخت دوباره نیست.",
            )
        if status.status == "EXECUTING":
            return (
                "⚙️ در حال اجرا",
                "تغییر در حال اعمال روی سرویس است. نیازی به پرداخت دوباره نیست.",
            )
        if status.status == "VERIFYING":
            return (
                "🔍 در حال تأیید نتیجه",
                "سامانه در حال بررسی نتیجه نهایی تغییر روی سرویس است.",
            )
        if status.status == "RECONCILING":
            return (
                "🔍 در حال تطبیق نتیجه",
                "نتیجه با وضعیت واقعی سرویس در حال تطبیق است. دوباره پرداخت نکنید.",
            )
        if status.status == "SUCCEEDED":
            return "✅ انجام شد", "عملیات با موفقیت روی سرویس اعمال و تأیید شد."
        if status.status == "COMPENSATED":
            return (
                "↩️ عملیات جبران شد",
                "فرآیند جبران ثبت شده است. برای وضعیت مالی، کیف پول را بررسی کنید.",
            )
        return (
            "⚠️ نیازمند بررسی",
            "پرداخت یا درخواست قبلی محفوظ است و وضعیت برای بررسی ثبت شده است. "
            "لطفاً دوباره پرداخت نکنید.",
        )

    def _render_operation_status(
        self, locale: str, operation_status: ServiceOperationStatus
    ) -> HandlerResult:
        renewal = operation_status.operation_type == "RENEW"
        operation_label = "تمدید سرویس" if renewal else "افزایش حجم"
        quantity = (
            f"{operation_status.amount:,} روز"
            if operation_status.unit == "DAY"
            else f"{operation_status.amount:,} گیگابایت"
        )
        title, detail = self._status_copy(operation_status)
        rows: list[list[dict[str, str]]] = []
        if operation_status.status != "SUCCEEDED":
            rows.append(
                [
                    {
                        "text": "🔄 بروزرسانی وضعیت",
                        "callback_data": BotCallback(
                            CallbackAction.SERVICE_OPERATION_STATUS,
                            operation_status.operation_reference,
                        ).pack(),
                    }
                ]
            )
        rows.append(
            [
                {
                    "text": "📦 مشاهده سرویس",
                    "callback_data": BotCallback(
                        CallbackAction.OPEN_SERVICE, operation_status.service_reference
                    ).pack(),
                }
            ]
        )
        if operation_status.status in _REVIEW_STATUSES:
            rows.append(
                [
                    {
                        "text": "💬 پشتیبانی",
                        "callback_data": BotCallback(CallbackAction.SUPPORT).pack(),
                    },
                    {
                        "text": "💰 کیف پول",
                        "callback_data": BotCallback(CallbackAction.WALLET).pack(),
                    },
                ]
            )
        return self._callback_message(
            f"{title}\n\n" f"عملیات: {operation_label}\n" f"مقدار: {quantity}\n\n" f"{detail}",
            [*rows, *self.renderer.nav_rows(locale)],
        )

    def _status_screen(
        self,
        user: IncomingUser,
        locale: str,
        operation_reference: str,
    ) -> HandlerResult:
        try:
            operation_status = self.service_management.service_operation_status(
                self._portal_context(user, locale), operation_reference
            )
        except AuthoritativePrivateApiError:
            return self._callback_message(
                "این درخواست برای حساب شما پیدا نشد یا دیگر قابل مشاهده نیست.",
                self.renderer.nav_rows(locale),
            )
        except (PrivateApiUnavailable, AttributeError, ValueError):
            return self._callback_message(
                "وضعیت عملیات موقتاً قابل دریافت نیست. کمی بعد دوباره بررسی کنید؛ "
                "اگر پرداخت ثبت شده باشد، دوباره پرداخت نکنید.",
                [
                    [
                        {
                            "text": "🔄 تلاش دوباره",
                            "callback_data": BotCallback(
                                CallbackAction.SERVICE_OPERATION_STATUS,
                                operation_reference,
                            ).pack(),
                        }
                    ],
                    *self.renderer.nav_rows(locale),
                ],
            )
        return self._render_operation_status(locale, operation_status)

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

        if callback.action == CallbackAction.SERVICE_OPERATION_STATUS:
            if not callback.value:
                return self._stale(locale)
            return self._status_screen(user, locale, callback.value)

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
