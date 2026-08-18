from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel
from platform_api.usage_models import ServiceUsageAccountModel, ServiceUsageAggregateModel
from platform_worker import service_traffic_notification
from platform_worker.main import main
from platform_worker.service_traffic_notification import (
    InvalidServiceTrafficNotification,
    ServiceTrafficNotificationTarget,
    ServiceTrafficNotificationWorker,
    StaleServiceTrafficNotification,
    _callback_data,
    _event_key,
    _notification_text,
    _remaining_text,
    _should_notify,
    _stage_for_state,
)

_NOW = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
_GIB = 1024**3


def _service(
    *,
    lifecycle: str = "ACTIVE",
    reference: str = "SVC-TRAFFIC",
) -> ServiceModel:
    return cast(
        ServiceModel,
        SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            public_reference=reference,
            beneficiary_customer_id="22222222-2222-4222-8222-222222222222",
            lifecycle=lifecycle,
        ),
    )


def _account(service: ServiceModel) -> ServiceUsageAccountModel:
    return cast(
        ServiceUsageAccountModel,
        SimpleNamespace(
            id="33333333-3333-4333-8333-333333333333",
            service_id=service.id,
        ),
    )


def _aggregate(
    account: ServiceUsageAccountModel,
    *,
    aggregate_id: str = "44444444-4444-4444-8444-444444444444",
    state: str = "WARNING",
    observed_at: datetime = _NOW,
    remaining_bytes: int | None = 18 * _GIB,
    consumed_percent: int | None = 82,
    confidence: str = "HIGH",
) -> ServiceUsageAggregateModel:
    return cast(
        ServiceUsageAggregateModel,
        SimpleNamespace(
            id=aggregate_id,
            usage_account_id=account.id,
            quota_state=state,
            latest_observed_at=observed_at,
            remaining_bytes=remaining_bytes,
            consumed_percent=consumed_percent,
            confidence=confidence,
        ),
    )


def _event(
    service: ServiceModel,
    account: ServiceUsageAccountModel,
    aggregate: ServiceUsageAggregateModel,
    stage: str,
) -> TransactionalOutboxModel:
    return cast(
        TransactionalOutboxModel,
        SimpleNamespace(
            payload={
                "service_id": service.id,
                "usage_account_id": account.id,
                "aggregate_id": aggregate.id,
                "stage": stage,
            }
        ),
    )


def test_only_upward_authoritative_threshold_crossings_notify() -> None:
    assert _stage_for_state("WARNING") == "WARNING"
    assert _stage_for_state("CRITICAL") == "CRITICAL"
    assert _stage_for_state("EXHAUSTED_CONFIRMED") == "EXHAUSTED"
    assert _stage_for_state("EXHAUSTED_PENDING_CONFIRMATION") is None
    assert _stage_for_state("UNKNOWN") is None

    assert _should_notify("WARNING", "AVAILABLE")
    assert not _should_notify("WARNING", "WARNING")
    assert _should_notify("CRITICAL", "WARNING")
    assert not _should_notify("WARNING", "CRITICAL")
    assert _should_notify("EXHAUSTED_CONFIRMED", "EXHAUSTED_PENDING_CONFIRMATION")
    assert not _should_notify("EXHAUSTED_PENDING_CONFIRMATION", "CRITICAL")


def test_event_key_and_native_callback_are_bounded_and_secret_free() -> None:
    service = _service(reference="S" * 48)
    account = _account(service)
    aggregate = _aggregate(account)

    event_key = _event_key(aggregate, "WARNING")
    callback = _callback_data(service.public_reference)

    assert aggregate.id in event_key
    assert len(event_key) <= 120
    assert callback == f"b:v1:svc_open:{service.public_reference}"
    assert len(callback.encode()) <= 64
    assert "http" not in callback
    assert "token" not in callback.lower()


def test_customer_copy_distinguishes_warning_critical_and_confirmed_exhaustion() -> None:
    base = {
        "service_reference": "SVC-1",
        "customer_id": "customer",
        "remaining_bytes": 8 * _GIB,
        "consumed_percent": 92,
    }
    warning = _notification_text(ServiceTrafficNotificationTarget(stage="WARNING", **base))
    critical = _notification_text(ServiceTrafficNotificationTarget(stage="CRITICAL", **base))
    exhausted = _notification_text(ServiceTrafficNotificationTarget(stage="EXHAUSTED", **base))

    assert "رو به اتمام" in warning
    assert "تقریباً تمام" in critical
    assert "تمام شده" in exhausted
    assert "8 گیگابایت" in warning
    for text in (warning, critical, exhausted):
        assert "provider" not in text.lower()
        assert "panel" not in text.lower()
        assert "remote" not in text.lower()


