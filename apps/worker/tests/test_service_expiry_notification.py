from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import getsource
from types import SimpleNamespace
from typing import cast

import pytest

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel
from platform_worker import service_expiry_notification
from platform_worker.main import main
from platform_worker.service_expiry_notification import (
    InvalidServiceExpiryNotification,
    ServiceExpiryNotificationTarget,
    ServiceExpiryNotificationWorker,
    StaleServiceExpiryNotification,
    _callback_data,
    _event_key,
    _expiry_token,
    _notification_text,
    _stage_for,
)

_NOW = datetime(2026, 8, 17, 18, 0, tzinfo=UTC)


def _service(
    *,
    service_id: str = "11111111-1111-1111-1111-111111111111",
    customer_id: str = "22222222-2222-2222-2222-222222222222",
    reference: str = "SVC-EXAMPLE",
    lifecycle: str = "ACTIVE",
    expires_at: datetime | None = None,
) -> ServiceModel:
    return cast(
        ServiceModel,
        SimpleNamespace(
            id=service_id,
            public_reference=reference,
            beneficiary_customer_id=customer_id,
            lifecycle=lifecycle,
            expires_at=expires_at or (_NOW + timedelta(hours=20)),
        ),
    )


def _event(service: ServiceModel, stage: str) -> TransactionalOutboxModel:
    assert service.expires_at is not None
    return cast(
        TransactionalOutboxModel,
        SimpleNamespace(
            payload={
                "service_id": service.id,
                "stage": stage,
                "expiry_token": _expiry_token(service.expires_at),
            }
        ),
    )


def test_stage_windows_prioritize_24_hours_then_72_hours() -> None:
    assert _stage_for(_NOW + timedelta(hours=23), _NOW) == "24H"
    assert _stage_for(_NOW + timedelta(hours=24), _NOW) == "24H"
    assert _stage_for(_NOW + timedelta(hours=25), _NOW) == "72H"
    assert _stage_for(_NOW + timedelta(hours=72), _NOW) == "72H"
    assert _stage_for(_NOW + timedelta(hours=73), _NOW) is None
    assert _stage_for(_NOW, _NOW) is None


def test_event_key_is_bound_to_exact_expiry_cycle() -> None:
    first = _service(expires_at=_NOW + timedelta(days=2))
    renewed = _service(expires_at=_NOW + timedelta(days=32))

    first_key = _event_key(first, "72H")
    renewed_key = _event_key(renewed, "72H")

    assert first_key != renewed_key
    assert first.id in first_key
    assert len(first_key) <= 120


def test_callback_opens_native_service_screen_and_stays_within_limit() -> None:
    reference = "S" * 48
    callback = _callback_data(reference)

    assert callback == f"b:v1:svc_open:{reference}"
    assert len(callback.encode()) <= 64
    assert "http" not in callback


def test_customer_copy_has_distinct_urgent_and_upcoming_reminders() -> None:
    urgent = _notification_text(
        ServiceExpiryNotificationTarget(
            service_reference="SVC-1",
            customer_id="customer",
            stage="24H",
        )
    )
    upcoming = _notification_text(
        ServiceExpiryNotificationTarget(
            service_reference="SVC-1",
            customer_id="customer",
            stage="72H",
        )
    )

    assert "۲۴ ساعت" in urgent
    assert "۳ روز" in upcoming
    assert "تمدید" in urgent
    assert "provider" not in urgent.lower()
    assert "panel" not in urgent.lower()


def test_target_revalidates_current_service_state_before_delivery() -> None:
    service = _service(expires_at=_NOW + timedelta(hours=20))
    target = ServiceExpiryNotificationWorker._target(_event(service, "24H"), service, _NOW)

    assert target.customer_id == service.beneficiary_customer_id
    assert target.service_reference == service.public_reference

    renewed = _service(expires_at=_NOW + timedelta(days=30))
    with pytest.raises(StaleServiceExpiryNotification):
        ServiceExpiryNotificationWorker._target(_event(service, "24H"), renewed, _NOW)

    inactive = _service(lifecycle="SUSPENDED", expires_at=service.expires_at)
    with pytest.raises(StaleServiceExpiryNotification):
        ServiceExpiryNotificationWorker._target(_event(service, "24H"), inactive, _NOW)


def test_72_hour_delivery_is_suppressed_once_24_hour_window_is_reached() -> None:
    queued_service = _service(expires_at=_NOW + timedelta(hours=30))
    event = _event(queued_service, "72H")

    with pytest.raises(StaleServiceExpiryNotification):
        ServiceExpiryNotificationWorker._target(
            event,
            queued_service,
            _NOW + timedelta(hours=7),
        )


def test_invalid_callback_or_event_data_fails_closed() -> None:
    with pytest.raises(InvalidServiceExpiryNotification):
        _callback_data("X" * 60)

    invalid_event = cast(
        TransactionalOutboxModel,
        SimpleNamespace(payload={"service_id": "svc", "stage": "7D", "expiry_token": "x"}),
    )
    with pytest.raises(InvalidServiceExpiryNotification):
        ServiceExpiryNotificationWorker._target(invalid_event, _service(service_id="svc"), _NOW)


def test_enqueue_is_deduplicated_and_scoped_to_active_future_services() -> None:
    source = getsource(ServiceExpiryNotificationWorker._enqueue_stage)
    module_source = getsource(service_expiry_notification)

    assert "already_enqueued" in source
    assert "~already_enqueued" in source
    assert "with_for_update(skip_locked=True" in source
    assert 'ServiceModel.lifecycle == "ACTIVE"' in source
    assert "ServiceModel.expires_at >" in source
    assert "ServiceModel.expires_at <=" in source
    assert "service_expiry_enabled" in module_source
    assert "LedgerPostingModel" not in module_source
    assert "WalletReservationModel" not in module_source
    assert "provider" not in module_source.lower()


def test_worker_runtime_wires_expiry_notifications_without_provider_writes() -> None:
    source = getsource(main)

    assert "ServiceExpiryNotificationWorker" in source
    assert "service_expiry_notifications.run_once()" in source
