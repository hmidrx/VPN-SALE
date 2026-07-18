from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class FleetErrorCode(StrEnum):
    FLEET_RESOURCE_NOT_FOUND = "FLEET_RESOURCE_NOT_FOUND"
    FLEET_HEALTH_UNKNOWN = "FLEET_HEALTH_UNKNOWN"
    FLEET_HEALTH_EVIDENCE_STALE = "FLEET_HEALTH_EVIDENCE_STALE"
    FLEET_HEALTH_POLICY_INVALID = "FLEET_HEALTH_POLICY_INVALID"
    FLEET_CAPACITY_UNKNOWN = "FLEET_CAPACITY_UNKNOWN"
    FLEET_CAPACITY_EXHAUSTED = "FLEET_CAPACITY_EXHAUSTED"
    FLEET_CAPACITY_FORECAST_UNAVAILABLE = "FLEET_CAPACITY_FORECAST_UNAVAILABLE"
    FLEET_RESOURCE_DRAINING = "FLEET_RESOURCE_DRAINING"
    FLEET_MAINTENANCE_CONFLICT = "FLEET_MAINTENANCE_CONFLICT"
    FLEET_DRAIN_ALREADY_ACTIVE = "FLEET_DRAIN_ALREADY_ACTIVE"
    FLEET_DRAIN_BLOCKED = "FLEET_DRAIN_BLOCKED"
    FLEET_EVACUATION_PLAN_STALE = "FLEET_EVACUATION_PLAN_STALE"
    FLEET_EVACUATION_CAPACITY_SHORTFALL = "FLEET_EVACUATION_CAPACITY_SHORTFALL"
    FLEET_EVACUATION_PAUSED = "FLEET_EVACUATION_PAUSED"
    FAILOVER_PROPOSAL_NOT_ELIGIBLE = "FAILOVER_PROPOSAL_NOT_ELIGIBLE"
    FAILOVER_PROPOSAL_STALE = "FAILOVER_PROPOSAL_STALE"
    FAILOVER_APPROVAL_REQUIRED = "FAILOVER_APPROVAL_REQUIRED"
    FAILOVER_SELF_APPROVAL_DENIED = "FAILOVER_SELF_APPROVAL_DENIED"
    BULK_OPERATION_TOO_LARGE = "BULK_OPERATION_TOO_LARGE"
    BULK_OPERATION_FILTER_INVALID = "BULK_OPERATION_FILTER_INVALID"
    BULK_OPERATION_APPROVAL_REQUIRED = "BULK_OPERATION_APPROVAL_REQUIRED"
    BULK_OPERATION_PARTIAL_FAILURE = "BULK_OPERATION_PARTIAL_FAILURE"
    RUNBOOK_STEP_UNSUPPORTED = "RUNBOOK_STEP_UNSUPPORTED"
    RUNBOOK_VERSION_STALE = "RUNBOOK_VERSION_STALE"
    RUNBOOK_EXECUTION_PAUSED = "RUNBOOK_EXECUTION_PAUSED"
    PROVIDER_REQUIRES_RECERTIFICATION = "PROVIDER_REQUIRES_RECERTIFICATION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class FleetDomainError(ValueError):
    code: FleetErrorCode
    safe_message: str


class FleetResourceType(StrEnum):
    FLEET = "FLEET"
    PANEL = "PANEL"
    NODE = "NODE"
    INBOUND = "INBOUND"
    ALLOCATION_TARGET = "ALLOCATION_TARGET"
    ALLOCATION_POOL = "ALLOCATION_POOL"


class FleetOperationalState(StrEnum):
    DISCOVERED = "DISCOVERED"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    AT_RISK = "AT_RISK"
    DRAINING = "DRAINING"
    MAINTENANCE_SCHEDULED = "MAINTENANCE_SCHEDULED"
    MAINTENANCE = "MAINTENANCE"
    UNAVAILABLE = "UNAVAILABLE"
    RECOVERING = "RECOVERING"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"
    WRITE_SUSPENDED = "WRITE_SUSPENDED"
    RETIRED = "RETIRED"
    UNKNOWN = "UNKNOWN"


