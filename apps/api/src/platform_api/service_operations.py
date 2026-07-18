from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.service_operations import ServiceOperationType

from .database import get_db_session
from .management import require_perm
from .service_models import ServiceModel, ServiceOperationModel, ServiceOperationPolicyVersionModel

admin_router = APIRouter(
    prefix="/api/v1/admin/service-operations", tags=["admin-service-operations"]
)
customer_router = APIRouter(
    prefix="/api/v1/customer/service-operations", tags=["customer-service-operations"]
)
reseller_router = APIRouter(
    prefix="/api/v1/reseller/service-operations", tags=["reseller-service-operations"]
)


class OperationEligibility(BaseModel):
    operation_type: str
    eligible: bool
    billable: bool
    requires_approval: bool
    safe_reason_codes: list[str]


class OperationCreateRequest(BaseModel):
    service_reference: str
    operation_type: ServiceOperationType
    amount: int | None = Field(default=None, ge=0)
    reason_code: str = Field(min_length=3, max_length=80)
    idempotency_key: str = Field(min_length=16, max_length=200)


class OperationStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    service_id: str
    operation_type: str
    status: str
    requester_type: str
    reason_code: str
    created_at: datetime
    order_id: str | None
    invoice_id: str | None
    payment_id: str | None


def _digest_idempotency(key: str) -> str:
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()


def _operation_status(row: ServiceOperationModel) -> OperationStatus:
    return OperationStatus(
        id=row.id,
        service_id=row.service_id,
        operation_type=row.operation_type,
        status=row.status,
        requester_type=row.requester_type,
        reason_code=row.reason_code,
        created_at=row.created_at,
        order_id=row.order_id,
        invoice_id=row.invoice_id,
        payment_id=row.payment_id,
    )


ELIGIBLE_DEFAULTS: tuple[ServiceOperationType, ...] = (
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
    ServiceOperationType.EXTEND_EXPIRY,
    ServiceOperationType.CHANGE_DEVICE_LIMIT,
    ServiceOperationType.SUSPEND,
    ServiceOperationType.RESUME,
    ServiceOperationType.RESET_TRAFFIC,
    ServiceOperationType.CLEAR_CLIENT_IPS,
    ServiceOperationType.CLEAR_HWID,
    ServiceOperationType.ROTATE_CREDENTIAL,
    ServiceOperationType.REVOKE_SUBSCRIPTION,
    ServiceOperationType.ROTATE_SUBSCRIPTION_TOKEN,
    ServiceOperationType.REFRESH_DELIVERY_PROFILE,
)


@customer_router.get("/{service_reference}/eligibility", response_model=list[OperationEligibility])
def customer_eligibility(
    service_reference: str, x_customer_id: str, db: Annotated[Session, Depends(get_db_session)]
) -> list[OperationEligibility]:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == x_customer_id,
        )
    )
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    active = service.lifecycle in {"ACTIVE", "EXPIRED", "SUSPENDED", "DEGRADED"}
    return [
        OperationEligibility(
            operation_type=item.value,
            eligible=active,
            billable=item
            in {
                ServiceOperationType.RENEW,
                ServiceOperationType.ADD_TRAFFIC,
                ServiceOperationType.EXTEND_EXPIRY,
                ServiceOperationType.CHANGE_DEVICE_LIMIT,
            },
            requires_approval=False,
            safe_reason_codes=[] if active else ["SERVICE_NOT_ELIGIBLE"],
        )
        for item in ELIGIBLE_DEFAULTS
    ]


@customer_router.post("", response_model=OperationStatus, status_code=status.HTTP_201_CREATED)
def create_customer_operation(
    body: OperationCreateRequest,
    x_customer_id: str,
    db: Annotated[Session, Depends(get_db_session)],
) -> OperationStatus:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == body.service_reference,
            ServiceModel.beneficiary_customer_id == x_customer_id,
        )
    )
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    digest = _digest_idempotency(body.idempotency_key)
    existing = db.scalar(
        select(ServiceOperationModel).where(
            ServiceOperationModel.service_id == service.id,
            ServiceOperationModel.idempotency_key_digest == digest,
        )
    )
    if existing is not None:
        return _operation_status(existing)
    policy_version = db.scalar(
        select(ServiceOperationPolicyVersionModel)
        .where(ServiceOperationPolicyVersionModel.status == "PUBLISHED")
        .order_by(ServiceOperationPolicyVersionModel.created_at.desc())
    )
    if policy_version is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": "OPERATION_POLICY_UNPUBLISHED"}
        )
    now = datetime.now(UTC)
    billable = body.operation_type in {
        ServiceOperationType.RENEW,
        ServiceOperationType.ADD_TRAFFIC,
        ServiceOperationType.EXTEND_EXPIRY,
        ServiceOperationType.CHANGE_DEVICE_LIMIT,
    }
    row = ServiceOperationModel(
        service_id=service.id,
        operation_type=body.operation_type.value,
        status="AWAITING_PAYMENT" if billable else "QUEUED",
        requester_type="CUSTOMER",
        requester_id=x_customer_id,
        idempotency_key_digest=digest,
        reason_code=body.reason_code,
        policy_version_id=policy_version.id,
        policy_snapshot=policy_version.immutable_snapshot,
        desired_change={"amount": body.amount, "operation_type": body.operation_type.value},
        quote_snapshot={"price_source": "backend_policy", "amount": body.amount}
        if billable
        else None,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _operation_status(row)


@admin_router.get("", response_model=list[OperationStatus])
def list_admin_operations(
    _: Annotated[object, Depends(require_perm("service_operations.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[OperationStatus]:
    rows = db.scalars(
        select(ServiceOperationModel)
        .order_by(ServiceOperationModel.created_at.desc())
        .limit(min(limit, 100))
    )
    return [_operation_status(row) for row in rows]


@admin_router.post("/{operation_id}/approve", response_model=OperationStatus)
def approve_operation(
    operation_id: str,
    x_admin_actor: str,
    _: Annotated[object, Depends(require_perm("service_operations.approve"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> OperationStatus:
    row = db.get(ServiceOperationModel, operation_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "OPERATION_NOT_FOUND"})
    if row.requester_id == x_admin_actor:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail={"code": "OPERATION_SELF_APPROVAL_DENIED"}
        )
    if row.status != "PENDING_APPROVAL":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={"code": "OPERATION_STATUS_INVALID"})
    row.status = "QUEUED"
    row.version += 1
    row.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return _operation_status(row)


@reseller_router.get("/{service_reference}/eligibility", response_model=list[OperationEligibility])
def reseller_eligibility(
    service_reference: str, x_reseller_id: str, db: Annotated[Session, Depends(get_db_session)]
) -> list[OperationEligibility]:
    service = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.reseller_id == x_reseller_id,
        )
    )
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    return [
        OperationEligibility(
            operation_type=item.value,
            eligible=True,
            billable=item in {ServiceOperationType.RENEW, ServiceOperationType.ADD_TRAFFIC},
            requires_approval=False,
            safe_reason_codes=[],
        )
        for item in ELIGIBLE_DEFAULTS
    ]
