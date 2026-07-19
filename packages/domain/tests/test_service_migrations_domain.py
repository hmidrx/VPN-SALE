from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from vpnsale_domain.delivery import (
    DeliveryAddressSource,
    DeliveryProfileStatus,
    DeliveryProfileVersion,
    DeliveryProtocol,
    DeliveryRawSettings,
    DeliverySecurity,
    DeliveryTransport,
)
from vpnsale_domain.provider_mutations import ProviderWriteMode
from vpnsale_domain.service_migrations import (
    MigrationDomainError,
    MigrationEligibilityOutcome,
    ServiceMigration,
    ServiceMigrationApproval,
    ServiceMigrationCleanupStrategy,
    ServiceMigrationCutoverStrategy,
    ServiceMigrationPolicyVersion,
    ServiceMigrationRequest,
    ServiceMigrationStatus,
    ServiceMigrationTargetCandidate,
    ServiceMigrationType,
    attach_reservations,
    capture_source_snapshot,
    choose_credential_strategy,
    commit_cutover,
    create_migration,
    evaluate_eligibility,
    mark_target_verified,
    reconcile_migration,
    request_rollback,
    reserve_target_capacity,
    retire_source,
    simulate_migration_plan,
)
from vpnsale_domain.services import (
    AllocationTarget,
    AttachmentStatus,
    Service,
    ServiceAttachment,
    ServiceEntitlement,
    ServiceLifecycle,
    TargetRole,
)


def _entitlement(protocol: str = "VLESS") -> ServiceEntitlement:
    now = datetime.now(UTC)
    return ServiceEntitlement(
        uuid4(),
        uuid4(),
        "plan-migration",
        "Migration plan",
        10_000,
        3600,
        now,
        now + timedelta(hours=1),
        2,
        1,
        2,
        0,
        "CUSTOMER",
        "cust-ref",
        uuid4(),
        None,
        uuid4(),
        uuid4(),
        uuid4(),
        "VPN SALE migration",
        (protocol,),
    )


def _target(
    priority: int, provider: str = "sanaei-3x-ui", protocol: str = "VLESS", capacity: int = 4
) -> ServiceMigrationTargetCandidate:
    now = datetime.now(UTC)
    target = AllocationTarget(
        uuid4(),
        uuid4(),
        uuid4(),
        f"inbound-{priority}",
        provider,
        "v1-certified",
        "sha256:contract",
        TargetRole.REQUIRED,
        priority,
        1,
        capacity,
        1,
        0,
        0,
        now,
        timedelta(minutes=10),
        True,
        False,
        ProviderWriteMode.WRITE_ENABLED,
        True,
        frozenset({"tehran"}),
    )
    profile = DeliveryProfileVersion(
        uuid4(),
        uuid4(),
        1,
        DeliveryProfileStatus.PUBLISHED,
        DeliveryProtocol(protocol),
        DeliveryTransport.RAW,
        DeliverySecurity.NONE,
        DeliveryAddressSource.FIXED_DOMAIN,
        "edge.example.test",
        443,
        "safe remark",
        "تهران",
        raw=DeliveryRawSettings(),
        published_at=now,
    )
    return ServiceMigrationTargetCandidate(
        target,
        f"تهران {priority}",
        protocol,
        profile,
        True,
        frozenset({"CREATE_IDENTITY", "DISABLE_IDENTITY"}),
    )


def _service() -> Service:
    entitlement = _entitlement()
    source_target = _target(1).target
    attachments = tuple(
        ServiceAttachment(
            uuid4(),
            UUID(int=1),
            source_target,
            True,
            AttachmentStatus.VERIFIED,
            "VERIFIED",
            uuid4(),
            f"remote-{idx}",
            f"sha256:fingerprint-{idx}",
        )
        for idx in range(2)
    )
    return Service(UUID(int=1), "SVC-PUBLIC", entitlement, ServiceLifecycle.ACTIVE, attachments)


