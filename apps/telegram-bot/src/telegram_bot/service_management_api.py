"""Telegram-native service management eligibility, quote and payment adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from telegram_bot.internal_api import PrivateApiUnavailable
from telegram_bot.portal import CustomerContext
from telegram_bot.topup_destination_api import NativeTopupPrivatePlatformClient


@dataclass(frozen=True)
class ServiceOperationQuoteOptions:
    unit: str
    minimum_amount: int
    maximum_amount: int
    increment: int
    suggested_amounts: tuple[int, ...]


@dataclass(frozen=True)
class ServiceOperationEligibility:
    operation_type: str
    eligible: bool
    billable: bool
    requires_authoritative_quote: bool
    safe_reason_codes: tuple[str, ...]
    quote_options: ServiceOperationQuoteOptions | None = None


@dataclass(frozen=True)
class ServiceOperationQuote:
    operation_reference: str
    service_id: str
    operation_type: str
    status: str
    amount: int
    price_rial: int
    currency: str
    expires_at: datetime
    policy_version_id: str


@dataclass(frozen=True)
class ServiceOperationPaymentResult:
    payment_reference: str
    operation_reference: str
    service_reference: str
    operation_type: str
    status: str
    amount_rial: int
    currency: str
    queued: bool


class ServiceManagementPortal(Protocol):
    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]: ...

    def service_operation_quote(
        self,
        context: CustomerContext,
        service_reference: str,
        operation_type: str,
        amount: int,
        idempotency_key: str,
    ) -> ServiceOperationQuote: ...

    def service_operation_pay(
        self,
        context: CustomerContext,
        operation_reference: str,
        idempotency_key: str,
    ) -> ServiceOperationPaymentResult: ...


class ServiceManagementPrivatePlatformClient(
    NativeTopupPrivatePlatformClient, ServiceManagementPortal
):
    @staticmethod
    def _quote_options(value: object) -> ServiceOperationQuoteOptions | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise PrivateApiUnavailable("گزینه‌های قیمت‌گذاری سرویس قابل استفاده نیست.")
        item = cast(dict[str, Any], value)
        unit = item.get("unit")
        minimum = item.get("minimum_amount")
        maximum = item.get("maximum_amount")
        increment = item.get("increment")
        raw_suggestions = item.get("suggested_amounts")
        if (
            unit not in {"DAY", "GIB"}
            or not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or not isinstance(increment, int)
            or isinstance(increment, bool)
            or minimum <= 0
            or maximum < minimum
            or increment <= 0
            or not isinstance(raw_suggestions, list)
        ):
            raise PrivateApiUnavailable("گزینه‌های قیمت‌گذاری سرویس قابل استفاده نیست.")
        suggestions = cast(list[object], raw_suggestions)
        if not suggestions or len(suggestions) > 8:
            raise PrivateApiUnavailable("گزینه‌های قیمت‌گذاری سرویس قابل استفاده نیست.")
        parsed: list[int] = []
        for raw in suggestions:
            if (
                not isinstance(raw, int)
                or isinstance(raw, bool)
                or raw < minimum
                or raw > maximum
                or raw % increment != 0
            ):
                raise PrivateApiUnavailable("گزینه‌های قیمت‌گذاری سرویس قابل استفاده نیست.")
            parsed.append(raw)
        return ServiceOperationQuoteOptions(unit, minimum, maximum, increment, tuple(parsed))

    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]:
        data = self._request(
            "GET",
            f"/service-management/{service_reference}/eligibility",
            context.telegram_user_id,
        )
        raw_operations_value = data.get("operations")
        if not isinstance(raw_operations_value, list):
            raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
        raw_operations = cast(list[object], raw_operations_value)
        if len(raw_operations) > 20:
            raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
        result: list[ServiceOperationEligibility] = []
        for raw in raw_operations:
            if not isinstance(raw, dict):
                raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
            item = cast(dict[str, Any], raw)
            operation_type = item.get("operation_type")
            eligible = item.get("eligible")
            billable = item.get("billable")
            quote_required = item.get("requires_authoritative_quote")
            reason_codes_value = item.get("safe_reason_codes")
            if not isinstance(reason_codes_value, list):
                raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
            reason_codes = cast(list[object], reason_codes_value)
            if (
                not isinstance(operation_type, str)
                or operation_type not in {"RENEW", "ADD_TRAFFIC"}
                or not isinstance(eligible, bool)
                or not isinstance(billable, bool)
                or not isinstance(quote_required, bool)
                or any(not isinstance(code, str) or len(code) > 80 for code in reason_codes)
            ):
                raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
            quote_options = self._quote_options(item.get("quote_options"))
            if eligible and quote_required and quote_options is None:
                raise PrivateApiUnavailable("گزینه‌های قیمت‌گذاری سرویس قابل استفاده نیست.")
            result.append(
                ServiceOperationEligibility(
                    operation_type=operation_type,
                    eligible=eligible,
                    billable=billable,
                    requires_authoritative_quote=quote_required,
                    safe_reason_codes=tuple(cast(list[str], reason_codes)),
                    quote_options=quote_options,
                )
            )
        return tuple(result)

    def service_operation_quote(
        self,
        context: CustomerContext,
        service_reference: str,
        operation_type: str,
        amount: int,
        idempotency_key: str,
    ) -> ServiceOperationQuote:
        if operation_type not in {"RENEW", "ADD_TRAFFIC"} or amount <= 0:
            raise ValueError("invalid service operation quote request")
        data = self._request(
            "POST",
            f"/service-management/{service_reference}/quotes",
            context.telegram_user_id,
            {"operation_type": operation_type, "amount": amount},
            idempotency_key,
        )
        returned_operation = data.get("operation_type")
        returned_amount = data.get("amount")
        price_rial = data.get("price_rial")
        currency = data.get("currency")
        if (
            returned_operation != operation_type
            or not isinstance(returned_amount, int)
            or isinstance(returned_amount, bool)
            or returned_amount != amount
            or not isinstance(price_rial, int)
            or isinstance(price_rial, bool)
            or price_rial <= 0
            or currency != "IRR"
        ):
            raise PrivateApiUnavailable("پاسخ قیمت‌گذاری سرویس معتبر نیست.")
        try:
            expires_at = datetime.fromisoformat(str(data["expires_at"]))
            operation_reference = str(data["operation_reference"])
            service_id = str(data["service_id"])
            status_value = str(data["status"])
            policy_version_id = str(data["policy_version_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivateApiUnavailable("پاسخ قیمت‌گذاری سرویس معتبر نیست.") from exc
        if (
            expires_at.tzinfo is None
            or not operation_reference
            or not service_id
            or status_value != "AWAITING_PAYMENT"
            or not policy_version_id
        ):
            raise PrivateApiUnavailable("پاسخ قیمت‌گذاری سرویس معتبر نیست.")
        return ServiceOperationQuote(
            operation_reference=operation_reference,
            service_id=service_id,
            operation_type=operation_type,
            status=status_value,
            amount=returned_amount,
            price_rial=price_rial,
            currency=currency,
            expires_at=expires_at,
            policy_version_id=policy_version_id,
        )

    def service_operation_pay(
        self,
        context: CustomerContext,
        operation_reference: str,
        idempotency_key: str,
    ) -> ServiceOperationPaymentResult:
        if not operation_reference:
            raise ValueError("invalid service operation payment request")
        data = self._request(
            "POST",
            f"/service-management/operations/{operation_reference}/pay",
            context.telegram_user_id,
            {},
            idempotency_key,
        )
        returned_operation_reference = data.get("operation_reference")
        service_reference = data.get("service_reference")
        operation_type = data.get("operation_type")
        status_value = data.get("status")
        amount_rial = data.get("amount_rial")
        currency = data.get("currency")
        queued = data.get("queued")
        payment_reference = data.get("payment_reference")
        if (
            returned_operation_reference != operation_reference
            or not isinstance(service_reference, str)
            or not service_reference
            or operation_type not in {"RENEW", "ADD_TRAFFIC"}
            or status_value not in {"QUEUED", "PENDING_APPROVAL"}
            or not isinstance(amount_rial, int)
            or isinstance(amount_rial, bool)
            or amount_rial <= 0
            or currency != "IRR"
            or not isinstance(queued, bool)
            or queued != (status_value == "QUEUED")
            or not isinstance(payment_reference, str)
            or not payment_reference
        ):
            raise PrivateApiUnavailable("پاسخ پرداخت عملیات سرویس معتبر نیست.")
        return ServiceOperationPaymentResult(
            payment_reference=payment_reference,
            operation_reference=operation_reference,
            service_reference=service_reference,
            operation_type=operation_type,
            status=status_value,
            amount_rial=amount_rial,
            currency="IRR",
            queued=queued,
        )
