from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel
from platform_api.management import current_admin
from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import (
    ServiceFulfillmentRequestModel,
    ServiceModel,
    ServiceOperationModel,
)
from platform_api.usage_models import (
    ServiceUsageAccountModel,
    ServiceUsageAggregateModel,
    ServiceUsageSyncRunModel,
)

router = APIRouter(
    prefix="/api/v1/admin/management/operations",
    tags=["admin-operations-observability"],
)

_STALE_CLAIM_AFTER = timedelta(minutes=15)
_STALE_USAGE_AFTER = timedelta(minutes=15)
_RECENT_FAILURE_WINDOW = timedelta(hours=1)
_IN_PROGRESS_OPERATION_STATUSES = (
    "PENDING_APPROVAL",
    "QUEUED",
    "EXECUTING",
    "VERIFYING",
    "RECONCILING",
)
_REVIEW_REQUIRED_OPERATION_STATUSES = (
    "PARTIALLY_APPLIED",
    "UNCERTAIN",
    "COMPENSATION_REQUIRED",
    "MANUAL_REVIEW",
)
_FULFILLMENT_STATUSES = ("RETRY_PENDING", "BLOCKED", "OPERATOR_REVIEW", "FAILED")
_USAGE_RUN_STATUSES = ("SUCCESS", "PARTIAL", "FAILED", "UNKNOWN")


class OutboxHealth(BaseModel):
    pending_due: int
    retrying: int
    failed: int
    stale_claims: int
    oldest_due_age_seconds: int


class FulfillmentHealth(BaseModel):
    retry_pending: int
    blocked: int
    operator_review: int
    failed: int


class ServiceOperationHealth(BaseModel):
    in_progress: int
    review_required: int


class UsageSyncHealth(BaseModel):
    latest_status: Literal["SUCCESS", "PARTIAL", "FAILED", "UNKNOWN"]
    latest_run_age_seconds: int | None
    last_success_age_seconds: int | None
    degraded_runs_last_hour: int
    stale_active_accounts: int


class OperationsHealthSnapshot(BaseModel):
    generated_at: datetime
    status: Literal["HEALTHY", "DEGRADED", "ACTION_REQUIRED"]
    signals: list[str]
    outbox: OutboxHealth
    fulfillment: FulfillmentHealth
    service_operations: ServiceOperationHealth
    usage_sync: UsageSyncHealth


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _age_seconds(now: datetime, value: datetime | None) -> int | None:
    normalized = _aware(value)
    if normalized is None:
        return None
    return max(0, int((now - normalized).total_seconds()))


def _status_counts(
    db: Session,
    model: type[ServiceFulfillmentRequestModel] | type[ServiceOperationModel],
    statuses: tuple[str, ...],
) -> dict[str, int]:
    rows = db.execute(
        select(model.status, func.count()).where(model.status.in_(statuses)).group_by(model.status)
    ).all()
    return {str(status): int(count) for status, count in rows}


def classify_operations_health(
    *,
    outbox: OutboxHealth,
    fulfillment: FulfillmentHealth,
    service_operations: ServiceOperationHealth,
    usage_sync: UsageSyncHealth,
) -> tuple[Literal["HEALTHY", "DEGRADED", "ACTION_REQUIRED"], list[str]]:
    signals: list[str] = []
    if outbox.failed:
        signals.append("OUTBOX_FAILED")
    if outbox.stale_claims:
        signals.append("OUTBOX_STALE_CLAIMS")
    if outbox.retrying:
        signals.append("OUTBOX_RETRYING")
    if outbox.oldest_due_age_seconds >= 60:
        signals.append("OUTBOX_LAGGING")
    if fulfillment.failed:
        signals.append("FULFILLMENT_FAILED")
    if fulfillment.operator_review:
        signals.append("FULFILLMENT_OPERATOR_REVIEW")
    if fulfillment.blocked:
        signals.append("FULFILLMENT_BLOCKED")
    if fulfillment.retry_pending:
        signals.append("FULFILLMENT_RETRYING")
    if service_operations.review_required:
        signals.append("SERVICE_OPERATION_REVIEW_REQUIRED")
    if usage_sync.degraded_runs_last_hour:
        signals.append("USAGE_SYNC_DEGRADED")
    if usage_sync.stale_active_accounts:
        signals.append("USAGE_DATA_STALE")

    action_required = any(
        signal
        in {
            "OUTBOX_FAILED",
            "FULFILLMENT_FAILED",
            "FULFILLMENT_OPERATOR_REVIEW",
            "SERVICE_OPERATION_REVIEW_REQUIRED",
        }
        for signal in signals
    )
    if action_required:
        return "ACTION_REQUIRED", signals
    if signals:
        return "DEGRADED", signals
    return "HEALTHY", signals


