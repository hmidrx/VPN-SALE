"""Direct payment transition rules for billable service operations."""

from __future__ import annotations

from datetime import datetime

from vpnsale_domain.service_operations import (
    ServiceOperationDomainError,
    ServiceOperationErrorCode,
    ServiceOperationStatus,
    ServiceOperationType,
)


def direct_wallet_payment_target_status(
    *,
    current_status: ServiceOperationStatus,
    operation_type: ServiceOperationType,
    high_risk_operations: frozenset[ServiceOperationType],
    quote_expires_at: datetime,
    now: datetime,
) -> ServiceOperationStatus:
    """Validate a direct wallet payment and return its post-payment operation state."""
    if current_status is not ServiceOperationStatus.AWAITING_PAYMENT:
        raise ServiceOperationDomainError(
            ServiceOperationErrorCode.OPERATION_STATUS_INVALID,
            "operation is not awaiting payment",
        )
    if quote_expires_at.tzinfo is None or now.tzinfo is None or quote_expires_at <= now:
        raise ServiceOperationDomainError(
            ServiceOperationErrorCode.OPERATION_PAYMENT_REQUIRED,
            "quote expired",
        )
    if operation_type in high_risk_operations:
        return ServiceOperationStatus.PENDING_APPROVAL
    return ServiceOperationStatus.QUEUED