def _policy() -> ServiceMigrationPolicyVersion:
    return ServiceMigrationPolicyVersion(
        uuid4(),
        uuid4(),
        1,
        "VALIDATED",
        frozenset({"sanaei-3x-ui", "pasarguard"}),
        frozenset({"sanaei-3x-ui", "pasarguard"}),
        frozenset({"VLESS", "TROJAN"}),
        True,
        True,
        True,
        frozenset(
            {
                ServiceMigrationCutoverStrategy.WARM,
                ServiceMigrationCutoverStrategy.COLD,
                ServiceMigrationCutoverStrategy.DUAL_ACTIVE_GRACE,
            }
        ),
        frozenset(
            {
                ServiceMigrationCleanupStrategy.DISABLE_ONLY,
                ServiceMigrationCleanupStrategy.DELETE_IDENTITY,
                ServiceMigrationCleanupStrategy.RETIRE_AFTER_GRACE,
            }
        ),
        timedelta(minutes=30),
        timedelta(minutes=10),
        timedelta(minutes=5),
        frozenset({"CREATE_IDENTITY"}),
        2,
        True,
        True,
        timedelta(hours=2),
    ).publish(datetime.now(UTC))


def _request(
    kind: ServiceMigrationType = ServiceMigrationType.PANEL_MOVE,
) -> ServiceMigrationRequest:
    return ServiceMigrationRequest(
        uuid4(),
        UUID(int=1),
        kind,
        uuid4(),
        "MAINTENANCE",
        ServiceMigrationCutoverStrategy.WARM,
        ServiceMigrationCleanupStrategy.RETIRE_AFTER_GRACE,
    )


def _migration() -> tuple[
    Service,
    ServiceMigrationPolicyVersion,
    ServiceMigrationRequest,
    ServiceMigration,
]:
    now = datetime.now(UTC)
    service = _service()
    request = _request()
    policy = _policy()
    snapshot = capture_source_snapshot(service, now, 1_000, 900, uuid4())
    plan = simulate_migration_plan(
        service, request, policy, snapshot, (_target(1), _target(2)), now
    )
    reservations = reserve_target_capacity(plan, service.service_id, now, timedelta(minutes=20))
    plan = attach_reservations(plan, reservations)
    for item in plan.attachment_plans:
        plan = mark_target_verified(plan, item.attachment_plan_id, uuid4())
    migration = create_migration(service, request, policy, snapshot, plan, now)
    approval = ServiceMigrationApproval(
        uuid4(),
        migration.migration_id,
        uuid4(),
        request.requested_by,
        migration.plan_digest,
        False,
        now,
        now + timedelta(minutes=30),
    )
    migration = migration.transition(
        ServiceMigrationStatus.AWAITING_APPROVAL,
        request.requested_by,
        migration.version,
        migration.plan_digest,
        now,
    )
    migration = migration.transition(
        ServiceMigrationStatus.APPROVED,
        approval.actor_id,
        migration.version,
        migration.plan_digest,
        now,
        approval,
    )
    return service, policy, request, migration


def test_eligibility_blocks_conflicts_and_rejects_incompatible_targets() -> None:
    service = _service()
    policy = _policy()
    now = datetime.now(UTC)
    conflict = evaluate_eligibility(service, _request(), policy, (_target(1),), False, True, now)
    assert conflict.outcome is MigrationEligibilityOutcome.CONFLICTING_OPERATION
    incompatible = _target(1, capacity=1)
    empty = evaluate_eligibility(service, _request(), policy, (incompatible,), False, False, now)
    assert empty.outcome is MigrationEligibilityOutcome.TARGET_CAPACITY_UNAVAILABLE


def test_simulation_is_deterministic_sanitized_and_preserves_history() -> None:
    service = _service()
    policy = _policy()
    now = datetime.now(UTC)
    snapshot = capture_source_snapshot(service, now, 1_234, 2_000, uuid4())
    candidates = (_target(2), _target(1))
    first = simulate_migration_plan(service, _request(), policy, snapshot, candidates, now)
    second = simulate_migration_plan(service, _request(), policy, snapshot, candidates, now)
    assert first.target_candidate_labels == second.target_candidate_labels == ("تهران 1", "تهران 2")
    assert "target_id" not in candidates[0].sanitized()
    assert snapshot.local_lifetime_usage_bytes == 1_234
    assert snapshot.expires_at == service.entitlement.expires_at


def test_credential_strategy_preserves_only_compatible_protocols_and_rotates_cross_protocol() -> (
    None
):
    policy = _policy()
    req = _request()
    assert choose_credential_strategy(
        "VLESS", "VLESS", _target(1), req, policy, True
    ).value.startswith("PRESERVE")
    assert choose_credential_strategy(
        "VLESS", "TROJAN", _target(1, protocol="TROJAN"), req, policy, True
    ).value.startswith("ROTATE")
    security_req = ServiceMigrationRequest(
        uuid4(),
        UUID(int=1),
        ServiceMigrationType.SECURITY_ROTATION_MOVE,
        uuid4(),
        "SECURITY",
        ServiceMigrationCutoverStrategy.WARM,
        ServiceMigrationCleanupStrategy.DISABLE_ONLY,
    )
    assert (
        choose_credential_strategy("VLESS", "VLESS", _target(1), security_req, policy, False).value
        == "ROTATE_PER_ATTACHMENT_CREDENTIAL"
    )


