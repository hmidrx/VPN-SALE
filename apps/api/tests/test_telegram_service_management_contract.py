from __future__ import annotations

from platform_api.telegram_service_management_internal import _CUSTOMER_NATIVE


def test_telegram_native_management_scope_stays_customer_safe() -> None:
    assert tuple(item.value for item in _CUSTOMER_NATIVE) == ("RENEW", "ADD_TRAFFIC")
