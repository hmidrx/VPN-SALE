from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db_session
from .management import require_perm
from .service_models import ServiceFulfillmentRequestModel, ServiceModel

admin_router = APIRouter(prefix="/api/v1/admin/services", tags=["admin-services"])
customer_router = APIRouter(prefix="/api/v1/customer/services", tags=["customer-services"])
allocation_router = APIRouter(prefix="/api/v1/admin/allocation", tags=["admin-allocation"])
reconciliation_router = APIRouter(
    prefix="/api/v1/admin/service-reconciliation", tags=["admin-service-reconciliation"]
)


class SafeServiceStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_reference: str
    lifecycle: str
    product_label: str = Field(default="خدمت شبکه")
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    required_attachment_count: int
    verified_attachment_count: int
    operational_message: str


class FulfillmentRequestStatus(BaseModel):
    id: str
    deduplication_key: str
    order_id: str
    order_item_id: str
    unit_index: int
    status: str
    result_code: str | None


class AllocationSimulationRequest(BaseModel):
    product_version_id: str
    plan_reference: str
    location: str | None = None
    required_attachment_count: int = Field(ge=1, le=8)


class AllocationSimulationResponse(BaseModel):
    eligible: list[str]
    rejected_reason_codes: list[str]
    performs_reservation: bool = False
    performs_provider_mutation: bool = False


def snapshot_non_negative_int(value: object, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdecimal():
        parsed = int(value)
    else:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    if parsed < 0:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    return parsed


def _safe_service(row: ServiceModel) -> SafeServiceStatus:
    entitlement = row.entitlement_snapshot
    required_attachment_count = snapshot_non_negative_int(
        entitlement.get("required_attachment_count"), "required_attachment_count", 0
    )
    return SafeServiceStatus(
        public_reference=row.public_reference,
        lifecycle=row.lifecycle,
        product_label=str(entitlement.get("product_label", "خدمت شبکه")),
        created_at=row.created_at,
        activated_at=row.activated_at,
        expires_at=row.expires_at,
        required_attachment_count=required_attachment_count,
        verified_attachment_count=0,
        operational_message="وضعیت تحقق سرویس بدون نمایش اطلاعات فنی ارائه‌دهنده.",
    )


@admin_router.get("", response_model=list[SafeServiceStatus])
def list_services(
    _: Annotated[object, Depends(require_perm("services.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[SafeServiceStatus]:
    rows = db.scalars(
        select(ServiceModel).order_by(ServiceModel.created_at.desc()).limit(min(limit, 100))
    )
    return [_safe_service(row) for row in rows]


@admin_router.get("/{service_reference}", response_model=SafeServiceStatus)
def service_detail(
    service_reference: str,
    _: Annotated[object, Depends(require_perm("services.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> SafeServiceStatus:
    row = db.scalar(select(ServiceModel).where(ServiceModel.public_reference == service_reference))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    return _safe_service(row)


@admin_router.get("/fulfillment/requests", response_model=list[FulfillmentRequestStatus])
def fulfillment_requests(
    _: Annotated[object, Depends(require_perm("fulfillment.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[FulfillmentRequestStatus]:
    rows = db.scalars(
        select(ServiceFulfillmentRequestModel)
        .order_by(ServiceFulfillmentRequestModel.created_at.desc())
        .limit(min(limit, 100))
    )
    return [
        FulfillmentRequestStatus(
            id=row.id,
            deduplication_key=row.deduplication_key,
            order_id=row.order_id,
            order_item_id=row.order_item_id,
            unit_index=row.unit_index,
            status=row.status,
            result_code=row.result_code,
        )
        for row in rows
    ]


@customer_router.get("", response_model=list[SafeServiceStatus])
def customer_services(
    x_customer_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[SafeServiceStatus]:
    rows = db.scalars(
        select(ServiceModel)
        .where(ServiceModel.beneficiary_customer_id == x_customer_id)
        .order_by(ServiceModel.created_at.desc())
        .limit(min(limit, 100))
    )
    return [_safe_service(row) for row in rows]


@allocation_router.post("/simulate", response_model=AllocationSimulationResponse)
def simulate_allocation(
    body: AllocationSimulationRequest,
    _: Annotated[object, Depends(require_perm("allocation.simulate"))],
) -> AllocationSimulationResponse:
    return AllocationSimulationResponse(
        eligible=[],
        rejected_reason_codes=["ALLOCATION_POLICY_NOT_FOUND", body.plan_reference],
    )


@reconciliation_router.get("/issues", response_model=list[dict[str, str]])
def reconciliation_issues(
    _: Annotated[object, Depends(require_perm("service_reconciliation.read"))],
) -> list[dict[str, str]]:
    return []
