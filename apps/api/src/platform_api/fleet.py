from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from vpnsale_domain.fleet import (
    FleetBulkOperation,
    FleetBulkOperationType,
    FleetCapacitySnapshot,
    FleetDrainPlan,
    FleetDrainState,
    FleetErrorCode,
    FleetEvacuationPlan,
    FleetEvacuationStrategy,
    FleetFailoverProposal,
    FleetHealthObservation,
    FleetHealthPolicyVersion,
    FleetHealthSignalType,
    FleetMaintenanceState,
    FleetMaintenanceWindow,
    FleetOperationalState,
    FleetRecoveryProposal,
    FleetResource,
    FleetResourceType,
    FleetRunbookStep,
    FleetRunbookStepType,
    FleetRunbookVersion,
    FleetSignalState,
    evaluate_health,
    forecast_capacity,
)

from .management import require_perm

admin_router = APIRouter(prefix="/api/v1/admin/fleet", tags=["admin-fleet"])
customer_router = APIRouter(prefix="/api/v1/customer/fleet-status", tags=["customer-fleet-status"])
reseller_router = APIRouter(prefix="/api/v1/reseller/fleet-status", tags=["reseller-fleet-status"])

_RESOURCES: dict[UUID, FleetResource] = {}
_HEALTH: list[FleetHealthObservation] = []
_CAPACITY: list[FleetCapacitySnapshot] = []
_MAINTENANCE: dict[UUID, FleetMaintenanceWindow] = {}
_DRAINS: dict[UUID, FleetDrainPlan] = {}
_EVACUATIONS: dict[UUID, FleetEvacuationPlan] = {}
_FAILOVER: dict[UUID, FleetFailoverProposal] = {}
_RECOVERY: dict[UUID, FleetRecoveryProposal] = {}
_BULK: dict[UUID, FleetBulkOperation] = {}
_RUNBOOKS: dict[UUID, FleetRunbookVersion] = {}


class FleetResourceResponse(BaseModel):
    resource_id: UUID
    resource_type: str
    safe_label: str
    provider_kind: str | None
    parent_resource_id: UUID | None
    state: str
    archived: bool
    version: int


class HealthObservationRequest(BaseModel):
    resource_id: UUID
    signal_type: str
    source: str = Field(max_length=80)
    state: str
    confidence: int = Field(ge=0, le=100)
    evidence_reference: str = Field(max_length=120)
    freshness_seconds: int = Field(default=300, ge=30, le=86400)


class HealthEvaluationResponse(BaseModel):
    resource_id: UUID
    state: str
    confidence: int
    stale_signal_count: int
    failing_signal_count: int
    proposal_recommended: bool
    limitation: str = (
        "control-plane/provider-reported health only; not verified customer data-plane connectivity"
    )


class CapacitySnapshotRequest(BaseModel):
    target_id: UUID
    hard_capacity: int = Field(ge=0)
    active_allocations: int = Field(ge=0)
    pending_reservations: int = Field(ge=0)
    migration_reservations: int = Field(ge=0)
    dual_active_consumption: int = Field(default=0, ge=0)
    safety_reserve: int = Field(default=0, ge=0)
    maintenance_reserve: int = Field(default=0, ge=0)
    uncertain_identities: int = Field(default=0, ge=0)
    stale_inventory_penalty: int = Field(default=0, ge=0)
    confidence: int = Field(default=80, ge=0, le=100)


class CapacitySnapshotResponse(BaseModel):
    target_id: UUID
    hard_capacity: int
    effective_capacity: int
    active_allocations: int
    pending_reservations: int
    migration_reservations: int
    dual_active_consumption: int
    safety_reserve: int
    uncertain_identities: int
    available_capacity: int
    utilization_basis_points: int
    confidence: int


class MaintenanceRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    reason: str = Field(min_length=8, max_length=500)
    resource_ids: list[UUID] = Field(min_length=1, max_length=50)
    planned_start: datetime
    planned_end: datetime
    expected_impact: str = Field(max_length=500)


class DrainRequest(BaseModel):
    target_id: UUID
    active_attachment_count: int = Field(ge=0)