class FleetHealthSignalType(StrEnum):
    PANEL_API_REACHABLE = "PANEL_API_REACHABLE"
    PANEL_AUTHENTICATION_VALID = "PANEL_AUTHENTICATION_VALID"
    PANEL_AUTHORIZATION_SUFFICIENT = "PANEL_AUTHORIZATION_SUFFICIENT"
    TLS_VALID = "TLS_VALID"
    CERTIFICATE_PIN_VALID = "CERTIFICATE_PIN_VALID"
    VERSION_SUPPORTED = "VERSION_SUPPORTED"
    CONTRACT_MATCHED = "CONTRACT_MATCHED"
    READ_CERTIFICATION_VALID = "READ_CERTIFICATION_VALID"
    WRITE_CERTIFICATION_VALID = "WRITE_CERTIFICATION_VALID"
    INVENTORY_SYNC_FRESH = "INVENTORY_SYNC_FRESH"
    USAGE_SYNC_FRESH = "USAGE_SYNC_FRESH"
    PROVIDER_LATENCY = "PROVIDER_LATENCY"
    PROVIDER_ERROR_RATE = "PROVIDER_ERROR_RATE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
    NODE_REPORTED_ONLINE = "NODE_REPORTED_ONLINE"
    INBOUND_REPORTED_ENABLED = "INBOUND_REPORTED_ENABLED"
    INVENTORY_DRIFT = "INVENTORY_DRIFT"
    OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
    CAPACITY_WARNING = "CAPACITY_WARNING"
    CAPACITY_CRITICAL = "CAPACITY_CRITICAL"
    WORKER_BACKLOG = "WORKER_BACKLOG"
    MIGRATION_BACKLOG = "MIGRATION_BACKLOG"
    RECONCILIATION_BACKLOG = "RECONCILIATION_BACKLOG"


class FleetSignalState(StrEnum):
    PASSING = "PASSING"
    WARNING = "WARNING"
    FAILING = "FAILING"
    UNKNOWN = "UNKNOWN"


class FleetMaintenanceState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SCHEDULED = "SCHEDULED"
    ANNOUNCED = "ANNOUNCED"
    PREPARING = "PREPARING"
    DRAINING = "DRAINING"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    EXTENDED = "EXTENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FleetDrainState(StrEnum):
    NOT_DRAINING = "NOT_DRAINING"
    BLOCK_NEW_ALLOCATIONS = "BLOCK_NEW_ALLOCATIONS"
    PLANNING = "PLANNING"
    READY = "READY"
    DRAINING = "DRAINING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FleetEvacuationStrategy(StrEnum):
    MIGRATE_LOW_RISK_FIRST = "MIGRATE_LOW_RISK_FIRST"
    MIGRATE_EXPIRING_LAST = "MIGRATE_EXPIRING_LAST"
    MIGRATE_HIGH_PRIORITY_FIRST = "MIGRATE_HIGH_PRIORITY_FIRST"
    BALANCE_TARGET_HEADROOM = "BALANCE_TARGET_HEADROOM"
    MAINTAIN_LOCATION = "MAINTAIN_LOCATION"
    MAINTAIN_PROVIDER_WHERE_POSSIBLE = "MAINTAIN_PROVIDER_WHERE_POSSIBLE"
    CROSS_PROVIDER_WHEN_REQUIRED = "CROSS_PROVIDER_WHEN_REQUIRED"


