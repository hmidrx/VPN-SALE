from __future__ import annotations

from datetime import UTC, datetime, timedelta

from platform_worker.service_usage_sync import build_safe_usage_projection

_SERVICE_ID = "11111111-1111-4111-8111-111111111111"
_ATTACHMENT_ID = "22222222-2222-4222-8222-222222222222"
_GIB = 1024**3


def _projection(
    *, combined: int | None, previous: int | None = None, allowance: int = 100 * _GIB
):
    return build_safe_usage_projection(
        service_id=_SERVICE_ID,
        attachment_id=_ATTACHMENT_ID,
        allowance_bytes=allowance,
        combined_bytes=combined,
        previous_combined_bytes=previous,
        observed_at=datetime(2026, 8, 18, 8, 0, tzinfo=UTC),
        expires_at=datetime(2026, 9, 18, 8, 0, tzinfo=UTC),
    )


def test_certified_counter_projects_real_remaining_traffic() -> None:
    result = _projection(combined=25 * _GIB, previous=20 * _GIB)

    assert result.used_bytes == 25 * _GIB
    assert result.remaining_bytes == 75 * _GIB
    assert result.consumed_percent == 25
    assert result.quota_state == "AVAILABLE"
    assert result.confidence == "HIGH"


def test_low_traffic_becomes_threshold_state_without_fabricating_exhaustion() -> None:
    result = _projection(combined=92 * _GIB, previous=90 * _GIB)

    assert result.remaining_bytes == 8 * _GIB
    assert result.quota_state == "WARNING"
    assert result.explanation_code == "PRIMARY_COUNTER"


def test_counter_decrease_fails_closed_instead_of_increasing_customer_remaining() -> None:
    result = _projection(combined=10 * _GIB, previous=70 * _GIB)

    assert result.used_bytes is None
    assert result.remaining_bytes is None
    assert result.quota_state == "MANUAL_REVIEW"
    assert result.confidence == "UNUSABLE"
    assert result.explanation_code == "COUNTER_DECREASE_UNEXPLAINED"


def test_missing_provider_counter_is_unknown_not_zero() -> None:
    result = _projection(combined=None, previous=40 * _GIB)

    assert result.used_bytes is None
    assert result.remaining_bytes is None
    assert result.quota_state == "UNKNOWN"
    assert result.explanation_code == "COUNTER_UNAVAILABLE"


def test_expiry_state_is_derived_from_service_expiry_not_provider_display() -> None:
    now = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    result = build_safe_usage_projection(
        service_id=_SERVICE_ID,
        attachment_id=_ATTACHMENT_ID,
        allowance_bytes=100 * _GIB,
        combined_bytes=10 * _GIB,
        previous_combined_bytes=9 * _GIB,
        observed_at=now,
        expires_at=now + timedelta(hours=12),
    )

    assert result.expiry_state == "CRITICAL"