def collect_operations_health(
    db: Session,
    now: datetime | None = None,
) -> OperationsHealthSnapshot:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    pending_due = int(
        db.scalar(
            select(func.count())
            .select_from(TransactionalOutboxModel)
            .where(
                TransactionalOutboxModel.status == "PENDING",
                TransactionalOutboxModel.available_at <= now,
            )
        )
        or 0
    )
    retrying = int(
        db.scalar(
            select(func.count())
            .select_from(TransactionalOutboxModel)
            .where(
                TransactionalOutboxModel.status == "PENDING",
                TransactionalOutboxModel.attempt_count > 0,
                TransactionalOutboxModel.failure_category.is_not(None),
            )
        )
        or 0
    )
    failed_outbox = int(
        db.scalar(
            select(func.count())
            .select_from(TransactionalOutboxModel)
            .where(TransactionalOutboxModel.status == "FAILED")
        )
        or 0
    )
    stale_claims = int(
        db.scalar(
            select(func.count())
            .select_from(TransactionalOutboxModel)
            .where(
                TransactionalOutboxModel.status == "CLAIMED",
                TransactionalOutboxModel.claimed_at.is_not(None),
                TransactionalOutboxModel.claimed_at < now - _STALE_CLAIM_AFTER,
            )
        )
        or 0
    )
    oldest_due = db.scalar(
        select(func.min(TransactionalOutboxModel.created_at)).where(
            TransactionalOutboxModel.status == "PENDING",
            TransactionalOutboxModel.available_at <= now,
        )
    )
    outbox = OutboxHealth(
        pending_due=pending_due,
        retrying=retrying,
        failed=failed_outbox,
        stale_claims=stale_claims,
        oldest_due_age_seconds=_age_seconds(now, oldest_due) or 0,
    )

    fulfillment_counts = _status_counts(
        db,
        ServiceFulfillmentRequestModel,
        _FULFILLMENT_STATUSES,
    )
    fulfillment = FulfillmentHealth(
        retry_pending=fulfillment_counts.get("RETRY_PENDING", 0),
        blocked=fulfillment_counts.get("BLOCKED", 0),
        operator_review=fulfillment_counts.get("OPERATOR_REVIEW", 0),
        failed=fulfillment_counts.get("FAILED", 0),
    )

    operation_counts = _status_counts(
        db,
        ServiceOperationModel,
        _IN_PROGRESS_OPERATION_STATUSES + _REVIEW_REQUIRED_OPERATION_STATUSES,
    )
    service_operations = ServiceOperationHealth(
        in_progress=sum(operation_counts.get(status, 0) for status in _IN_PROGRESS_OPERATION_STATUSES),
        review_required=sum(
            operation_counts.get(status, 0) for status in _REVIEW_REQUIRED_OPERATION_STATUSES
        ),
    )

    latest_run = db.scalar(
        select(ServiceUsageSyncRunModel)
        .order_by(ServiceUsageSyncRunModel.started_at.desc())
        .limit(1)
    )
    latest_status = (
        latest_run.status if latest_run is not None and latest_run.status in _USAGE_RUN_STATUSES else "UNKNOWN"
    )
    last_success = db.scalar(
        select(func.max(ServiceUsageSyncRunModel.finished_at)).where(
            ServiceUsageSyncRunModel.status == "SUCCESS"
        )
    )
    degraded_runs = int(
        db.scalar(
            select(func.count())
            .select_from(ServiceUsageSyncRunModel)
            .where(
                ServiceUsageSyncRunModel.status.in_(("PARTIAL", "FAILED")),
                ServiceUsageSyncRunModel.started_at >= now - _RECENT_FAILURE_WINDOW,
            )
        )
        or 0
    )

    latest_aggregate = (
        select(
            ServiceUsageAggregateModel.usage_account_id.label("usage_account_id"),
            func.max(ServiceUsageAggregateModel.calculated_at).label("last_calculated_at"),
        )
        .group_by(ServiceUsageAggregateModel.usage_account_id)
        .subquery()
    )
    stale_active_accounts = int(
        db.scalar(
            select(func.count())
            .select_from(ServiceUsageAccountModel)
            .join(ServiceModel, ServiceModel.id == ServiceUsageAccountModel.service_id)
            .outerjoin(
                latest_aggregate,
                latest_aggregate.c.usage_account_id == ServiceUsageAccountModel.id,
            )
            .where(
                ServiceModel.lifecycle == "ACTIVE",
                or_(
                    latest_aggregate.c.last_calculated_at.is_(None),
                    latest_aggregate.c.last_calculated_at < now - _STALE_USAGE_AFTER,
                ),
            )
        )
        or 0
    )
    usage_sync = UsageSyncHealth(
        latest_status=latest_status,
        latest_run_age_seconds=_age_seconds(
            now,
            latest_run.finished_at or latest_run.started_at if latest_run is not None else None,
        ),
        last_success_age_seconds=_age_seconds(now, last_success),
        degraded_runs_last_hour=degraded_runs,
        stale_active_accounts=stale_active_accounts,
    )

    status, signals = classify_operations_health(
        outbox=outbox,
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )
    return OperationsHealthSnapshot(
        generated_at=now,
        status=status,
        signals=signals,
        outbox=outbox,
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )


def render_prometheus(snapshot: OperationsHealthSnapshot) -> str:
    lines = [
        "# HELP vpnsale_ops_health_state One-hot operational health state for the Telegram production path.",
        "# TYPE vpnsale_ops_health_state gauge",
    ]
    for state in ("HEALTHY", "DEGRADED", "ACTION_REQUIRED"):
        lines.append(f'vpnsale_ops_health_state{{state="{state}"}} {int(snapshot.status == state)}')
    lines.extend(
        [
            "# HELP vpnsale_ops_outbox_pending_due Due transactional-outbox events awaiting work.",
            "# TYPE vpnsale_ops_outbox_pending_due gauge",
            f"vpnsale_ops_outbox_pending_due {snapshot.outbox.pending_due}",
            "# HELP vpnsale_ops_outbox_retrying Transactional-outbox events scheduled after a failed attempt.",
            "# TYPE vpnsale_ops_outbox_retrying gauge",
            f"vpnsale_ops_outbox_retrying {snapshot.outbox.retrying}",
            "# HELP vpnsale_ops_outbox_failed Terminal transactional-outbox failures.",
            "# TYPE vpnsale_ops_outbox_failed gauge",
            f"vpnsale_ops_outbox_failed {snapshot.outbox.failed}",
            "# HELP vpnsale_ops_outbox_stale_claims Claims older than the bounded stale-claim threshold.",
            "# TYPE vpnsale_ops_outbox_stale_claims gauge",
            f"vpnsale_ops_outbox_stale_claims {snapshot.outbox.stale_claims}",
            "# HELP vpnsale_ops_outbox_oldest_due_age_seconds Age of the oldest due outbox event.",
            "# TYPE vpnsale_ops_outbox_oldest_due_age_seconds gauge",
            f"vpnsale_ops_outbox_oldest_due_age_seconds {snapshot.outbox.oldest_due_age_seconds}",
            "# HELP vpnsale_ops_fulfillment_attention Fulfillment items that need retry, configuration or operator attention.",
            "# TYPE vpnsale_ops_fulfillment_attention gauge",
            f'vpnsale_ops_fulfillment_attention{{state="RETRY_PENDING"}} {snapshot.fulfillment.retry_pending}',
            f'vpnsale_ops_fulfillment_attention{{state="BLOCKED"}} {snapshot.fulfillment.blocked}',
            f'vpnsale_ops_fulfillment_attention{{state="OPERATOR_REVIEW"}} {snapshot.fulfillment.operator_review}',
            f'vpnsale_ops_fulfillment_attention{{state="FAILED"}} {snapshot.fulfillment.failed}',
            "# HELP vpnsale_ops_service_operations Paid service operations grouped by safe operator action class.",
            "# TYPE vpnsale_ops_service_operations gauge",
            f'vpnsale_ops_service_operations{{state="IN_PROGRESS"}} {snapshot.service_operations.in_progress}',
            f'vpnsale_ops_service_operations{{state="REVIEW_REQUIRED"}} {snapshot.service_operations.review_required}',
            "# HELP vpnsale_ops_usage_sync_degraded_runs_last_hour Usage sync runs that were partial or failed in the last hour.",
            "# TYPE vpnsale_ops_usage_sync_degraded_runs_last_hour gauge",
            f"vpnsale_ops_usage_sync_degraded_runs_last_hour {snapshot.usage_sync.degraded_runs_last_hour}",
            "# HELP vpnsale_ops_usage_stale_active_accounts Active usage accounts without a fresh aggregate.",
            "# TYPE vpnsale_ops_usage_stale_active_accounts gauge",
            f"vpnsale_ops_usage_stale_active_accounts {snapshot.usage_sync.stale_active_accounts}",
        ]
    )
    if snapshot.usage_sync.latest_run_age_seconds is not None:
        lines.extend(
            [
                "# HELP vpnsale_ops_usage_sync_latest_run_age_seconds Age of the latest usage-sync run.",
                "# TYPE vpnsale_ops_usage_sync_latest_run_age_seconds gauge",
                f"vpnsale_ops_usage_sync_latest_run_age_seconds {snapshot.usage_sync.latest_run_age_seconds}",
            ]
        )
    if snapshot.usage_sync.last_success_age_seconds is not None:
        lines.extend(
            [
                "# HELP vpnsale_ops_usage_sync_last_success_age_seconds Age of the latest fully successful usage-sync run.",
                "# TYPE vpnsale_ops_usage_sync_last_success_age_seconds gauge",
                f"vpnsale_ops_usage_sync_last_success_age_seconds {snapshot.usage_sync.last_success_age_seconds}",
            ]
        )
    for status in _USAGE_RUN_STATUSES:
        lines.append(
            f'vpnsale_ops_usage_sync_latest_status{{status="{status}"}} '
            f"{int(snapshot.usage_sync.latest_status == status)}"
        )
    return "\n".join(lines) + "\n"


@router.get("/health", response_model=OperationsHealthSnapshot)
def operations_health(
    db: Annotated[Session, Depends(get_db_session)],
    _admin: Annotated[AdminModel, Depends(current_admin)],
) -> OperationsHealthSnapshot:
    return collect_operations_health(db)


@router.get("/metrics", response_class=PlainTextResponse)
def operations_metrics(
    db: Annotated[Session, Depends(get_db_session)],
    _admin: Annotated[AdminModel, Depends(current_admin)],
) -> PlainTextResponse:
    return PlainTextResponse(
        render_prometheus(collect_operations_health(db)),
        media_type="text/plain; version=0.0.4",
    )
