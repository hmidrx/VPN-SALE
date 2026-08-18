from __future__ import annotations

from telegram_bot.internal_api import PrivatePlatformClient
from telegram_bot.portal import CustomerContext

_GIB = 1024**3


def _payload(usage: object) -> dict[str, object]:
    return {
        "reference": "svc-safe",
        "plan_name": "پلن استاندارد",
        "status": "ACTIVE",
        "expires_at": "2026-09-18T08:00:00+00:00",
        "traffic_entitlement_bytes": 100 * _GIB,
        "location": "Germany",
        "renewable": True,
        "usage": usage,
    }


def test_private_client_uses_fresh_usage_remaining_bytes_when_present() -> None:
    context = CustomerContext("customer-safe", 42, "fa")
    service = PrivatePlatformClient._service_summary(  # pyright: ignore[reportPrivateUsage]
        _payload({"remaining_bytes": 37 * _GIB}), context
    )

    assert service.total_gb == 100
    assert service.remaining_gb == 37


def test_private_client_keeps_remaining_unknown_when_projection_is_absent() -> None:
    context = CustomerContext("customer-safe", 42, "fa")
    service = PrivatePlatformClient._service_summary(  # pyright: ignore[reportPrivateUsage]
        _payload(None), context
    )

    assert service.total_gb == 100
    assert service.remaining_gb is None
