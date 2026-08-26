from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from vpnsale_domain.usage import ExpiryState, ObservationConfidence, QuotaState

from .management import require_perm

customer_router = APIRouter(
    prefix="/api/v1/customer/service-usage", tags=["customer-service-usage"]
)
reseller_router = APIRouter(
    prefix="/api/v1/reseller/service-usage", tags=["reseller-service-usage"]
)
admin_router = APIRouter(prefix="/api/v1/admin/service-usage", tags=["admin-service-usage"])
policy_router = APIRouter(prefix="/api/v1/admin/usage-policies", tags=["admin-usage-policies"])
anomaly_router = APIRouter(prefix="/api/v1/admin/usage-anomalies", tags=["admin-usage-anomalies"])
automation_router = APIRouter(
    prefix="/api/v1/admin/lifecycle-automation", tags=["admin-lifecycle-automation"]
)


class ServiceUsageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_reference: str
    used_bytes: int | None = Field(ge=0)
    remaining_bytes: int | None = Field(ge=0)
    allowance_bytes: int | None = Field(ge=0)
    unlimited: bool
    quota_state: QuotaState
    expiry_state: ExpiryState
    confidence: ObservationConfidence
    latest_observed_at: datetime | None
    freshness_seconds: int | None = Field(ge=0)
    safe_message: str


class UsageRollupPoint(BaseModel):
    window_start: datetime
    window_end: datetime
    used_bytes: int = Field(ge=0)
    latest_observed_at: datetime


class AdminUsageDashboard(BaseModel):
    near_quota_count: int = Field(ge=0)
    near_expiry_count: int = Field(ge=0)
    exhausted_count: int = Field(ge=0)
    expired_count: int = Field(ge=0)
    stale_or_unknown_count: int = Field(ge=0)
    anomaly_count: int = Field(ge=0)
    worker_backlog_count: int = Field(ge=0)


def unavailable_summary(service_reference: str) -> ServiceUsageSummary:
    return ServiceUsageSummary(
        service_reference=service_reference,
        used_bytes=None,
        remaining_bytes=None,
        allowance_bytes=None,
        unlimited=False,
        quota_state=QuotaState.UNKNOWN,
        expiry_state=ExpiryState.ACTIVE,
        confidence=ObservationConfidence.LOW,
        latest_observed_at=None,
        freshness_seconds=None,
        safe_message=(
            "usage temporarily unavailable; provider data is not exposed to this interface"
        ),
    )


@customer_router.get("/{service_reference}", response_model=ServiceUsageSummary)
def customer_usage_summary(service_reference: str) -> ServiceUsageSummary:
    return unavailable_summary(service_reference)


@customer_router.get("/{service_reference}/rollups", response_model=list[UsageRollupPoint])
def customer_usage_rollups(service_reference: str) -> list[UsageRollupPoint]:
    _ = service_reference
    return []


@reseller_router.get("/{service_reference}", response_model=ServiceUsageSummary)
def reseller_usage_summary(service_reference: str) -> ServiceUsageSummary:
    return unavailable_summary(service_reference)


@admin_router.get(
    "/dashboard",
    response_model=AdminUsageDashboard,
    dependencies=[Depends(require_perm("service_usage.read"))],
)
def admin_usage_dashboard() -> AdminUsageDashboard:
    return AdminUsageDashboard(
        near_quota_count=0,
        near_expiry_count=0,
        exhausted_count=0,
        expired_count=0,
        stale_or_unknown_count=0,
        anomaly_count=0,
        worker_backlog_count=0,
    )


@admin_router.get(
    "/{service_reference}",
    response_model=ServiceUsageSummary,
    dependencies=[Depends(require_perm("service_usage.read"))],
)
def admin_usage_detail(service_reference: str) -> ServiceUsageSummary:
    return unavailable_summary(service_reference)


@policy_router.get(
    "",
    response_model=dict[str, str],
    dependencies=[Depends(require_perm("service_usage.read"))],
)
def usage_policy_index() -> dict[str, str]:
    return {"status": "versioned usage and threshold policy API placeholder"}


@anomaly_router.get(
    "",
    response_model=list[dict[str, str]],
    dependencies=[Depends(require_perm("service_usage.read_anomalies"))],
)
def usage_anomaly_index() -> list[dict[str, str]]:
    return []


@automation_router.get(
    "",
    response_model=dict[str, str | datetime | UUID],
    dependencies=[Depends(require_perm("lifecycle_automation.read"))],
)
def lifecycle_automation_index() -> dict[str, str | datetime | UUID]:
    return {
        "status": "bounded workers scheduled from PostgreSQL leases",
        "observed_at": datetime.now(UTC),
    }
