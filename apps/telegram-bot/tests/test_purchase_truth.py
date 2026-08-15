from __future__ import annotations

from datetime import UTC, datetime

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
    state: str,
    *,
    service_reference: str | None = None,
    refunded: bool = False,
    lifecycle: str | None = None,
    delivery_ready: bool = False,
    fulfillment_status: str = "SUCCEEDED",
) -> PurchaseResult:
    return PurchaseResult(
        "ord_12345678",
        "PAID",
        fulfillment_status,
        _plan(),
        service_reference,
        datetime(2026, 9, 1, tzinfo=UTC),
        refunded=refunded,
        purchase_state=state,
        service_lifecycle=lifecycle,
        delivery_ready=delivery_ready,
    )


def test_purchase_status_distinguishes_provisioning_pending_delivery_and_operator_review() -> None:
    provisioning = purchase_status_text(_result("PROVISIONING"))
    pending_delivery = purchase_status_text(_result("PENDING_DELIVERY"))
    operator_review = purchase_status_text(_result("OPERATOR_REVIEW"))

    assert "در حال انجام" in provisioning
    assert "تحویل کانفیگ هنوز آماده نیست" in pending_delivery
    assert "نیازمند بررسی اپراتور" in operator_review
    assert "سرویس شما فعال شد" not in provisioning
    assert "سرویس شما فعال شد" not in pending_delivery
    assert "سرویس شما فعال شد" not in operator_review


def test_purchase_status_announces_active_only_for_delivery_ready_projection() -> None:
    active = purchase_status_text(
        _result(
            "ACTIVE",
            service_reference="svc_abcdefgh",
            lifecycle="ACTIVE",
            delivery_ready=True,
        )
    )
    inconsistent = purchase_status_text(
        _result("ACTIVE", service_reference="svc_abcdefgh", lifecycle="ACTIVE")
    )

    assert "✅ سرویس شما فعال شد" in active
    assert "✅ سرویس شما فعال شد" not in inconsistent
    assert "تحویل کانفیگ هنوز آماده نیست" in inconsistent


def test_purchase_status_refund_is_explicit() -> None:
    text = purchase_status_text(_result("REFUNDED", refunded=True))
    assert "به کیف پول شما بازگردانده شد" in text