class FleetWorkState(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    READY = "READY"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class FleetResource:
    resource_id: UUID
    resource_type: FleetResourceType
    safe_label: str
    provider_kind: str | None = None
    panel_id: UUID | None = None
    parent_resource_id: UUID | None = None
    allocation_target_id: UUID | None = None
    state: FleetOperationalState = FleetOperationalState.DISCOVERED
    archived: bool = False
    version: int = 1


@dataclass(frozen=True)
class FleetHealthObservation:
    observation_id: UUID
    resource_id: UUID
    signal_type: FleetHealthSignalType
    source: str
    observed_at: datetime
    freshness: timedelta
    state: FleetSignalState
    confidence: int
    evidence_reference: str
    sanitized_details: tuple[tuple[str, str], ...] = ()
    provider_adapter_version: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or not 0 <= self.confidence <= 100:
            raise FleetDomainError(FleetErrorCode.FLEET_HEALTH_POLICY_INVALID, "invalid evidence")
        blocked = ("token", "secret", "password", "cookie", "http://", "https://")
        text = f"{self.evidence_reference} {self.sanitized_details}".lower()
        if any(marker in text for marker in blocked):
            raise FleetDomainError(FleetErrorCode.FLEET_HEALTH_POLICY_INVALID, "unsafe evidence")

    def is_fresh(self, now: datetime) -> bool:
        return now.tzinfo is not None and self.observed_at + self.freshness >= now


@dataclass(frozen=True)
class FleetHealthPolicyVersion:
    version_id: UUID
    version_number: int
    required_signals: frozenset[FleetHealthSignalType]
    minimum_confidence: int
    consecutive_failure_count: int
    consecutive_recovery_count: int
    freshness: timedelta
    evaluation_interval: timedelta


@dataclass(frozen=True)
class FleetHealthEvaluation:
    evaluation_id: UUID
    resource_id: UUID
    policy_version_id: UUID
    evaluated_at: datetime
    state: FleetOperationalState
    confidence: int
    stale_signal_count: int
    failing_signal_count: int
    consecutive_failures: int
    consecutive_recoveries: int
    proposal_recommended: bool = False


def evaluate_health(
    resource_id: UUID,
    policy: FleetHealthPolicyVersion,
    observations: tuple[FleetHealthObservation, ...],
    previous: FleetHealthEvaluation | None,
    now: datetime,
) -> FleetHealthEvaluation:
    latest: dict[FleetHealthSignalType, FleetHealthObservation] = {}
    for observation in observations:
        if observation.resource_id == resource_id:
            current = latest.get(observation.signal_type)
            if current is None or observation.observed_at > current.observed_at:
                latest[observation.signal_type] = observation
    stale = 0
    failing = 0
    confidences: list[int] = []
    for signal in policy.required_signals:
        observation = latest.get(signal)
        if observation is None or not observation.is_fresh(now):
            stale += 1
            continue
        confidences.append(observation.confidence)
        if (
            observation.confidence < policy.minimum_confidence
            or observation.state == FleetSignalState.FAILING
        ):
            failing += 1
        if (
            signal
            in {FleetHealthSignalType.CONTRACT_MATCHED, FleetHealthSignalType.VERSION_SUPPORTED}
            and observation.state == FleetSignalState.FAILING
        ):
            return FleetHealthEvaluation(
                uuid4(),
                resource_id,
                policy.version_id,
                now,
                FleetOperationalState.RECERTIFICATION_REQUIRED,
                observation.confidence,
                stale,
                failing + 1,
                policy.consecutive_failure_count,
                0,
                True,
            )
        if (
            signal == FleetHealthSignalType.WRITE_CERTIFICATION_VALID
            and observation.state == FleetSignalState.FAILING
        ):
            return FleetHealthEvaluation(
                uuid4(),
                resource_id,
                policy.version_id,
                now,
                FleetOperationalState.WRITE_SUSPENDED,
                observation.confidence,
                stale,
                failing + 1,
                policy.consecutive_failure_count,
                0,
                True,
            )
    confidence = min(confidences) if confidences else 0
    if stale:
        return FleetHealthEvaluation(
            uuid4(),
            resource_id,
            policy.version_id,
            now,
            FleetOperationalState.UNKNOWN,
            confidence,
            stale,
            failing,
            0,
            0,
        )
    prior_failures = previous.consecutive_failures if previous else 0
    prior_recoveries = previous.consecutive_recoveries if previous else 0
    if failing:
        failures = prior_failures + 1
        state = (
            FleetOperationalState.UNAVAILABLE
            if failures >= policy.consecutive_failure_count
            else FleetOperationalState.DEGRADED
        )
        return FleetHealthEvaluation(
            uuid4(),
            resource_id,
            policy.version_id,
            now,
            state,
            confidence,
            0,
            failing,
            failures,
            0,
            state == FleetOperationalState.UNAVAILABLE,
        )
    recoveries = prior_recoveries + 1
    if (
        previous
        and previous.state in {FleetOperationalState.DEGRADED, FleetOperationalState.UNAVAILABLE}
        and recoveries < policy.consecutive_recovery_count
    ):
        return replace(
            previous,
            evaluation_id=uuid4(),
            evaluated_at=now,
            consecutive_recoveries=recoveries,
            confidence=confidence,
        )
    return FleetHealthEvaluation(
        uuid4(),
        resource_id,
        policy.version_id,
        now,
        FleetOperationalState.ACTIVE,
        confidence,
        0,
        0,
        0,
        recoveries,
    )


@dataclass(frozen=True)
class FleetCapacitySnapshot:
    snapshot_id: UUID
    target_id: UUID
    hard_capacity: int
    active_allocations: int
    pending_reservations: int
    migration_reservations: int
    dual_active_consumption: int
    safety_reserve: int
    maintenance_reserve: int
    uncertain_identities: int
    stale_inventory_penalty: int
    observed_at: datetime
    confidence: int

    def __post_init__(self) -> None:
        values = (
            self.hard_capacity,
            self.active_allocations,
            self.pending_reservations,
            self.migration_reservations,
            self.dual_active_consumption,
            self.safety_reserve,
            self.maintenance_reserve,
            self.uncertain_identities,
            self.stale_inventory_penalty,
        )
        if any(value < 0 for value in values):
            raise FleetDomainError(FleetErrorCode.FLEET_CAPACITY_UNKNOWN, "negative capacity")

    @property
    def effective_capacity(self) -> int:
        return max(
            0,
            self.hard_capacity
            - self.safety_reserve
            - self.maintenance_reserve
            - self.stale_inventory_penalty,
        )

    @property
    def consumed_capacity(self) -> int:
        return (
            self.active_allocations
            + self.pending_reservations
            + self.migration_reservations
            + self.dual_active_consumption
            + self.uncertain_identities
        )

    @property
    def available_capacity(self) -> int:
        return max(0, self.effective_capacity - self.consumed_capacity)

    @property
    def utilization_basis_points(self) -> int:
        if self.effective_capacity == 0:
            return 10_000
        return min(10_000, self.consumed_capacity * 10_000 // self.effective_capacity)


@dataclass(frozen=True)
class FleetCapacityForecast:
    forecast_id: UUID
    target_id: UUID
    generated_at: datetime
    method_version: str
    horizon_days: int
    current_headroom: int
    observed_net_growth_per_day: int | None
    estimated_exhaustion_at: datetime | None
    confidence: int
    insufficient_data: bool
    assumptions: tuple[str, ...]


def forecast_capacity(
    target_id: UUID,
    history: tuple[FleetCapacitySnapshot, ...],
    now: datetime,
    horizon_days: int = 30,
) -> FleetCapacityForecast:
    ordered = sorted(
        (item for item in history if item.target_id == target_id), key=lambda item: item.observed_at
    )
    if len(ordered) < 3:
        headroom = ordered[-1].available_capacity if ordered else 0
        return FleetCapacityForecast(
            uuid4(),
            target_id,
            now,
            "rolling-average-v1",
            horizon_days,
            headroom,
            None,
            None,
            0,
            True,
            ("insufficient historical capacity snapshots",),
        )
    deltas = [
        max(0, ordered[index].consumed_capacity - ordered[index - 1].consumed_capacity)
        for index in range(1, len(ordered))
    ]
    growth = sum(deltas) // len(deltas)
    headroom = ordered[-1].available_capacity
    exhaustion = None if growth <= 0 else now + timedelta(days=(headroom + growth - 1) // growth)
    return FleetCapacityForecast(
        uuid4(),
        target_id,
        now,
        "rolling-average-v1",
        horizon_days,
        headroom,
        growth,
        exhaustion if exhaustion and exhaustion <= now + timedelta(days=horizon_days) else None,
        80,
        False,
        ("uses non-negative rolling average allocation growth",),
    )


@dataclass(frozen=True)
class FleetMaintenanceWindow:
    window_id: UUID
    title: str
    reason: str
    resource_ids: tuple[UUID, ...]
    planned_start: datetime
    planned_end: datetime
    expected_impact: str
    state: FleetMaintenanceState = FleetMaintenanceState.DRAFT
    optimistic_version: int = 1

    def validate(self, existing: tuple[FleetMaintenanceWindow, ...]) -> FleetMaintenanceWindow:
        if (
            self.planned_start.tzinfo is None
            or self.planned_end.tzinfo is None
            or self.planned_start >= self.planned_end
        ):
            raise FleetDomainError(FleetErrorCode.FLEET_MAINTENANCE_CONFLICT, "invalid window")
        for window in existing:
            if (
                window.state
                not in {
                    FleetMaintenanceState.CANCELLED,
                    FleetMaintenanceState.COMPLETED,
                    FleetMaintenanceState.FAILED,
                }
                and set(window.resource_ids) & set(self.resource_ids)
                and self.planned_start < window.planned_end
                and window.planned_start < self.planned_end
            ):
                raise FleetDomainError(
                    FleetErrorCode.FLEET_MAINTENANCE_CONFLICT, "overlapping maintenance"
                )
        return replace(
            self,
            state=FleetMaintenanceState.VALIDATED,
            optimistic_version=self.optimistic_version + 1,
        )


@dataclass(frozen=True)
class FleetDrainPlan:
    drain_id: UUID
    target_id: UUID
    state: FleetDrainState
    active_attachment_count: int
    approved_exception_count: int = 0

    def blocks_allocation(self) -> bool:
        return self.state in {
            FleetDrainState.BLOCK_NEW_ALLOCATIONS,
            FleetDrainState.PLANNING,
            FleetDrainState.READY,
            FleetDrainState.DRAINING,
            FleetDrainState.PAUSED,
        }

    def assert_can_allocate(self) -> None:
        if self.blocks_allocation():
            raise FleetDomainError(FleetErrorCode.FLEET_RESOURCE_DRAINING, "target is draining")

    def complete(self) -> FleetDrainPlan:
        if self.active_attachment_count > self.approved_exception_count:
            raise FleetDomainError(FleetErrorCode.FLEET_DRAIN_BLOCKED, "active attachments remain")
        return replace(self, state=FleetDrainState.COMPLETED)


@dataclass(frozen=True)
class FleetEvacuationPlan:
    plan_id: UUID
    source_target_id: UUID
    affected_service_ids: tuple[UUID, ...]
    eligible_service_ids: tuple[UUID, ...]
    manual_review_service_ids: tuple[UUID, ...]
    capacity_shortfall: int
    strategy: FleetEvacuationStrategy
    max_concurrent_migrations: int
    expires_at: datetime
    approved_by: UUID | None = None

    def assert_current(self, now: datetime) -> None:
        if now > self.expires_at:
            raise FleetDomainError(FleetErrorCode.FLEET_EVACUATION_PLAN_STALE, "plan expired")
        if self.capacity_shortfall > 0:
            raise FleetDomainError(
                FleetErrorCode.FLEET_EVACUATION_CAPACITY_SHORTFALL, "capacity shortfall"
            )


@dataclass(frozen=True)
class FleetEvacuationBatch:
    batch_id: UUID
    plan_id: UUID
    service_ids: tuple[UUID, ...]
    state: FleetWorkState = FleetWorkState.QUEUED
    failed_count: int = 0
    uncertain_count: int = 0

    def with_guardrails(self, max_failures: int) -> FleetEvacuationBatch:
        if self.failed_count > max_failures or self.uncertain_count > 0:
            return replace(self, state=FleetWorkState.PAUSED)
        return self


@dataclass(frozen=True)
class FleetFailoverProposal:
    proposal_id: UUID
    resource_id: UUID
    triggering_evidence: tuple[UUID, ...]
    impacted_service_count: int
    eligible_service_count: int
    risk_classification: str
    expires_at: datetime
    approved_by: UUID | None = None
    requested_by: UUID | None = None

    def approve(self, approver_id: UUID, now: datetime) -> FleetFailoverProposal:
        if now > self.expires_at:
            raise FleetDomainError(FleetErrorCode.FAILOVER_PROPOSAL_STALE, "proposal expired")
        if self.requested_by == approver_id:
            raise FleetDomainError(
                FleetErrorCode.FAILOVER_SELF_APPROVAL_DENIED, "self approval denied"
            )
        return replace(self, approved_by=approver_id)


@dataclass(frozen=True)
class FleetRecoveryProposal:
    proposal_id: UUID
    resource_id: UUID
    recommendation: str
    evidence_ids: tuple[UUID, ...]
    state: FleetWorkState = FleetWorkState.PENDING_APPROVAL


class FleetBulkOperationType(StrEnum):
    REQUEST_PROVIDER_INVENTORY_SYNC = "REQUEST_PROVIDER_INVENTORY_SYNC"
    REQUEST_USAGE_SYNC = "REQUEST_USAGE_SYNC"
    REQUEST_SERVICE_RECONCILIATION = "REQUEST_SERVICE_RECONCILIATION"
    REQUEST_MIGRATION_ELIGIBILITY_SIMULATION = "REQUEST_MIGRATION_ELIGIBILITY_SIMULATION"
    SUSPEND_SELECTED_SERVICES = "SUSPEND_SELECTED_SERVICES"
    RESUME_SELECTED_SERVICES = "RESUME_SELECTED_SERVICES"
    ROTATE_SUBSCRIPTION_TOKENS = "ROTATE_SUBSCRIPTION_TOKENS"
    SEND_MAINTENANCE_NOTIFICATION = "SEND_MAINTENANCE_NOTIFICATION"
    MARK_OPERATIONAL_ISSUES_FOR_REVIEW = "MARK_OPERATIONAL_ISSUES_FOR_REVIEW"


@dataclass(frozen=True)
class FleetBulkOperation:
    operation_id: UUID
    operation_type: FleetBulkOperationType
    target_ids: tuple[UUID, ...]
    reason: str
    state: FleetWorkState = FleetWorkState.DRAFT
    max_target_count: int = 500

    def validate(self) -> FleetBulkOperation:
        if not self.target_ids or len(set(self.target_ids)) != len(self.target_ids):
            raise FleetDomainError(
                FleetErrorCode.BULK_OPERATION_FILTER_INVALID, "invalid target snapshot"
            )
        if len(self.target_ids) > self.max_target_count:
            raise FleetDomainError(
                FleetErrorCode.BULK_OPERATION_TOO_LARGE, "bulk operation too large"
            )
        return replace(self, state=FleetWorkState.READY)


@dataclass(frozen=True)
class FleetBulkOperationItem:
    item_id: UUID
    operation_id: UUID
    target_id: UUID
    state: FleetWorkState = FleetWorkState.QUEUED
    idempotency_key: str = field(default_factory=lambda: uuid4().hex)

    def retry(self) -> FleetBulkOperationItem:
        if self.state == FleetWorkState.COMPLETED:
            return self
        return replace(self, state=FleetWorkState.QUEUED)


class FleetRunbookStepType(StrEnum):
    INSPECT_HEALTH_EVIDENCE = "INSPECT_HEALTH_EVIDENCE"
    RUN_PROVIDER_SYNC = "RUN_PROVIDER_SYNC"
    RUN_USAGE_SYNC = "RUN_USAGE_SYNC"
    RUN_RECONCILIATION = "RUN_RECONCILIATION"
    BLOCK_ALLOCATIONS = "BLOCK_ALLOCATIONS"
    CREATE_DRAIN_PLAN = "CREATE_DRAIN_PLAN"
    SIMULATE_EVACUATION = "SIMULATE_EVACUATION"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    START_BOUNDED_MIGRATION_BATCH = "START_BOUNDED_MIGRATION_BATCH"
    VERIFY_SOURCE_CLEANUP = "VERIFY_SOURCE_CLEANUP"
    UPDATE_INCIDENT = "UPDATE_INCIDENT"
    NOTIFY_AFFECTED_USERS = "NOTIFY_AFFECTED_USERS"
    CLOSE_MAINTENANCE = "CLOSE_MAINTENANCE"
    CREATE_MANUAL_REVIEW_TASK = "CREATE_MANUAL_REVIEW_TASK"
    MANUAL_CONFIRMATION = "MANUAL_CONFIRMATION"


@dataclass(frozen=True)
class FleetRunbookStep:
    step_type: FleetRunbookStepType
    title: str
    permission: str


@dataclass(frozen=True)
class FleetRunbookVersion:
    version_id: UUID
    runbook_id: UUID
    version_number: int
    steps: tuple[FleetRunbookStep, ...]
    published: bool = False
    max_step_count: int = 30

    def validate(self) -> FleetRunbookVersion:
        if not self.steps or len(self.steps) > self.max_step_count:
            raise FleetDomainError(FleetErrorCode.RUNBOOK_STEP_UNSUPPORTED, "invalid step count")
        return self

    def publish(self) -> FleetRunbookVersion:
        self.validate()
        return replace(self, published=True)


@dataclass(frozen=True)
class FleetRunbookExecution:
    execution_id: UUID
    version_id: UUID
    state: FleetWorkState = FleetWorkState.QUEUED
    current_step_index: int = 0


@dataclass(frozen=True)
class FleetManualReview:
    review_id: UUID
    resource_id: UUID | None
    reason_code: str
    state: FleetWorkState = FleetWorkState.MANUAL_REVIEW
