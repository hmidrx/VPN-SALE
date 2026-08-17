"""Private customer-scoped Telegram projection for paid service-operation status."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select
from vpnsale_domain.service_operations import ServiceOperationActorType

from .service_models import ServiceModel, ServiceOperationModel
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store
from .telegram_service_management_internal import CUSTOMER_NATIVE_OPERATION_TYPES

router = APIRouter(
    prefix="/api/v1/internal/telegram/service-management",
    tags=["internal-telegram-service-operation-status"],
    include_in_schema=False,
)

_CUSTOMER_NATIVE_OPERATION_VALUES = tuple(item.value for item in CUSTOMER_NATIVE_OPERATION_TYPES)


def operation_status_view(
    operation: ServiceOperationModel,
    service: ServiceModel,
) -> dict[str, object]:
    if operation.operation_type == "RENEW":
        amount = operation.desired_change.get("renew_days")
        unit = "DAY"
    elif operation.operation_type == "ADD_TRAFFIC":
        amount = operation.desired_change.get("traffic_gib")
        unit = "GIB"
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service_operation_not_found",
        )
    if type(amount) is not int or amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="service_operation_state_invalid",
        )
    updated_at = operation.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return {
        "operation_reference": operation.id,
        "service_reference": service.public_reference,
        "operation_type": operation.operation_type,
        "status": operation.status,
        "amount": amount,
        "unit": unit,
        "updated_at": updated_at.isoformat(),
    }


@router.get("/operations/{operation_reference}")
def service_operation_status(
    operation_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    operation = db.scalar(
        select(ServiceOperationModel)
        .join(ServiceModel, ServiceModel.id == ServiceOperationModel.service_id)
        .where(
            ServiceOperationModel.id == operation_reference,
            ServiceOperationModel.requester_type == ServiceOperationActorType.CUSTOMER.value,
            ServiceOperationModel.requester_id == customer_id,
            ServiceOperationModel.operation_type.in_(_CUSTOMER_NATIVE_OPERATION_VALUES),
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service_operation_not_found",
        )
    service = db.get(ServiceModel, operation.service_id)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service_operation_not_found",
        )
    _no_store(response)
    return operation_status_view(operation, service)
