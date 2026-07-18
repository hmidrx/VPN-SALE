from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.fleet import (
    FleetBulkOperation,
    FleetBulkOperationItem,
    FleetBulkOperationType,
    FleetCapacitySnapshot,
    FleetDomainError,
    FleetDrainPlan,
    FleetDrainState,
    FleetErrorCode,
    FleetEvacuationBatch,
    FleetEvacuationPlan,
    FleetEvacuationStrategy,
    FleetFailoverProposal,
    FleetHealthObservation,
    FleetHealthPolicyVersion,
    FleetHealthSignalType,
    FleetOperationalState,
    FleetRunbookStep,
    FleetRunbookStepType,
    FleetRunbookVersion,
    FleetSignalState,
    FleetWorkState,
    evaluate_health,
    forecast_capacity,
)


def test_health_freshness_confidence_hysteresis_and_certification_blocks() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    rid = uuid4()
    policy = FleetHealthPolicyVersion(
        uuid4(),
        1,
        frozenset(
            {
                FleetHealthSignalType.PANEL_API_REACHABLE,
                FleetHealthSignalType.CONTRACT_MATCHED,
                FleetHealthSignalType.WRITE_CERTIFICATION_VALID,
            }
        ),
        70,
        2,
        2,
        timedelta(minutes=5),
        timedelta(minutes=1),
    )
    stale = FleetHealthObservation(
        uuid4(),
        rid,
        FleetHealthSignalType.PANEL_API_REACHABLE,
        "worker",
        now - timedelta(hours=1),
        timedelta(minutes=5),
        FleetSignalState.PASSING,
        90,
        "obs-stale",
    )
    assert evaluate_health(rid, policy, (stale,), None, now).state == FleetOperationalState.UNKNOWN
    fail_contract = FleetHealthObservation(
        uuid4(),
        rid,
        FleetHealthSignalType.CONTRACT_MATCHED,
        "certifier",
        now,
        timedelta(minutes=5),
        FleetSignalState.FAILING,
        95,
        "contract-digest-mismatch",
    )
    assert (
        evaluate_health(rid, policy, (stale, fail_contract), None, now).state
        == FleetOperationalState.RECERTIFICATION_REQUIRED
    )
    passing = tuple(
        FleetHealthObservation(
            uuid4(),
            rid,
            signal,
            "worker",
            now,
            timedelta(minutes=5),
            FleetSignalState.PASSING,
            90,
            f"safe-{signal}",
        )
        for signal in policy.required_signals
    )
    assert evaluate_health(rid, policy, passing, None, now).state == FleetOperationalState.ACTIVE
    failing = tuple(
        FleetHealthObservation(
            uuid4(),
            rid,
            signal,
            "worker",
            now,
            timedelta(minutes=5),
            FleetSignalState.FAILING
            if signal == FleetHealthSignalType.PANEL_API_REACHABLE
            else FleetSignalState.PASSING,
            90,
            f"safe-{signal}",
        )
        for signal in policy.required_signals
    )
    first = evaluate_health(rid, policy, failing, None, now)
    assert first.state == FleetOperationalState.DEGRADED
    second = evaluate_health(rid, policy, failing, first, now + timedelta(minutes=1))
    assert second.state == FleetOperationalState.UNAVAILABLE


def test_capacity_accounting_forecast_and_insufficient_data() -> None:
    tid = uuid4()
    now = datetime(2026, 7, 18, tzinfo=UTC)
    snapshot = FleetCapacitySnapshot(uuid4(), tid, 100, 70, 5, 3, 2, 10, 5, 4, 1, now, 80)
    assert snapshot.effective_capacity == 84
    assert snapshot.consumed_capacity == 84
    assert snapshot.available_capacity == 0
    assert snapshot.utilization_basis_points == 10_000
    with pytest.raises(FleetDomainError):
        FleetCapacitySnapshot(uuid4(), tid, -1, 0, 0, 0, 0, 0, 0, 0, 0, now, 80)
    assert forecast_capacity(tid, (snapshot,), now).insufficient_data is True
    history = tuple(
        FleetCapacitySnapshot(
            uuid4(), tid, 100, active, 0, 0, 0, 10, 0, 0, 0, now + timedelta(days=index), 80
        )
        for index, active in enumerate((50, 55, 60))
    )
    forecast = forecast_capacity(tid, history, now + timedelta(days=3))
    assert forecast.insufficient_data is False
    assert forecast.observed_net_growth_per_day == 5
    assert forecast.estimated_exhaustion_at is not None


def test_drain_evacuation_failover_bulk_and_runbook_guardrails() -> None:
    target = uuid4()
    drain = FleetDrainPlan(uuid4(), target, FleetDrainState.BLOCK_NEW_ALLOCATIONS, 1)
    with pytest.raises(FleetDomainError):
        drain.assert_can_allocate()
    with pytest.raises(FleetDomainError):
        drain.complete()
    assert (
        FleetDrainPlan(uuid4(), target, FleetDrainState.DRAINING, 1, 1).complete().state
        == FleetDrainState.COMPLETED
    )
    plan = FleetEvacuationPlan(
        uuid4(),
        target,
        (uuid4(), uuid4()),
        (uuid4(),),
        (uuid4(),),
        0,
        FleetEvacuationStrategy.MIGRATE_LOW_RISK_FIRST,
        2,
        datetime.now(UTC) + timedelta(minutes=10),
    )
    plan.assert_current(datetime.now(UTC))
    paused = FleetEvacuationBatch(
        uuid4(), plan.plan_id, plan.eligible_service_ids, failed_count=0, uncertain_count=1
    ).with_guardrails(1)
    assert paused.state == FleetWorkState.PAUSED
    requester = uuid4()
    proposal = FleetFailoverProposal(
        uuid4(),
        target,
        (uuid4(),),
        10,
        8,
        "HIGH",
        datetime.now(UTC) + timedelta(minutes=10),
        requested_by=requester,
    )
    with pytest.raises(FleetDomainError) as exc:
        proposal.approve(requester, datetime.now(UTC))
    assert exc.value.code == FleetErrorCode.FAILOVER_SELF_APPROVAL_DENIED
    assert proposal.approve(uuid4(), datetime.now(UTC)).approved_by is not None
    operation = FleetBulkOperation(
        uuid4(),
        FleetBulkOperationType.REQUEST_SERVICE_RECONCILIATION,
        (uuid4(), uuid4()),
        "review selected services",
    ).validate()
    assert operation.state == FleetWorkState.READY
    item = FleetBulkOperationItem(
        uuid4(), operation.operation_id, operation.target_ids[0], FleetWorkState.COMPLETED
    )
    assert item.retry() == item
    runbook = FleetRunbookVersion(
        uuid4(),
        uuid4(),
        1,
        (
            FleetRunbookStep(
                FleetRunbookStepType.INSPECT_HEALTH_EVIDENCE, "Inspect", "fleet.read_health"
            ),
        ),
    ).publish()
    assert runbook.published is True
    with pytest.raises(ValueError):
        FleetRunbookStepType("SHELL")
