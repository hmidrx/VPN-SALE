"""Shared safety guard for concurrent paid service operations.

A customer may quote multiple operations, but only one paid/in-flight mutation may be
allowed to advance for a service at a time. Unresolved provider outcomes block new paid
work until they are explicitly resolved or compensated.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .service_models import ServiceOperationModel

SERVICE_OPERATION_IN_FLIGHT_STATES = frozenset(
    {
        "PENDING_APPROVAL",
        "QUEUED",
        "EXECUTING",
        "VERIFYING",
        "RECONCILING",
    }
)
SERVICE_OPERATION_UNRESOLVED_STATES = frozenset(
    {
        "PARTIALLY_APPLIED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "MANUAL_REVIEW",
    }
)
SERVICE_OPERATION_BLOCKING_STATES = (
    SERVICE_OPERATION_IN_FLIGHT_STATES | SERVICE_OPERATION_UNRESOLVED_STATES
)


@dataclass(frozen=True)
class ServiceOperationBlocker:
    operation_id: str
    status: str
    reason_code: str


def blocker_reason_for_status(status: str) -> str | None:
    if status in SERVICE_OPERATION_UNRESOLVED_STATES:
        return "SERVICE_OPERATION_REVIEW_REQUIRED"
    if status in SERVICE_OPERATION_IN_FLIGHT_STATES:
        return "SERVICE_OPERATION_IN_PROGRESS"
    return None


def blocker_http_detail(blocker: ServiceOperationBlocker) -> str:
    if blocker.reason_code == "SERVICE_OPERATION_REVIEW_REQUIRED":
        return "service_operation_review_required"
    if blocker.reason_code == "SERVICE_OPERATION_IN_PROGRESS":
        return "service_operation_in_progress"
    raise RuntimeError("blocking operation reason is not classified")


def find_service_operation_blocker(
    db: Session,
    service_id: str,
    *,
    exclude_operation_id: str | None = None,
) -> ServiceOperationBlocker | None:
    """Return the strongest same-service blocker, preferring unresolved outcomes."""

    for statuses in (
        SERVICE_OPERATION_UNRESOLVED_STATES,
        SERVICE_OPERATION_IN_FLIGHT_STATES,
    ):
        statement = (
            select(ServiceOperationModel)
            .where(
                ServiceOperationModel.service_id == service_id,
                ServiceOperationModel.status.in_(statuses),
            )
            .order_by(ServiceOperationModel.created_at, ServiceOperationModel.id)
            .limit(1)
        )
        if exclude_operation_id is not None:
            statement = statement.where(ServiceOperationModel.id != exclude_operation_id)
        operation = db.scalar(statement)
        if operation is not None:
            reason_code = blocker_reason_for_status(operation.status)
            if reason_code is None:
                raise RuntimeError("blocking operation status is not classified")
            return ServiceOperationBlocker(operation.id, operation.status, reason_code)
    return None
