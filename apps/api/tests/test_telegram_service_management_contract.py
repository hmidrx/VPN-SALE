from __future__ import annotations

from platform_api.telegram_service_management_internal import (
    CUSTOMER_NATIVE_OPERATION_TYPES,
)


def test_telegram_native_management_scope_stays_customer_safe() -> None:
    assert tuple(item.value for item in CUSTOMER_NATIVE_OPERATION_TYPES) == (
        "RENEW",
        "ADD_TRAFFIC",
    )
