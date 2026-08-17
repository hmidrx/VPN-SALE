"""Telegram-native service management eligibility adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from telegram_bot.internal_api import PrivateApiUnavailable
from telegram_bot.portal import CustomerContext
from telegram_bot.topup_destination_api import NativeTopupPrivatePlatformClient


@dataclass(frozen=True)
class ServiceOperationEligibility:
    operation_type: str
    eligible: bool
    billable: bool
    requires_authoritative_quote: bool
    safe_reason_codes: tuple[str, ...]


class ServiceManagementPortal(Protocol):
    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]: ...


class ServiceManagementPrivatePlatformClient(
    NativeTopupPrivatePlatformClient, ServiceManagementPortal
):
    def service_management_eligibility(
        self, context: CustomerContext, service_reference: str
    ) -> tuple[ServiceOperationEligibility, ...]:
        data = self._request(
            "GET",
            f"/service-management/{service_reference}/eligibility",
            context.telegram_user_id,
        )
        raw_operations = data.get("operations")
        if not isinstance(raw_operations, list) or len(raw_operations) > 20:
            raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
        result: list[ServiceOperationEligibility] = []
        for raw in cast(list[object], raw_operations):
            if not isinstance(raw, dict):
                raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
            item = cast(dict[str, Any], raw)
            operation_type = item.get("operation_type")
            eligible = item.get("eligible")
            billable = item.get("billable")
            quote_required = item.get("requires_authoritative_quote")
            reason_codes = item.get("safe_reason_codes")
            if (
                not isinstance(operation_type, str)
                or operation_type not in {"RENEW", "ADD_TRAFFIC"}
                or not isinstance(eligible, bool)
                or not isinstance(billable, bool)
                or not isinstance(quote_required, bool)
                or not isinstance(reason_codes, list)
                or any(not isinstance(code, str) or len(code) > 80 for code in reason_codes)
            ):
                raise PrivateApiUnavailable("وضعیت مدیریت سرویس قابل استفاده نیست.")
            result.append(
                ServiceOperationEligibility(
                    operation_type=operation_type,
                    eligible=eligible,
                    billable=billable,
                    requires_authoritative_quote=quote_required,
                    safe_reason_codes=tuple(cast(list[str], reason_codes)),
                )
            )
        return tuple(result)