class EvacuationRequest(BaseModel):
    source_target_id: UUID
    affected_service_ids: list[UUID] = Field(max_length=500)
    eligible_service_ids: list[UUID] = Field(max_length=500)
    manual_review_service_ids: list[UUID] = Field(default_factory=list, max_length=500)
    capacity_shortfall: int = Field(default=0, ge=0)
    strategy: str = FleetEvacuationStrategy.MIGRATE_LOW_RISK_FIRST
    max_concurrent_migrations: int = Field(default=5, ge=1, le=50)


class ApprovalRequest(BaseModel):
    actor_id: UUID


class BulkRequest(BaseModel):
    operation_type: str
    target_ids: list[UUID] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=8, max_length=500)


class RunbookRequest(BaseModel):
    runbook_id: UUID
    steps: list[str] = Field(min_length=1, max_length=30)


def _resource_response(resource: FleetResource) -> FleetResourceResponse:
    return FleetResourceResponse(
        resource_id=resource.resource_id,
        resource_type=resource.resource_type,
        safe_label=resource.safe_label,
        provider_kind=resource.provider_kind,
        parent_resource_id=resource.parent_resource_id,
        state=resource.state,
        archived=resource.archived,
        version=resource.version,
    )


@admin_router.get("/hierarchy", response_model=list[FleetResourceResponse])
def hierarchy(
    _: Annotated[object, Depends(require_perm("fleet.read"))],
) -> list[FleetResourceResponse]:
    return [_resource_response(resource) for resource in _RESOURCES.values()]


@admin_router.post(
    "/resources", response_model=FleetResourceResponse, status_code=status.HTTP_201_CREATED
)
def create_resource(
    resource: FleetResourceResponse,
    _: Annotated[object, Depends(require_perm("providers.manage"))],
) -> FleetResourceResponse:
    model = FleetResource(
        resource.resource_id,
        FleetResourceType(resource.resource_type),
        resource.safe_label,
        resource.provider_kind,
        parent_resource_id=resource.parent_resource_id,
        state=FleetOperationalState(resource.state),
        archived=resource.archived,
        version=resource.version,
    )
    _RESOURCES[model.resource_id] = model
    return _resource_response(model)


@admin_router.post("/health/observations", status_code=status.HTTP_202_ACCEPTED)
def ingest_health(
    payload: HealthObservationRequest,
    _: Annotated[object, Depends(require_perm("fleet.manage_health_policies"))],
) -> dict[str, UUID]:
    observation = FleetHealthObservation(
        uuid4(),
        payload.resource_id,
        FleetHealthSignalType(payload.signal_type),
        payload.source,
        datetime.now(UTC),
        timedelta(seconds=payload.freshness_seconds),
        FleetSignalState(payload.state),
        payload.confidence,
        payload.evidence_reference,
    )
    _HEALTH.append(observation)
    return {"observation_id": observation.observation_id}


@admin_router.get("/health/{resource_id}", response_model=HealthEvaluationResponse)
def read_health(
    resource_id: UUID, _: Annotated[object, Depends(require_perm("fleet.read_health"))]
) -> HealthEvaluationResponse:
    policy = FleetHealthPolicyVersion(
        uuid4(),
        1,
        frozenset({item.signal_type for item in _HEALTH if item.resource_id == resource_id}),
        70,
        2,
        2,
        timedelta(minutes=10),
        timedelta(minutes=1),
    )
    if not policy.required_signals:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail={"code": FleetErrorCode.FLEET_HEALTH_UNKNOWN}
        )
    evaluation = evaluate_health(resource_id, policy, tuple(_HEALTH), None, datetime.now(UTC))
    return HealthEvaluationResponse(
        resource_id=resource_id,
        state=evaluation.state,
        confidence=evaluation.confidence,
        stale_signal_count=evaluation.stale_signal_count,
        failing_signal_count=evaluation.failing_signal_count,
        proposal_recommended=evaluation.proposal_recommended,
    )


