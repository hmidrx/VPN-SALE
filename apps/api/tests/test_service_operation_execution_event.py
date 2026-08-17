# pyright: reportPrivateUsage=false
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from sqlalchemy.orm import Session

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel
from platform_api.service_operations import _enqueue_paid_operation_ready


class _FakeSession:
    def __init__(self, scalar_results: list[object | None]) -> None:
        self.scalar_results = scalar_results
        self.added: list[object] = []

    def scalar(self, _statement: object) -> object | None:
        return self.scalar_results.pop(0)

    def add(self, row: object) -> None:
        self.added.append(row)


def _operation(operation_type: str) -> ServiceOperationModel:
    return cast(
        ServiceOperationModel,
        SimpleNamespace(
            id="11111111-1111-1111-1111-111111111111",
            operation_type=operation_type,
            payment_id=None,
        ),
    )


def _service() -> ServiceModel:
    return cast(
        ServiceModel,
        SimpleNamespace(
            id="22222222-2222-2222-2222-222222222222",
            public_reference="svc_test",
        ),
    )


def _payment() -> ServiceOperationPaymentModel:
    return cast(
        ServiceOperationPaymentModel,
        SimpleNamespace(
            id="33333333-3333-3333-3333-333333333333",
            customer_id="44444444-4444-4444-4444-444444444444",
        ),
    )


def test_approved_paid_renewal_emits_the_same_ready_contract_as_direct_payment() -> None:
    fake = _FakeSession([_payment(), None])
    operation = _operation("RENEW")
    now = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)

    _enqueue_paid_operation_ready(cast(Session, fake), operation, _service(), now)

    assert operation.payment_id == "33333333-3333-3333-3333-333333333333"
    assert len(fake.added) == 1
    event = cast(TransactionalOutboxModel, fake.added[0])
    assert event.event_key == "service_operation.ready:11111111-1111-1111-1111-111111111111"
    assert event.event_type == "service_operation.ready.v1"
    assert event.status == "PENDING"
    assert event.payload["operation_type"] == "RENEW"
    assert event.payload["payment_id"] == "33333333-3333-3333-3333-333333333333"
    assert event.available_at == now


def test_approval_event_is_idempotent_when_ready_event_already_exists() -> None:
    fake = _FakeSession([_payment(), "existing-event-id"])

    _enqueue_paid_operation_ready(
        cast(Session, fake),
        _operation("ADD_TRAFFIC"),
        _service(),
        datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
    )

    assert fake.added == []


def test_non_executable_approved_operation_does_not_emit_worker_event() -> None:
    fake = _FakeSession([])

    _enqueue_paid_operation_ready(
        cast(Session, fake),
        _operation("RESET_TRAFFIC"),
        _service(),
        datetime(2026, 8, 17, 16, 0, tzinfo=UTC),
    )

    assert fake.added == []
