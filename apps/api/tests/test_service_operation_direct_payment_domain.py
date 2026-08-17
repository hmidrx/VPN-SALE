from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from vpnsale_domain.service_operation_payments import direct_wallet_payment_target_status
from vpnsale_domain.service_operations import (
    ServiceOperationDomainError,
    ServiceOperationStatus,
    ServiceOperationType,
)


def test_direct_wallet_payment_moves_normal_operation_to_queue() -> None:
    now = datetime.now(UTC)

    assert (
        direct_wallet_payment_target_status(
            current_status=ServiceOperationStatus.AWAITING_PAYMENT,
            operation_type=ServiceOperationType.RENEW,
            high_risk_operations=frozenset(),
            quote_expires_at=now + timedelta(minutes=5),
            now=now,
        )
        is ServiceOperationStatus.QUEUED
    )


def test_direct_wallet_payment_preserves_high_risk_approval_gate() -> None:
    now = datetime.now(UTC)

    assert (
        direct_wallet_payment_target_status(
            current_status=ServiceOperationStatus.AWAITING_PAYMENT,
            operation_type=ServiceOperationType.ADD_TRAFFIC,
            high_risk_operations=frozenset({ServiceOperationType.ADD_TRAFFIC}),
            quote_expires_at=now + timedelta(minutes=5),
            now=now,
        )
        is ServiceOperationStatus.PENDING_APPROVAL
    )


def test_direct_wallet_payment_rejects_expired_quote() -> None:
    now = datetime.now(UTC)

    with pytest.raises(ServiceOperationDomainError):
        direct_wallet_payment_target_status(
            current_status=ServiceOperationStatus.AWAITING_PAYMENT,
            operation_type=ServiceOperationType.RENEW,
            high_risk_operations=frozenset(),
            quote_expires_at=now - timedelta(seconds=1),
            now=now,
        )