@admin_router.post("/capacity/snapshots", response_model=CapacitySnapshotResponse)
def create_capacity(
    payload: CapacitySnapshotRequest,
    _: Annotated[object, Depends(require_perm("fleet.manage_capacity_policies"))],
) -> CapacitySnapshotResponse:
    snapshot = FleetCapacitySnapshot(
        uuid4(),
        payload.target_id,
        payload.hard_capacity,
        payload.active_allocations,
        payload.pending_reservations,
        payload.migration_reservations,
        payload.dual_active_consumption,
        payload.safety_reserve,
        payload.maintenance_reserve,
        payload.uncertain_identities,
        payload.stale_inventory_penalty,
        datetime.now(UTC),
        payload.confidence,
    )
    _CAPACITY.append(snapshot)
    return CapacitySnapshotResponse(
        target_id=snapshot.target_id,
        hard_capacity=snapshot.hard_capacity,
        effective_capacity=snapshot.effective_capacity,
        active_allocations=snapshot.active_allocations,
        pending_reservations=snapshot.pending_reservations,
        migration_reservations=snapshot.migration_reservations,
        dual_active_consumption=snapshot.dual_active_consumption,
        safety_reserve=snapshot.safety_reserve,
        uncertain_identities=snapshot.uncertain_identities,
        available_capacity=snapshot.available_capacity,
        utilization_basis_points=snapshot.utilization_basis_points,
        confidence=snapshot.confidence,
    )


@admin_router.get("/capacity/{target_id}/forecast")
def capacity_forecast(
    target_id: UUID, _: Annotated[object, Depends(require_perm("fleet.read_capacity"))]
) -> dict[str, object]:
    forecast = forecast_capacity(target_id, tuple(_CAPACITY), datetime.now(UTC))
    return {
        "target_id": target_id,
        "insufficient_data": forecast.insufficient_data,
        "estimated_exhaustion_at": forecast.estimated_exhaustion_at,
        "current_headroom": forecast.current_headroom,
        "confidence": forecast.confidence,
        "method_version": forecast.method_version,
    }


@admin_router.post("/maintenance/validate")
def validate_maintenance(
    payload: MaintenanceRequest,
    _: Annotated[object, Depends(require_perm("fleet.maintenance.manage"))],
) -> dict[str, object]:
    window = FleetMaintenanceWindow(
        uuid4(),
        payload.title,
        payload.reason,
        tuple(payload.resource_ids),
        payload.planned_start,
        payload.planned_end,
        payload.expected_impact,
    )
    validated = window.validate(tuple(_MAINTENANCE.values()))
    _MAINTENANCE[validated.window_id] = validated
    return {"window_id": validated.window_id, "state": validated.state, "public_message_safe": True}


@admin_router.post("/drains/start")
def start_drain(
    payload: DrainRequest, _: Annotated[object, Depends(require_perm("fleet.drain.manage"))]
) -> dict[str, object]:
    if any(
        drain.target_id == payload.target_id and drain.blocks_allocation()
        for drain in _DRAINS.values()
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail={"code": FleetErrorCode.FLEET_DRAIN_ALREADY_ACTIVE}
        )
    drain = FleetDrainPlan(
        uuid4(),
        payload.target_id,
        FleetDrainState.BLOCK_NEW_ALLOCATIONS,
        payload.active_attachment_count,
    )
    _DRAINS[drain.drain_id] = drain
    return {
        "drain_id": drain.drain_id,
        "state": drain.state,
        "blocks_new_allocations": drain.blocks_allocation(),
    }


@admin_router.post("/evacuations/simulate")
def simulate_evacuation(
    payload: EvacuationRequest, _: Annotated[object, Depends(require_perm("fleet.drain.execute"))]
) -> dict[str, object]:
    plan = FleetEvacuationPlan(
        uuid4(),
        payload.source_target_id,
        tuple(payload.affected_service_ids),
        tuple(payload.eligible_service_ids),
        tuple(payload.manual_review_service_ids),
        payload.capacity_shortfall,
        FleetEvacuationStrategy(payload.strategy),
        payload.max_concurrent_migrations,
        datetime.now(UTC) + timedelta(hours=2),
    )
    _EVACUATIONS[plan.plan_id] = plan
    return {
        "plan_id": plan.plan_id,
        "eligible_count": len(plan.eligible_service_ids),
        "manual_review_count": len(plan.manual_review_service_ids),
        "capacity_shortfall": plan.capacity_shortfall,
        "performs_provider_mutation": False,
    }


