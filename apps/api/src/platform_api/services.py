from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .customer_auth.routes import current_customer_session_dependency
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .management import require_perm
from .service_models import ServiceAttachmentModel, ServiceFulfillmentRequestModel, ServiceModel

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


class CustomerServiceEntitlement(BaseModel):
    traffic_quota_bytes: int | None = None
    duration_days: int | None = None
    device_limit: int | None = None
    location_label: str | None = None
    quality_label: str | None = None


class CustomerServiceUsage(BaseModel):
    used_bytes: int
    total_bytes: int | None
    remaining_bytes: int | None
    last_synced_at: datetime
    unlimited: bool
    stale: bool


class CustomerServiceSummary(BaseModel):
    service_reference: str
    display_name: str
    lifecycle: str
    lifecycle_label: str
    created_at: datetime
    starts_at: datetime | None
    activated_at: datetime | None
    expires_at: datetime | None
    delivery_ready: bool
    required_attachment_count: int
    verified_attachment_count: int
    provisioning_progress: int
    safe_operational_message: str
    entitlement: CustomerServiceEntitlement
    usage: CustomerServiceUsage | None = None


class CustomerServiceDetail(BaseModel):
    summary: CustomerServiceSummary
    service_health: str
    eligible_operations: list[dict[str, object]]
    delivery: dict[str, object]
    latest_activity: list[dict[str, object]]


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


def _safe_service(row: ServiceModel, verified_attachment_count: int = 0) -> SafeServiceStatus:
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
        verified_attachment_count=verified_attachment_count,
        operational_message="وضعیت تحقق سرویس بدون نمایش اطلاعات فنی ارائه‌دهنده.",
    )


_INTEGER_LIMITS = {
    "traffic_quota_bytes": 1024**5,
    "duration_days": 3650,
    "device_limit": 1000,
    "required_attachment_count": 8,
}


def _allowlisted_int(snapshot: dict[str, object], name: str) -> int | None:
    value = snapshot.get(name)
    if type(value) is not int or value < 0 or value > _INTEGER_LIMITS[name]:
        return None
    return value


def _allowlisted_text(snapshot: dict[str, object], name: str, maximum: int) -> str | None:
    value = snapshot.get(name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum else None


_LIFECYCLE_LABELS = {
    "ACTIVE": "فعال",
    "PROVISIONING": "در حال آماده‌سازی",
    "PENDING_ACTIVATION": "سفارش ثبت شد",
    "SUSPENDED": "متوقف",
    "EXPIRED": "منقضی",
    "DEGRADED": "نیازمند بررسی",
}


def _customer_summary(row: ServiceModel, verified: int) -> CustomerServiceSummary:
    snapshot = row.entitlement_snapshot
    required = _allowlisted_int(snapshot, "required_attachment_count") or 0
    entitlement = CustomerServiceEntitlement(
        traffic_quota_bytes=_allowlisted_int(snapshot, "traffic_quota_bytes"),
        duration_days=_allowlisted_int(snapshot, "duration_days"),
        device_limit=_allowlisted_int(snapshot, "device_limit"),
        location_label=_allowlisted_text(snapshot, "location_label", 80),
        quality_label=_allowlisted_text(snapshot, "quality_label", 80),
    )
    progress = min(100, round(verified / required * 100)) if required else 0
    delivery_ready = required > 0 and verified == required and row.lifecycle == "ACTIVE"
    return CustomerServiceSummary(
        service_reference=row.public_reference,
        display_name=_allowlisted_text(snapshot, "product_label", 120) or "خدمت شبکه",
        lifecycle=row.lifecycle,
        lifecycle_label=_LIFECYCLE_LABELS.get(row.lifecycle, "در حال بررسی"),
        created_at=row.created_at,
        starts_at=row.starts_at,
        activated_at=row.activated_at,
        expires_at=row.expires_at,
        delivery_ready=delivery_ready,
        required_attachment_count=required,
        verified_attachment_count=verified,
        provisioning_progress=progress,
        safe_operational_message="وضعیت سرویس بدون نمایش اطلاعات فنی ارائه‌دهنده.",
        entitlement=entitlement,
        usage=None,
    )


def customer_service_summaries(
    db: Session, customer_id: str, limit: int = 50
) -> list[CustomerServiceSummary]:
    """Authoritative customer-safe projection shared by web and private bot APIs."""
    rows = db.scalars(
        select(ServiceModel)
        .where(ServiceModel.beneficiary_customer_id == customer_id)
        .order_by(ServiceModel.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [_customer_summary(row, _verified_attachment_count(db, row.id)) for row in rows]


def _verified_attachment_count(db: Session, service_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ServiceAttachmentModel)
            .where(
                ServiceAttachmentModel.service_id == service_id,
                ServiceAttachmentModel.required.is_(True),
                ServiceAttachmentModel.verification_status == "VERIFIED",
            )
        )
        or 0
    )


def customer_service_projection(
    db: Session, customer_id: str, service_reference: str
) -> CustomerServiceDetail | None:
    row = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if row is None:
        return None
    summary = _customer_summary(row, _verified_attachment_count(db, row.id))
    return CustomerServiceDetail(
        summary=summary,
        service_health=summary.lifecycle_label,
        eligible_operations=[],
        delivery={
            "ready": summary.delivery_ready,
            "formats": ["subscription"] if summary.delivery_ready else [],
        },
        latest_activity=[],
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


@customer_router.get("", response_model=list[CustomerServiceSummary])
def customer_services(
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[CustomerServiceSummary]:
    return customer_service_summaries(db, customer_session.user_id, limit)


@customer_router.get("/{service_reference}", response_model=CustomerServiceDetail)
def customer_service_detail(
    service_reference: str,
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CustomerServiceDetail:
    detail = customer_service_projection(db, customer_session.user_id, service_reference)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    return detail


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
