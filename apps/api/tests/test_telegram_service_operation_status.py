from __future__ import annotations

from datetime import UTC, datetime
from inspect import getsource
from types import SimpleNamespace
from typing import cast

from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_api.telegram_service_operation_status_internal import (
    operation_status_view,
    service_operation_status,
)


def _operation(operation_type: str, amount: int, status: str) -> ServiceOperationModel:
    desired_change = (
        {"renew_days": amount, "duration_delta_seconds": amount * 24 * 60 * 60}
        if operation_type == "RENEW"
        else {"traffic_gib": amount, "traffic_delta_bytes": amount * 1024**3}
    )
    return cast(
        ServiceOperationModel,
        SimpleNamespace(
            id="11111111-1111-4111-8111-111111111111",
            operation_type=operation_type,
            status=status,
            desired_change=desired_change,
            updated_at=datetime(2026, 8, 17, 18, 0, tzinfo=UTC),
        ),
    )


def _service() -> ServiceModel:
    return cast(ServiceModel, SimpleNamespace(public_reference="svc_customer_safe"))


def test_status_projection_exposes_only_customer_safe_renewal_fields() -> None:
    result = operation_status_view(_operation("RENEW", 30, "SUCCEEDED"), _service())

    assert result == {
        "operation_reference": "11111111-1111-4111-8111-111111111111",
        "service_reference": "svc_customer_safe",
        "operation_type": "RENEW",
        "status": "SUCCEEDED",
        "amount": 30,
        "unit": "DAY",
        "updated_at": "2026-08-17T18:00:00+00:00",
    }
    assert "provider" not in result
    assert "result_snapshot" not in result
    assert "attachment" not in result


def test_status_projection_uses_gib_for_traffic_purchase() -> None:
    result = operation_status_view(_operation("ADD_TRAFFIC", 20, "EXECUTING"), _service())

    assert result["amount"] == 20
    assert result["unit"] == "GIB"
    assert result["status"] == "EXECUTING"


def test_status_lookup_is_bound_to_requester_and_service_owner() -> None:
    source = getsource(service_operation_status)

    assert "ServiceOperationModel.requester_type" in source
    assert "ServiceOperationModel.requester_id == customer_id" in source
    assert "ServiceModel.beneficiary_customer_id == customer_id" in source
    assert "CUSTOMER_NATIVE_OPERATION" in source
    assert "result_snapshot" not in source
    assert "provider_operation_id" not in source
