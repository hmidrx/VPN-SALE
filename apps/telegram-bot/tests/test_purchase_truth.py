from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from telegram_bot.internal_api import PrivatePlatformClient
from telegram_bot.portal import PurchasePlan, PurchaseResult
from telegram_bot.runtime.purchase_truth import purchase_status_text


def _plan() -> PurchasePlan:
    return PurchasePlan(
        "p_safe",
        "پلن تست",
        50,
        30,
        1,
        "de",
        "آلمان",
        "standard",
        100_000,
        {},
    )


def _result(
    purchase_state: str,
    *,
    fulfillment_status: str = "SUCCEEDED",
    service_reference: str | None = None,
    service_lifecycle: str | None = None,
    delivery_ready: bool = False,
    refunded: bool = False,
) -> PurchaseResult:
    return PurchaseResult(
        order_reference="ord_12345678",
        status="PAID",
        fulfillment_status=fulfillment_status,
        plan=_plan(),
        service_reference=service_reference,
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
        refunded=refunded,
        purchase_state=purchase_state,
        service_lifecycle=service_lifecycle,
        delivery_ready=delivery_ready,
    )


def test_purchase_status_distinguishes_provisioning_pending_delivery_and_operator_review() -> None:
    provisioning = purchase_status_text(
        _result("PROVISIONING", fulfillment_status="PROVISIONING")
    )
    pending_delivery = purchase_status_text(
        _result(
            "PENDING_DELIVERY",
            service_reference="svc_pending",
            service_lifecycle="PENDING_ACTIVATION",
        )
    )
    operator_review = purchase_status_text(_result("OPERATOR_REVIEW"))

    assert "در حال انجام" in provisioning
    assert "تحویل کانفیگ هنوز آماده نیست" in pending_delivery
    assert "نیازمند بررسی اپراتور" in operator_review
    assert "سرویس شما فعال شد" not in provisioning
    assert "سرویس شما فعال شد" not in pending_delivery
    assert "سرویس شما فعال شد" not in operator_review


def test_purchase_status_announces_active_only_for_authoritative_delivery_truth() -> None:
    active = purchase_status_text(
        _result(
            "ACTIVE",
            service_reference="svc_abcdefgh",
            service_lifecycle="ACTIVE",
            delivery_ready=True,
        )
    )
    pending_delivery = purchase_status_text(
        _result(
            "ACTIVE",
            service_reference="svc_abcdefgh",
            service_lifecycle="PENDING_ACTIVATION",
            delivery_ready=False,
        )
    )
    missing_reference = purchase_status_text(
        _result("ACTIVE", service_lifecycle="ACTIVE", delivery_ready=True)
    )

    assert "✅ سرویس شما فعال شد" in active
    assert "✅ سرویس شما فعال شد" not in pending_delivery
    assert "تحویل کانفیگ هنوز آماده نیست" in pending_delivery
    assert "✅ سرویس شما فعال شد" not in missing_reference


def test_purchase_status_refund_is_explicit() -> None:
    text = purchase_status_text(_result("REFUNDED", refunded=True))
    assert "به کیف پول شما بازگردانده شد" in text


def test_private_api_mapping_preserves_independent_purchase_truth(tmp_path: Path) -> None:
    token_file = tmp_path / "telegram-internal-token"
    token_file.write_text("x" * 32, encoding="utf-8")
    client = PrivatePlatformClient("http://internal", str(token_file))

    result = client._purchase_result(
        {
            "order_reference": "ord_truth",
            "status": "PAID",
            "fulfillment_status": "SUCCEEDED",
            "purchase_state": "PENDING_DELIVERY",
            "service_lifecycle": "PENDING_ACTIVATION",
            "delivery_ready": False,
            "service_reference": "svc_provider_created",
            "expires_at": None,
            "refunded": False,
            "outcome": "ACCEPTED",
            "plan": {
                "reference": "p_safe",
                "title": "پلن تست",
                "traffic_gb": 50,
                "duration_days": 30,
                "device_limit": 1,
                "location_code": "de",
                "location_label": "آلمان",
                "quality_code": "standard",
                "price_toman": 100_000,
                "selection": {},
            },
        }
    )

    assert result.fulfillment_status == "SUCCEEDED"
    assert result.purchase_state == "PENDING_DELIVERY"
    assert result.service_lifecycle == "PENDING_ACTIVATION"
    assert result.delivery_ready is False
    assert result.service_reference == "svc_provider_created"
    assert "سرویس شما فعال شد" not in purchase_status_text(result)
