from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.provider_mutations import ProviderOperationStatus
from vpnsale_domain.service_operations import (
    ServiceOperation,
    ServiceOperationActorType,
    ServiceOperationAttachmentPlan,
    ServiceOperationAttachmentSuccessPolicy,
    ServiceOperationCommercialOrigin,
    ServiceOperationDesiredChange,
    ServiceOperationDomainError,
    ServiceOperationErrorCode,
    ServiceOperationPolicyVersion,
    ServiceOperationPriceRule,
    ServiceOperationStatus,
    ServiceOperationType,
    ServiceUsageSnapshot,
    validate_desired_reduction,
)


def policy(*, billable: bool = True, high_risk: bool = False) -> ServiceOperationPolicyVersion:
    op = ServiceOperationType.ADD_TRAFFIC if billable else ServiceOperationType.RESET_TRAFFIC
    return ServiceOperationPolicyVersion(
        policy_id=uuid4(),
        version_id=uuid4(),
        version_number=1,
        status="PUBLISHED",
        allowed_operation_types=frozenset({op, ServiceOperationType.REDUCE_TRAFFIC}),
        customer_self_service=frozenset({op}),
        reseller_service=frozenset({op}),
        admin_only=frozenset({ServiceOperationType.REDUCE_TRAFFIC}),
        billable_operations=frozenset({op}) if billable else frozenset(),
        high_risk_operations=frozenset({ServiceOperationType.REDUCE_TRAFFIC})
        if high_risk
        else frozenset(),
        required_permissions={ServiceOperationType.REDUCE_TRAFFIC: "services.reduce_entitlement"},
        price_rule=ServiceOperationPriceRule.PER_GIB_RIAL,
        unit_price_rial=10_000,
        min_amount=1,
        max_amount=10,
        increment=1,
        attachment_success_policy=ServiceOperationAttachmentSuccessPolicy.ALL_REQUIRED,
        published_at=datetime(2026, 7, 18, tzinfo=UTC),
    )


def test_billable_operation_creates_backend_quote_and_awaits_payment() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    operation = ServiceOperation.create(
        service_id=uuid4(),
        operation_type=ServiceOperationType.ADD_TRAFFIC,
        requester_type=ServiceOperationActorType.CUSTOMER,
        requester_id="customer-1",
        policy_version=policy(),
        desired_change=ServiceOperationDesiredChange(traffic_delta_bytes=2),
        idempotency_key_digest="sha256:test",
        reason_code="customer_addon",
        now=now,
        amount=2,
        commercial_origin=ServiceOperationCommercialOrigin.CUSTOMER_CHECKOUT,
    )
    assert operation.status is ServiceOperationStatus.AWAITING_PAYMENT
    assert operation.quote is not None
    assert operation.quote.price_rial == 20_000


def test_payment_event_moves_once_to_queue_without_financial_rewrite() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    operation = ServiceOperation.create(
        service_id=uuid4(),
        operation_type=ServiceOperationType.ADD_TRAFFIC,
        requester_type=ServiceOperationActorType.CUSTOMER,
        requester_id="customer-1",
        policy_version=policy(),
        desired_change=ServiceOperationDesiredChange(traffic_delta_bytes=1),
        idempotency_key_digest="sha256:test",
        reason_code="paid",
        now=now,
        amount=1,
    )
    paid = operation.mark_paid(order_id=uuid4(), invoice_id=uuid4(), payment_id=uuid4(), now=now)
    assert paid.status is ServiceOperationStatus.QUEUED
    with pytest.raises(ServiceOperationDomainError) as exc:
        paid.mark_paid(order_id=uuid4(), invoice_id=uuid4(), payment_id=uuid4(), now=now)
    assert exc.value.code is ServiceOperationErrorCode.OPERATION_STATUS_INVALID


def test_self_approval_denied_for_high_risk_reduction() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    operation = ServiceOperation.create(
        service_id=uuid4(),
        operation_type=ServiceOperationType.REDUCE_TRAFFIC,
        requester_type=ServiceOperationActorType.ADMIN,
        requester_id="admin-1",
        policy_version=policy(billable=False, high_risk=True),
        desired_change=ServiceOperationDesiredChange(traffic_delta_bytes=-1),
        idempotency_key_digest="sha256:test",
        reason_code="impact_review",
        now=now,
    )
    assert operation.status is ServiceOperationStatus.PENDING_APPROVAL
    with pytest.raises(ServiceOperationDomainError) as exc:
        operation.approve("admin-1", "approve", now)
    assert exc.value.code is ServiceOperationErrorCode.OPERATION_SELF_APPROVAL_DENIED


def test_reduction_below_verified_usage_is_blocked() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    usage = ServiceUsageSnapshot(
        now,
        lifetime_used_bytes=100,
        provider_counter_bytes=50,
        stale_after=now + timedelta(minutes=5),
        source="reconciled",
    )
    with pytest.raises(ServiceOperationDomainError) as exc:
        validate_desired_reduction(
            operation_type=ServiceOperationType.REDUCE_TRAFFIC,
            current_traffic_limit_bytes=200,
            desired_traffic_limit_bytes=99,
            current_expiry=None,
            desired_expiry=None,
            usage=usage,
            now=now,
        )
    assert exc.value.code is ServiceOperationErrorCode.OPERATION_REDUCTION_BELOW_USAGE


def test_required_attachment_uncertainty_prevents_success() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    operation = ServiceOperation.create(
        service_id=uuid4(),
        operation_type=ServiceOperationType.RESET_TRAFFIC,
        requester_type=ServiceOperationActorType.CUSTOMER,
        requester_id="customer-1",
        policy_version=policy(billable=False),
        desired_change=ServiceOperationDesiredChange(reset_generation=2),
        idempotency_key_digest="sha256:test",
        reason_code="reset",
        now=now,
    ).begin_execution()
    plan = ServiceOperationAttachmentPlan(
        uuid4(),
        True,
        uuid4(),
        "RESET_TRAFFIC",
        "sha256:expected",
        ProviderOperationStatus.UNCERTAIN,
        False,
        True,
    )
    finished = operation.finish_verification((plan,))
    assert finished.status is ServiceOperationStatus.UNCERTAIN
