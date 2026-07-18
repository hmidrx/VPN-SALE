from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.orders import OrderFinancialStatus, OrderStatus
from vpnsale_domain.provider_mutations import ProviderWriteMode
from vpnsale_domain.services import (
    AllocationPolicyStatus,
    AllocationPolicyVersion,
    AllocationStrategy,
    AllocationTarget,
    AttachmentStatus,
    CommercialOrderState,
    IdentityStrategy,
    Service,
    ServiceDomainError,
    ServiceEntitlement,
    ServiceLifecycle,
    TargetRole,
    build_fulfillment_request,
    reconcile_service,
    select_targets,
)


def _entitlement() -> ServiceEntitlement:
    now = datetime.now(UTC)
    return ServiceEntitlement(
        product_id=uuid4(),
        product_version_id=uuid4(),
        plan_reference="plan-basic-v1",
        product_label="Safe VPN plan",
        traffic_limit_bytes=1000,
        duration_seconds=3600,
        starts_at=now,
        expires_at=now + timedelta(hours=1),
        device_limit=1,
        quantity_unit_index=1,
        required_attachment_count=2,
        optional_attachment_count=0,
        payer_type="CUSTOMER",
        payer_reference="cust-public-ref",
        beneficiary_customer_id=uuid4(),
        reseller_id=None,
        order_id=uuid4(),
        invoice_id=uuid4(),
        payment_id=uuid4(),
        safe_remark="VPN-SALE service",
    )


def _target(priority: int = 1, capacity: int = 2) -> AllocationTarget:
    now = datetime.now(UTC)
    return AllocationTarget(
        target_id=uuid4(),
        panel_id=uuid4(),
        node_id=uuid4(),
        inbound_id=f"inbound-{priority}",
        provider_kind="sanaei-3x-ui",
        provider_version="certified-v1",
        contract_digest="sha256:abc",
        role=TargetRole.REQUIRED,
        priority=priority,
        weight=1,
        max_capacity=capacity,
        safety_reserve=0,
        active_allocations=0,
        pending_reservations=0,
        inventory_observed_at=now,
        inventory_max_age=timedelta(minutes=5),
        healthy=True,
        maintenance=False,
        write_mode=ProviderWriteMode.WRITE_ENABLED,
        supports_shared_identity=True,
        tags=frozenset({"iran"}),
    )


def test_paid_order_builds_stable_fulfillment_key_and_blocks_unpaid() -> None:
    state = CommercialOrderState(
        uuid4(), uuid4(), OrderStatus.READY_FOR_FULFILLMENT, OrderFinancialStatus.PAID, "CAPTURED"
    )
    request = build_fulfillment_request(state, 1, uuid4(), "payer")
    duplicate = build_fulfillment_request(state, 1, uuid4(), "payer")
    assert request.deduplication_key == duplicate.deduplication_key
    with pytest.raises(ServiceDomainError):
        build_fulfillment_request(
            CommercialOrderState(
                uuid4(),
                uuid4(),
                OrderStatus.PENDING_PAYMENT,
                OrderFinancialStatus.UNPAID,
                "RESERVED",
            ),
            1,
            uuid4(),
            "payer",
        )


def test_allocation_is_deterministic_and_capacity_aware() -> None:
    now = datetime.now(UTC)
    policy = AllocationPolicyVersion(
        uuid4(),
        uuid4(),
        1,
        AllocationPolicyStatus.VALIDATED,
        AllocationStrategy.ALL_REQUIRED_TARGETS,
        "ALL_REQUIRED",
        IdentityStrategy.SHARED,
        2,
        frozenset({"iran"}),
    ).publish(now)
    targets = (_target(2), _target(1), _target(3, capacity=0))
    first = select_targets(policy, targets, "service-key", now)
    second = select_targets(policy, targets, "service-key", now)
    assert [t.target_id for t in first.selected_targets] == [
        t.target_id for t in second.selected_targets
    ]
    assert len(first.selected_targets) == 2
    assert "ALLOCATION_CAPACITY_EXHAUSTED" in first.rejected_reason_codes


def test_service_cannot_activate_until_required_attachments_verified() -> None:
    service = Service(uuid4(), "svc_public", _entitlement(), ServiceLifecycle.VERIFYING)
    with pytest.raises(ServiceDomainError):
        service.transition(ServiceLifecycle.ACTIVE, "verified")
    target = _target()
    attachment = __import__(
        "vpnsale_domain.services", fromlist=["ServiceAttachment"]
    ).ServiceAttachment(
        uuid4(),
        service.service_id,
        target,
        True,
        AttachmentStatus.VERIFIED,
        "VERIFIED",
        remote_identity_reference="remote-1",
        credential_fingerprint="sha256:fingerprint",
    )
    active = Service(
        service.service_id,
        service.public_reference,
        service.entitlement,
        ServiceLifecycle.VERIFYING,
        (attachment,),
    ).transition(ServiceLifecycle.ACTIVE, "verified")
    assert active.lifecycle is ServiceLifecycle.ACTIVE


def test_reconciliation_flags_missing_remote_identity() -> None:
    service = Service(uuid4(), "svc_public", _entitlement(), ServiceLifecycle.ACTIVE)
    target = _target()
    attachment = __import__(
        "vpnsale_domain.services", fromlist=["ServiceAttachment"]
    ).ServiceAttachment(
        uuid4(),
        service.service_id,
        target,
        True,
        AttachmentStatus.VERIFIED,
        "VERIFIED",
        remote_identity_reference="remote-1",
        credential_fingerprint="sha256:fingerprint",
    )
    issues = reconcile_service(
        Service(
            service.service_id,
            service.public_reference,
            service.entitlement,
            ServiceLifecycle.ACTIVE,
            (attachment,),
        ),
        frozenset(),
    )
    assert issues[0].outcome == "REMOTE_MISSING"