def test_remaining_text_is_customer_safe_for_small_and_large_values() -> None:
    assert _remaining_text(8 * _GIB) == "8 گیگابایت"
    assert _remaining_text(512 * 1024**2) == "512 مگابایت"
    assert _remaining_text(0) == "0 مگابایت"
    assert _remaining_text(None) == "نامشخص"


def test_target_revalidates_fresh_current_usage_before_delivery() -> None:
    service = _service()
    account = _account(service)
    source = _aggregate(account)
    newer_same_stage = _aggregate(
        account,
        aggregate_id="55555555-5555-4555-8555-555555555555",
        remaining_bytes=15 * _GIB,
        consumed_percent=85,
    )
    event = _event(service, account, source, "WARNING")

    target = ServiceTrafficNotificationWorker._target(
        event, service, account, source, newer_same_stage, _NOW
    )
    assert target.remaining_bytes == 15 * _GIB
    assert target.customer_id == service.beneficiary_customer_id

    recovered = _aggregate(account, state="AVAILABLE", remaining_bytes=70 * _GIB)
    with pytest.raises(StaleServiceTrafficNotification):
        ServiceTrafficNotificationWorker._target(event, service, account, source, recovered, _NOW)

    escalated = _aggregate(account, state="CRITICAL", remaining_bytes=3 * _GIB)
    with pytest.raises(StaleServiceTrafficNotification):
        ServiceTrafficNotificationWorker._target(event, service, account, source, escalated, _NOW)


def test_confirmed_exhaustion_allows_percent_over_100_from_real_overage() -> None:
    service = _service()
    account = _account(service)
    source = _aggregate(
        account,
        state="EXHAUSTED_CONFIRMED",
        remaining_bytes=0,
        consumed_percent=104,
    )
    event = _event(service, account, source, "EXHAUSTED")

    target = ServiceTrafficNotificationWorker._target(event, service, account, source, source, _NOW)
    assert target.stage == "EXHAUSTED"
    assert target.consumed_percent == 104


def test_target_rejects_stale_low_confidence_and_invalid_scope() -> None:
    service = _service()
    account = _account(service)
    source = _aggregate(account)
    event = _event(service, account, source, "WARNING")

    stale = _aggregate(account, observed_at=_NOW - timedelta(hours=3))
    with pytest.raises(StaleServiceTrafficNotification):
        ServiceTrafficNotificationWorker._target(event, service, account, source, stale, _NOW)

    low = _aggregate(account, confidence="LOW")
    with pytest.raises(StaleServiceTrafficNotification):
        ServiceTrafficNotificationWorker._target(event, service, account, source, low, _NOW)

    invalid_event = cast(
        TransactionalOutboxModel,
        SimpleNamespace(payload={"service_id": service.id, "stage": "WARNING"}),
    )
    with pytest.raises(InvalidServiceTrafficNotification):
        ServiceTrafficNotificationWorker._target(
            invalid_event, service, account, source, source, _NOW
        )


def test_enqueue_is_latest_fresh_deduplicated_and_preference_scoped() -> None:
    enqueue_source = getsource(ServiceTrafficNotificationWorker._enqueue)
    module_source = getsource(service_traffic_notification)

    assert "newer_exists" in enqueue_source
    assert "with_for_update(skip_locked=True" in enqueue_source
    assert 'ServiceModel.lifecycle == "ACTIVE"' in enqueue_source
    assert 'ServiceUsageAggregateModel.confidence.in_(("HIGH", "MEDIUM"))' in enqueue_source
    assert "FRESHNESS_LIMIT" in enqueue_source
    assert "TransactionalOutboxModel.event_key" in enqueue_source
    assert "low_traffic_enabled" in module_source
    assert "LedgerPostingModel" not in module_source
    assert "WalletReservationModel" not in module_source
    assert "SanaeiAuthenticatedTransport" not in module_source


def test_rollout_migration_baselines_only_latest_historical_notification_stage() -> None:
    migration = Path(
        "apps/api/alembic/versions/0047_telegram_low_traffic_notifications.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "0047_low_traffic_tg"' in migration
    assert 'down_revision: str = "0046_service_op_tg_notify"' in migration
    assert "row_number() OVER" in migration
    assert "ranked.row_number = 1" in migration
    assert "EXHAUSTED_CONFIRMED" in migration
    assert "BASELINED" in migration
    assert "ON CONFLICT (event_key) DO NOTHING" in migration


def test_worker_runtime_orders_usage_sync_before_traffic_notifications() -> None:
    source = getsource(main)

    usage_index = source.index("usage_sync.run_once()")
    traffic_index = source.index("service_traffic_notifications.run_once()")
    assert usage_index < traffic_index