@admin_router.post("/failover/proposals")
def create_failover(
    resource_id: UUID,
    actor_id: UUID,
    _: Annotated[object, Depends(require_perm("fleet.failover.manage"))],
) -> dict[str, object]:
    proposal = FleetFailoverProposal(
        uuid4(),
        resource_id,
        tuple(obs.observation_id for obs in _HEALTH if obs.resource_id == resource_id),
        0,
        0,
        "CONTROLLED",
        datetime.now(UTC) + timedelta(hours=1),
        requested_by=actor_id,
    )
    _FAILOVER[proposal.proposal_id] = proposal
    return {"proposal_id": proposal.proposal_id, "executes_automatically": False}


@admin_router.post("/failover/proposals/{proposal_id}/approve")
def approve_failover(
    proposal_id: UUID,
    payload: ApprovalRequest,
    _: Annotated[object, Depends(require_perm("fleet.failover.approve"))],
) -> dict[str, object]:
    proposal = _FAILOVER[proposal_id].approve(payload.actor_id, datetime.now(UTC))
    _FAILOVER[proposal_id] = proposal
    return {
        "proposal_id": proposal_id,
        "approved_by": proposal.approved_by,
        "uses_controlled_migration": True,
    }


@admin_router.post("/recovery/proposals")
def create_recovery(
    resource_id: UUID, _: Annotated[object, Depends(require_perm("fleet.failover.manage"))]
) -> dict[str, object]:
    proposal = FleetRecoveryProposal(
        uuid4(),
        resource_id,
        "VERIFY_CERTIFICATION_BEFORE_REALLOCATION",
        tuple(obs.observation_id for obs in _HEALTH if obs.resource_id == resource_id),
    )
    _RECOVERY[proposal.proposal_id] = proposal
    return {"proposal_id": proposal.proposal_id, "automatic_reverse_migration": False}


@admin_router.post("/bulk-operations/dry-run")
def dry_run_bulk(
    payload: BulkRequest, _: Annotated[object, Depends(require_perm("fleet.bulk.manage"))]
) -> dict[str, object]:
    operation = FleetBulkOperation(
        uuid4(),
        FleetBulkOperationType(payload.operation_type),
        tuple(payload.target_ids),
        payload.reason,
    ).validate()
    _BULK[operation.operation_id] = operation
    return {
        "operation_id": operation.operation_id,
        "state": operation.state,
        "target_count": len(operation.target_ids),
        "eligible_count": len(operation.target_ids),
        "snapshot_frozen": True,
    }


@admin_router.post("/runbooks/publish")
def publish_runbook(
    payload: RunbookRequest, _: Annotated[object, Depends(require_perm("fleet.runbooks.publish"))]
) -> dict[str, object]:
    steps = tuple(
        FleetRunbookStep(
            FleetRunbookStepType(step), step.replace("_", " ").title(), "fleet.runbooks.execute"
        )
        for step in payload.steps
    )
    version = FleetRunbookVersion(uuid4(), payload.runbook_id, 1, steps).publish()
    _RUNBOOKS[version.version_id] = version
    return {
        "version_id": version.version_id,
        "published": version.published,
        "step_count": len(version.steps),
    }


@customer_router.get("/maintenance")
def customer_maintenance() -> dict[str, object]:
    return {
        "items": [
            {
                "state": item.state,
                "planned_start": item.planned_start,
                "planned_end": item.planned_end,
                "expected_impact": item.expected_impact,
            }
            for item in _MAINTENANCE.values()
            if item.state
            in {
                FleetMaintenanceState.SCHEDULED,
                FleetMaintenanceState.ANNOUNCED,
                FleetMaintenanceState.IN_PROGRESS,
            }
        ],
        "internal_identifiers_exposed": False,
    }


@reseller_router.get("/maintenance")
def reseller_maintenance() -> dict[str, object]:
    return {"items": [], "internal_identifiers_exposed": False}
