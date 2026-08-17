# pyright: reportPrivateUsage=false
"""Private Telegram-native service management projections."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select
from vpnsale_domain.service_operations import ServiceOperationType

from .service_models import ServiceModel
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store

router = APIRouter(
    prefix="/api/v1/internal/telegram/service-management",
    tags=["internal-telegram-service-management"],
    include_in_schema=False,
)

_BILLABLE = {
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
    ServiceOperationType.EXTEND_EXPIRY,
    ServiceOperationType.CHANGE_DEVICE_LIMIT,
}
CUSTOMER_NATIVE_OPERATION_TYPES = (
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
)
_ELIGIBLE_LIFECYCLES = {"ACTIVE", "EXPIRED", "SUSPENDED", "DEGRADED"}


def _service(db: Database, customer_id: str, reference: str) -> ServiceModel:
    row = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service_not_found")
    return row


@router.get("/{service_reference}/eligibility")
def service_management_eligibility(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    service = _service(db, customer_id, service_reference)
    eligible = service.lifecycle in _ELIGIBLE_LIFECYCLES
    _no_store(response)
    return {
        "service_reference": service.public_reference,
        "lifecycle": service.lifecycle,
        "operations": [
            {
                "operation_type": operation.value,
                "eligible": eligible,
                "billable": operation in _BILLABLE,
                "requires_authoritative_quote": operation in _BILLABLE,
                "safe_reason_codes": [] if eligible else ["SERVICE_NOT_ELIGIBLE"],
            }
            for operation in CUSTOMER_NATIVE_OPERATION_TYPES
        ],
    }