def test_reservation_cutover_stable_subscription_and_reconciliation() -> None:
    _service_obj, _policy_obj, _request_obj, migration_obj = _migration()
    migration = migration_obj
    assert migration.approval is not None
    approval = migration.approval
    now = datetime.now(UTC)
    ready = migration.transition(
        ServiceMigrationStatus.RESERVING_TARGET,
        approval.actor_id,
        migration.version,
        migration.plan_digest,
        now,
    )
    ready = ready.transition(
        ServiceMigrationStatus.PREPARING_TARGET,
        approval.actor_id,
        ready.version,
        ready.plan_digest,
        now,
    )
    ready = ready.transition(
        ServiceMigrationStatus.PROVISIONING_TARGET,
        approval.actor_id,
        ready.version,
        ready.plan_digest,
        now,
    )
    ready = ready.transition(
        ServiceMigrationStatus.VERIFYING_TARGET,
        approval.actor_id,
        ready.version,
        ready.plan_digest,
        now,
    )
    ready = ready.transition(
        ServiceMigrationStatus.READY_FOR_CUTOVER,
        approval.actor_id,
        ready.version,
        ready.plan_digest,
        now,
    )
    cut = commit_cutover(ready, approval.actor_id, ready.version, uuid4(), "stable-token", now)
    assert cut.status is ServiceMigrationStatus.DUAL_ACTIVE_GRACE
    assert cut.cutover is not None
    assert cut.cutover.stable_subscription_token_digest.startswith("sha256:")
    assert (
        reconcile_migration(
            cut, False, True, cut.cutover.new_delivery_revision_id, False
        ).outcome.value
        == "MATCHED"
    )


def test_self_approval_and_stale_plan_are_denied() -> None:
    service = _service()
    policy = _policy()
    request = _request()
    now = datetime.now(UTC)
    snapshot = capture_source_snapshot(service, now, 0, 0, None)
    plan = simulate_migration_plan(
        service, request, policy, snapshot, (_target(1), _target(2)), now
    )
    migration = create_migration(service, request, policy, snapshot, plan, now)
    approval = ServiceMigrationApproval(
        uuid4(),
        migration.migration_id,
        request.requested_by,
        request.requested_by,
        migration.plan_digest,
        True,
        now,
        now + timedelta(minutes=5),
    )
    waiting = migration.transition(
        ServiceMigrationStatus.AWAITING_APPROVAL,
        request.requested_by,
        migration.version,
        migration.plan_digest,
        now,
    )
    with pytest.raises(MigrationDomainError):
        waiting.transition(
            ServiceMigrationStatus.APPROVED,
            request.requested_by,
            waiting.version,
            waiting.plan_digest,
            now,
            approval,
        )
    with pytest.raises(MigrationDomainError):
        waiting.transition(
            ServiceMigrationStatus.APPROVED, uuid4(), waiting.version, "sha256:stale", now, approval
        )


def test_source_cleanup_rollback_orphan_and_cross_provider_failover_boundaries() -> None:
    _service_obj, _policy_obj, _request_obj, migration_obj = _migration()
    migration = migration_obj
    assert migration.approval is not None
    approval = migration.approval
    with pytest.raises(MigrationDomainError):
        retire_source(
            migration,
            approval.actor_id,
            migration.version,
            datetime.now(UTC),
            False,
            False,
        )
    rollback = request_rollback(
        migration, approval.actor_id, migration.version, datetime.now(UTC), True, False
    )
    assert rollback.rollback is not None
    failover = _request(ServiceMigrationType.CONTROLLED_FAILOVER)
    snapshot = capture_source_snapshot(
        _service(), datetime.now(UTC), 50, 40, None, source_uncertain=True
    )
    plan = simulate_migration_plan(
        _service(),
        failover,
        _policy(),
        snapshot,
        (_target(1, "pasarguard"), _target(2, "pasarguard")),
        datetime.now(UTC),
    )
    assert plan.high_risk is True
    assert plan.rollback_feasible is False
