from __future__ import annotations

from inspect import getsource
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel
from platform_worker import service_operation_notification
from platform_worker.main import BotApiTransport
from platform_worker.service_operation_notification import (
    InvalidServiceOperationNotification,
    ServiceOperationNotificationTarget,
    ServiceOperationNotificationWorker,
    _callback_data,
    _notification_text,
)


def _event(operation_id: str, status: str) -> TransactionalOutboxModel:
    return cast(
        TransactionalOutboxModel,
        SimpleNamespace(
            payload={"operation_id": operation_id, "terminal_status": status},
        ),
    )


def _operation(
    *,
    operation_id: str = "11111111-1111-1111-1111-111111111111",
    customer_id: str = "22222222-2222-2222-2222-222222222222",
    service_id: str = "33333333-3333-3333-3333-333333333333",
    operation_type: str = "RENEW",
    status: str = "SUCCEEDED",
) -> ServiceOperationModel:
    return cast(
        ServiceOperationModel,
        SimpleNamespace(
            id=operation_id,
            service_id=service_id,
            operation_type=operation_type,
            status=status,
            requester_type="CUSTOMER",
            requester_id=customer_id,
        ),
    )


def _service(
    *,
    customer_id: str = "22222222-2222-2222-2222-222222222222",
    service_id: str = "33333333-3333-3333-3333-333333333333",
) -> ServiceModel:
    return cast(
        ServiceModel,
        SimpleNamespace(
            id=service_id,
            public_reference="SVC-EXAMPLE",
            beneficiary_customer_id=customer_id,
        ),
    )


def _payment(
    *,
    operation_id: str = "11111111-1111-1111-1111-111111111111",
    customer_id: str = "22222222-2222-2222-2222-222222222222",
    status: str = "CAPTURED",
) -> ServiceOperationPaymentModel:
    return cast(
        ServiceOperationPaymentModel,
        SimpleNamespace(
            operation_id=operation_id,
            customer_id=customer_id,
            status=status,
        ),
    )


def test_callback_is_native_compact_and_within_telegram_limit() -> None:
    reference = "11111111-1111-1111-1111-111111111111"
    callback = _callback_data(reference)

    assert callback == f"b:v1:svst:{reference}"
    assert len(callback.encode()) <= 64
    assert "http" not in callback


def test_success_and_review_messages_are_customer_safe() -> None:
    success = _notification_text(
        ServiceOperationNotificationTarget(
            operation_reference="op",
            service_reference="SVC-1",
            operation_type="ADD_TRAFFIC",
            status="SUCCEEDED",
            customer_id="customer",
        )
    )
    uncertain = _notification_text(
        ServiceOperationNotificationTarget(
            operation_reference="op",
            service_reference="SVC-1",
            operation_type="RENEW",
            status="UNCERTAIN",
            customer_id="customer",
        )
    )

    assert "افزایش حجم سرویس" in success
    assert "با موفقیت انجام شد" in success
    assert "دوباره پرداخت نکنید" in uncertain
    assert "provider" not in uncertain.lower()
    assert "panel" not in uncertain.lower()


def test_target_requires_paid_customer_owned_operation_and_service() -> None:
    operation = _operation()
    target = ServiceOperationNotificationWorker._target(
        _event(operation.id, operation.status),
        operation,
        _service(),
        _payment(),
    )

    assert target.customer_id == operation.requester_id
    assert target.service_reference == "SVC-EXAMPLE"

    with pytest.raises(InvalidServiceOperationNotification):
        ServiceOperationNotificationWorker._target(
            _event(operation.id, operation.status),
            operation,
            _service(customer_id="44444444-4444-4444-4444-444444444444"),
            _payment(),
        )


def test_refunded_payment_remains_a_valid_read_only_notification_anchor() -> None:
    operation = _operation(status="COMPENSATED")
    target = ServiceOperationNotificationWorker._target(
        _event(operation.id, operation.status),
        operation,
        _service(),
        _payment(status="REFUNDED"),
    )

    assert target.status == "COMPENSATED"
    assert "کیف پول" in _notification_text(target)


def test_enqueue_is_deduplicated_and_scoped_without_financial_mutation() -> None:
    source = getsource(ServiceOperationNotificationWorker._enqueue)
    module_source = getsource(service_operation_notification)

    assert "already_enqueued" in source
    assert "~already_enqueued" in source
    assert "with_for_update(skip_locked=True" in source
    assert "ServiceOperationPaymentModel.customer_id" in source
    assert "ServiceModel.beneficiary_customer_id" in source
    assert "LedgerPostingModel" not in module_source
    assert "WalletReservationModel" not in module_source
    assert "executor.execute" not in module_source


def test_transport_notification_uses_native_callback_not_mini_app() -> None:
    source = getsource(BotApiTransport.send_callback)
    markup_source = getsource(BotApiTransport._callback_reply_markup)

    assert '"callback_data"' in markup_source
    assert '"web_app"' not in markup_source
    assert "_message_endpoint" in source
    assert "sendPhoto" not in source


def test_rollout_migration_baselines_only_historical_terminal_rows() -> None:
    module_path = Path(service_operation_notification.__file__).resolve()
    root = module_path.parents[4]
    migration = (
        root
        / "apps/api/alembic/versions/0046_service_op_telegram_notifications.py"
    ).read_text(encoding="utf-8")

    assert "'baseline', true" in migration
    assert "ON CONFLICT (event_key) DO NOTHING" in migration
    assert "failure_category = 'BASELINED'" in migration
    assert "payload ->> 'baseline' = 'true'" in migration
    assert "payment.customer_id = service.beneficiary_customer_id" in migration
    assert "operation.requester_id = payment.customer_id::text" in migration
