from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from vpnsale_domain.providers import ProviderKind


class UsageErrorCode(StrEnum):
    USAGE_NOT_AVAILABLE = "USAGE_NOT_AVAILABLE"
    USAGE_OBSERVATION_STALE = "USAGE_OBSERVATION_STALE"
    USAGE_COUNTER_INVALID = "USAGE_COUNTER_INVALID"
    USAGE_COUNTER_DECREASE_UNEXPLAINED = "USAGE_COUNTER_DECREASE_UNEXPLAINED"
    USAGE_COUNTER_GENERATION_CONFLICT = "USAGE_COUNTER_GENERATION_CONFLICT"
    USAGE_AGGREGATION_UNCERTAIN = "USAGE_AGGREGATION_UNCERTAIN"
    USAGE_POLICY_NOT_FOUND = "USAGE_POLICY_NOT_FOUND"
    USAGE_POLICY_INVALID = "USAGE_POLICY_INVALID"
    USAGE_ALLOWANCE_UNKNOWN = "USAGE_ALLOWANCE_UNKNOWN"
    USAGE_CORRECTION_APPROVAL_REQUIRED = "USAGE_CORRECTION_APPROVAL_REQUIRED"
    USAGE_SELF_APPROVAL_DENIED = "USAGE_SELF_APPROVAL_DENIED"
    FIRST_USE_STATE_UNCERTAIN = "FIRST_USE_STATE_UNCERTAIN"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    QUOTA_ENFORCEMENT_PENDING = "QUOTA_ENFORCEMENT_PENDING"
    QUOTA_ENFORCEMENT_FAILED = "QUOTA_ENFORCEMENT_FAILED"
    SERVICE_EXPIRY_PENDING = "SERVICE_EXPIRY_PENDING"
    SERVICE_EXPIRY_ENFORCEMENT_FAILED = "SERVICE_EXPIRY_ENFORCEMENT_FAILED"
    SERVICE_RESTORATION_BLOCKED = "SERVICE_RESTORATION_BLOCKED"
    LIFECYCLE_AUTOMATION_CONFLICT = "LIFECYCLE_AUTOMATION_CONFLICT"
    PROVIDER_USAGE_RATE_LIMITED = "PROVIDER_USAGE_RATE_LIMITED"
    PROVIDER_USAGE_CONTRACT_MISMATCH = "PROVIDER_USAGE_CONTRACT_MISMATCH"
    PROVIDER_REQUIRES_RECERTIFICATION = "PROVIDER_REQUIRES_RECERTIFICATION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class UsageDomainError(ValueError):
    code: UsageErrorCode
    safe_message: str


class CounterScope(StrEnum):
    USER = "USER"
    CLIENT = "CLIENT"
    INBOUND_CLIENT = "INBOUND_CLIENT"
    NODE_CLIENT = "NODE_CLIENT"
    PANEL_USER = "PANEL_USER"


class ObservationConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNUSABLE = "UNUSABLE"


class CounterAnomalyType(StrEnum):
    COUNTER_DECREASE_UNEXPLAINED = "COUNTER_DECREASE_UNEXPLAINED"
    COUNTER_RESET_CONFIRMED = "COUNTER_RESET_CONFIRMED"
    COUNTER_WRAP_SUSPECTED = "COUNTER_WRAP_SUSPECTED"
    REMOTE_IDENTITY_RECREATED = "REMOTE_IDENTITY_RECREATED"
    COUNTER_SOURCE_CHANGED = "COUNTER_SOURCE_CHANGED"
    COUNTER_JUMP_SUSPECTED = "COUNTER_JUMP_SUSPECTED"
    COUNTER_UNAVAILABLE = "COUNTER_UNAVAILABLE"
    COUNTER_STALE = "COUNTER_STALE"
    COUNTER_DUPLICATE_SOURCE = "COUNTER_DUPLICATE_SOURCE"
    COUNTER_CONTRACT_CHANGED = "COUNTER_CONTRACT_CHANGED"


class AggregationStrategy(StrEnum):
    SINGLE_ATTACHMENT = "SINGLE_ATTACHMENT"
    SUM_INDEPENDENT_IDENTITIES = "SUM_INDEPENDENT_IDENTITIES"
    MAX_MIRRORED_IDENTITIES = "MAX_MIRRORED_IDENTITIES"
    PRIMARY_ATTACHMENT_ONLY = "PRIMARY_ATTACHMENT_ONLY"
    SHARED_IDENTITY_DEDUPLICATED = "SHARED_IDENTITY_DEDUPLICATED"
    PROVIDER_CANONICAL_USER_COUNTER = "PROVIDER_CANONICAL_USER_COUNTER"
    MIGRATION_OVERLAP_DEDUPLICATED = "MIGRATION_OVERLAP_DEDUPLICATED"


class UsageCycleKind(StrEnum):
    SERVICE_LIFETIME = "SERVICE_LIFETIME"
    PURCHASE_PERIOD = "PURCHASE_PERIOD"
    RENEWAL_PERIOD = "RENEWAL_PERIOD"
    MANUAL_RESET_PERIOD = "MANUAL_RESET_PERIOD"
    PROVIDER_PERIODIC_LIMIT = "PROVIDER_PERIODIC_LIMIT"


class QuotaState(StrEnum):
    UNKNOWN = "UNKNOWN"
    AVAILABLE = "AVAILABLE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EXHAUSTED_PENDING_CONFIRMATION = "EXHAUSTED_PENDING_CONFIRMATION"
    EXHAUSTED_CONFIRMED = "EXHAUSTED_CONFIRMED"
    ENFORCEMENT_PENDING = "ENFORCEMENT_PENDING"
    ENFORCED = "ENFORCED"
    ENFORCEMENT_FAILED = "ENFORCEMENT_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ExpiryState(StrEnum):
    NO_EXPIRY = "NO_EXPIRY"
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    EXPIRED_PENDING_CONFIRMATION = "EXPIRED_PENDING_CONFIRMATION"
    EXPIRED_CONFIRMED = "EXPIRED_CONFIRMED"
    GRACE_PERIOD = "GRACE_PERIOD"
    ENFORCEMENT_PENDING = "ENFORCEMENT_PENDING"
    ENFORCED = "ENFORCED"
    ENFORCEMENT_FAILED = "ENFORCEMENT_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class RestrictionReason(StrEnum):
    TRAFFIC_EXHAUSTED = "TRAFFIC_EXHAUSTED"
    EXPIRED = "EXPIRED"
    ADMIN_SUSPENDED = "ADMIN_SUSPENDED"
    CUSTOMER_SUSPENDED = "CUSTOMER_SUSPENDED"
    SECURITY_HOLD = "SECURITY_HOLD"
    PAYMENT_REVIEW = "PAYMENT_REVIEW"
    PROVIDER_UNCERTAIN = "PROVIDER_UNCERTAIN"
    MIGRATION_IN_PROGRESS = "MIGRATION_IN_PROGRESS"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FirstUseState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    START_DETECTED = "START_DETECTED"
    START_CONFIRMED = "START_CONFIRMED"
    EXPIRY_CALCULATED = "EXPIRY_CALCULATED"
    REMOTE_EXPIRY_APPLIED = "REMOTE_EXPIRY_APPLIED"
    ACTIVE = "ACTIVE"
    ANOMALOUS = "ANOMALOUS"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class ProviderCounterSemantics:
    provider_kind: ProviderKind
    contract_code: str
    counter_scope: CounterScope
    combined_counter_field: str
    upload_field: str | None
    download_field: str | None
    disabled_users_report_counters: bool
    supports_first_use_expiry: bool
    online_state_trustworthy_for_first_use: bool
    reset_starts_new_generation: bool = True
    unit: str = "bytes"


CERTIFIED_COUNTER_SEMANTICS: Mapping[ProviderKind, ProviderCounterSemantics] = {
    ProviderKind.SANAEI_3X_UI: ProviderCounterSemantics(
        ProviderKind.SANAEI_3X_UI,
        "sanaei-3x-ui-v3.7.0-global-client-used-traffic-v1",
        CounterScope.CLIENT,
        "usedTraffic",
        None,
        None,
        True,
        False,
        False,
    ),
    ProviderKind.ALIREZA_X_UI: ProviderCounterSemantics(
        ProviderKind.ALIREZA_X_UI,
        "alireza-x-ui-read-v1",
        CounterScope.CLIENT,
        "total",
        None,
        None,
        True,
        False,
        False,
    ),
    ProviderKind.PASARGUARD: ProviderCounterSemantics(
        ProviderKind.PASARGUARD,
        "pasarguard-read-v1",
        CounterScope.PANEL_USER,
        "traffic_bytes",
        None,
        None,
        False,
        True,
        True,
    ),
}


def require_non_negative_bytes(value: int | None, field_name: str) -> None:
    if value is None:
        return
    if type(value) is not int or value < 0:
        raise UsageDomainError(
            UsageErrorCode.USAGE_COUNTER_INVALID, f"{field_name} must be non-negative integer bytes"
        )


@dataclass(frozen=True)
class UsageAllowance:
    finite_bytes: int | None
    unlimited: bool = False
    source: str = "entitlement"

    def __post_init__(self) -> None:
        if self.unlimited and self.finite_bytes is not None:
            raise UsageDomainError(
                UsageErrorCode.USAGE_POLICY_INVALID, "unlimited allowance cannot also be finite"
            )
        require_non_negative_bytes(self.finite_bytes, "finite_bytes")


@dataclass(frozen=True)
class UsageCounterGeneration:
    generation_id: UUID
    attachment_id: UUID
    counter_scope_key: str
    generation_number: int
    started_at: datetime
    start_reason: str


@dataclass(frozen=True)
class UsageObservation:
    observation_id: UUID
    service_id: UUID
    attachment_id: UUID
    provider_kind: ProviderKind
    contract_code: str
    observed_at: datetime
    counter_scope_key: str
    combined_bytes: int | None
    upload_bytes: int | None = None
    download_bytes: int | None = None
    remote_limit_bytes: int | None = None
    remote_expiry_at: datetime | None = None
    remote_enabled: bool | None = None
    online: bool | None = None
    generation_number: int = 1
    confidence: ObservationConfidence = ObservationConfidence.HIGH
    mirrored_group: str | None = None
    primary: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise UsageDomainError(
                UsageErrorCode.USAGE_COUNTER_INVALID, "observed_at must be UTC-aware"
            )
        for name in ("combined_bytes", "upload_bytes", "download_bytes", "remote_limit_bytes"):
            require_non_negative_bytes(getattr(self, name), name)


@dataclass(frozen=True)
class UsageDelta:
    delta_id: UUID
    service_id: UUID
    attachment_id: UUID
    generation_number: int
    delta_bytes: int
    source_observation_id: UUID
    reason: str

    def __post_init__(self) -> None:
        require_non_negative_bytes(self.delta_bytes, "delta_bytes")


@dataclass(frozen=True)
class CounterCheckpoint:
    attachment_id: UUID
    counter_scope_key: str
    generation_number: int
    last_counter_bytes: int
    lifetime_bytes: int
    last_observation_id: UUID


@dataclass(frozen=True)
class CounterClassification:
    delta: UsageDelta | None
    checkpoint: CounterCheckpoint
    anomaly: CounterAnomalyType | None
    starts_new_generation: bool = False


def classify_counter_observation(
    previous: CounterCheckpoint | None,
    observation: UsageObservation,
    *,
    reset_operation_confirmed: bool = False,
    remote_identity_recreated: bool = False,
    wrap_threshold_bytes: int = 2**32,
    jump_threshold_bytes: int = 10 * 1024**4,
) -> CounterClassification:
    if observation.combined_bytes is None:
        checkpoint = previous or CounterCheckpoint(
            observation.attachment_id,
            observation.counter_scope_key,
            observation.generation_number,
            0,
            0,
            observation.observation_id,
        )
        return CounterClassification(None, checkpoint, CounterAnomalyType.COUNTER_UNAVAILABLE)
    if previous is None or reset_operation_confirmed or remote_identity_recreated:
        generation = observation.generation_number + (
            1 if reset_operation_confirmed or remote_identity_recreated else 0
        )
        checkpoint = CounterCheckpoint(
            observation.attachment_id,
            observation.counter_scope_key,
            generation,
            observation.combined_bytes,
            previous.lifetime_bytes if previous is not None else 0,
            observation.observation_id,
        )
        anomaly = (
            CounterAnomalyType.COUNTER_RESET_CONFIRMED
            if reset_operation_confirmed
            else CounterAnomalyType.REMOTE_IDENTITY_RECREATED
            if remote_identity_recreated
            else None
        )
        return CounterClassification(
            None, checkpoint, anomaly, reset_operation_confirmed or remote_identity_recreated
        )
    if observation.counter_scope_key != previous.counter_scope_key:
        checkpoint = CounterCheckpoint(
            observation.attachment_id,
            observation.counter_scope_key,
            previous.generation_number + 1,
            observation.combined_bytes,
            previous.lifetime_bytes,
            observation.observation_id,
        )
        return CounterClassification(
            None, checkpoint, CounterAnomalyType.COUNTER_SOURCE_CHANGED, True
        )
    current = observation.combined_bytes
    last = previous.last_counter_bytes
    if current == last:
        return CounterClassification(
            None, replace(previous, last_observation_id=observation.observation_id), None
        )
    if current > last:
        amount = current - last
        anomaly = (
            CounterAnomalyType.COUNTER_JUMP_SUSPECTED if amount > jump_threshold_bytes else None
        )
        delta = UsageDelta(
            uuid4(),
            observation.service_id,
            observation.attachment_id,
            previous.generation_number,
            amount,
            observation.observation_id,
            "PROVIDER_POSITIVE_DELTA",
        )
        checkpoint = CounterCheckpoint(
            observation.attachment_id,
            previous.counter_scope_key,
            previous.generation_number,
            current,
            previous.lifetime_bytes + amount,
            observation.observation_id,
        )
        return CounterClassification(delta, checkpoint, anomaly)
    anomaly = (
        CounterAnomalyType.COUNTER_WRAP_SUSPECTED
        if last >= wrap_threshold_bytes and current < last
        else CounterAnomalyType.COUNTER_DECREASE_UNEXPLAINED
    )
    return CounterClassification(
        None, replace(previous, last_observation_id=observation.observation_id), anomaly
    )


@dataclass(frozen=True)
class AggregationPolicyVersion:
    policy_id: UUID
    version: int
    strategy: AggregationStrategy
    max_staleness: timedelta = timedelta(hours=2)
    published: bool = True


@dataclass(frozen=True)
class UsageAggregate:
    service_id: UUID
    used_bytes: int | None
    confidence: ObservationConfidence
    latest_observed_at: datetime | None
    strategy: AggregationStrategy
    explanation_code: str
    anomaly_types: tuple[CounterAnomalyType, ...] = ()


def aggregate_usage(
    observations: Sequence[UsageObservation],
    policy: AggregationPolicyVersion,
    now: datetime,
) -> UsageAggregate:
    if not observations:
        return UsageAggregate(
            uuid4(),
            None,
            ObservationConfidence.UNUSABLE,
            None,
            policy.strategy,
            "NO_OBSERVATIONS",
            (CounterAnomalyType.COUNTER_UNAVAILABLE,),
        )
    service_id = observations[0].service_id
    fresh = [
        o
        for o in observations
        if now - o.observed_at <= policy.max_staleness
        and o.confidence != ObservationConfidence.UNUSABLE
    ]
    if not fresh:
        return UsageAggregate(
            service_id,
            None,
            ObservationConfidence.LOW,
            max(o.observed_at for o in observations),
            policy.strategy,
            "STALE_OBSERVATIONS",
            (CounterAnomalyType.COUNTER_STALE,),
        )
    counters = [o.combined_bytes for o in fresh]
    if any(v is None for v in counters):
        return UsageAggregate(
            service_id,
            None,
            ObservationConfidence.LOW,
            max(o.observed_at for o in fresh),
            policy.strategy,
            "PARTIAL_UNKNOWN_COUNTER",
        )
    values = [v for v in counters if v is not None]
    if policy.strategy in {
        AggregationStrategy.SINGLE_ATTACHMENT,
        AggregationStrategy.PRIMARY_ATTACHMENT_ONLY,
    }:
        selected = next((o for o in fresh if o.primary), fresh[0])
        return UsageAggregate(
            service_id,
            selected.combined_bytes,
            selected.confidence,
            selected.observed_at,
            policy.strategy,
            "PRIMARY_COUNTER",
        )
    if policy.strategy in {
        AggregationStrategy.SHARED_IDENTITY_DEDUPLICATED,
        AggregationStrategy.PROVIDER_CANONICAL_USER_COUNTER,
    }:
        by_scope: dict[str, list[int]] = defaultdict(list)
        for obs in fresh:
            if obs.combined_bytes is not None:
                by_scope[obs.counter_scope_key].append(obs.combined_bytes)
        if any(len(set(v)) > 1 for v in by_scope.values()):
            return UsageAggregate(
                service_id,
                max(max(v) for v in by_scope.values()),
                ObservationConfidence.MEDIUM,
                max(o.observed_at for o in fresh),
                policy.strategy,
                "SHARED_COUNTER_DRIFT",
                (CounterAnomalyType.COUNTER_DUPLICATE_SOURCE,),
            )
        return UsageAggregate(
            service_id,
            sum(v[0] for v in by_scope.values()),
            ObservationConfidence.HIGH,
            max(o.observed_at for o in fresh),
            policy.strategy,
            "SHARED_SCOPE_DEDUPLICATED",
        )
    if policy.strategy in {
        AggregationStrategy.MAX_MIRRORED_IDENTITIES,
        AggregationStrategy.MIGRATION_OVERLAP_DEDUPLICATED,
    }:
        by_group: dict[str, list[int]] = defaultdict(list)
        for obs in fresh:
            if obs.combined_bytes is not None:
                by_group[obs.mirrored_group or obs.counter_scope_key].append(obs.combined_bytes)
        return UsageAggregate(
            service_id,
            sum(max(v) for v in by_group.values()),
            ObservationConfidence.MEDIUM,
            max(o.observed_at for o in fresh),
            policy.strategy,
            "MIRRORED_MAX_DEDUPLICATED",
        )
    return UsageAggregate(
        service_id,
        sum(values),
        ObservationConfidence.HIGH,
        max(o.observed_at for o in fresh),
        policy.strategy,
        "INDEPENDENT_SUM",
    )


@dataclass(frozen=True)
class UsageRemaining:
    allowance: UsageAllowance
    used_bytes: int | None
    remaining_bytes: int | None
    overage_bytes: int
    consumed_percent: int | None


def calculate_remaining(allowance: UsageAllowance, used_bytes: int | None) -> UsageRemaining:
    if allowance.unlimited:
        return UsageRemaining(allowance, used_bytes, None, 0, None)
    if allowance.finite_bytes is None or used_bytes is None:
        return UsageRemaining(allowance, used_bytes, None, 0, None)
    remaining = max(allowance.finite_bytes - used_bytes, 0)
    overage = max(used_bytes - allowance.finite_bytes, 0)
    percent = (used_bytes * 100) // allowance.finite_bytes if allowance.finite_bytes > 0 else 100
    return UsageRemaining(allowance, used_bytes, remaining, overage, percent)


@dataclass(frozen=True)
class ThresholdPolicy:
    policy_id: UUID
    version: int
    warning_percent: int = 80
    critical_percent: int = 95
    expiry_warning: timedelta = timedelta(days=7)
    expiry_critical: timedelta = timedelta(days=1)


@dataclass(frozen=True)
class ThresholdEvent:
    service_id: UUID
    cycle_id: UUID
    policy_id: UUID
    policy_version: int
    threshold_code: str
    direction: str
    generation: int

    @property
    def deduplication_key(self) -> str:
        return ":".join(
            (
                str(self.service_id),
                str(self.cycle_id),
                str(self.policy_id),
                str(self.policy_version),
                self.threshold_code,
                self.direction,
                str(self.generation),
            )
        )


def evaluate_quota(
    remaining: UsageRemaining,
    aggregate: UsageAggregate,
    policy: ThresholdPolicy,
    confirmation_count: int,
    confirmed_observations: int,
) -> QuotaState:
    if remaining.allowance.unlimited:
        return QuotaState.AVAILABLE
    if (
        aggregate.confidence in {ObservationConfidence.LOW, ObservationConfidence.UNUSABLE}
        or remaining.used_bytes is None
    ):
        return QuotaState.UNKNOWN
    if aggregate.anomaly_types:
        return QuotaState.MANUAL_REVIEW
    if remaining.remaining_bytes == 0:
        return (
            QuotaState.EXHAUSTED_CONFIRMED
            if confirmed_observations >= confirmation_count
            else QuotaState.EXHAUSTED_PENDING_CONFIRMATION
        )
    percent = remaining.consumed_percent or 0
    if percent >= policy.critical_percent:
        return QuotaState.CRITICAL
    if percent >= policy.warning_percent:
        return QuotaState.WARNING
    return QuotaState.AVAILABLE


def evaluate_expiry(
    expires_at: datetime | None,
    now: datetime,
    policy: ThresholdPolicy,
    grace: timedelta,
    confirmed_observations: int,
    confirmation_count: int,
    pending_renewal_committed: bool = False,
) -> ExpiryState:
    if expires_at is None:
        return ExpiryState.NO_EXPIRY
    if pending_renewal_committed:
        return ExpiryState.ACTIVE
    if expires_at <= now:
        if now - expires_at <= grace:
            return ExpiryState.GRACE_PERIOD
        return (
            ExpiryState.EXPIRED_CONFIRMED
            if confirmed_observations >= confirmation_count
            else ExpiryState.EXPIRED_PENDING_CONFIRMATION
        )
    remaining = expires_at - now
    if remaining <= policy.expiry_critical:
        return ExpiryState.CRITICAL
    if remaining <= policy.expiry_warning:
        return ExpiryState.WARNING
    return ExpiryState.ACTIVE


@dataclass(frozen=True)
class ServiceRestrictions:
    reasons: frozenset[RestrictionReason] = frozenset()

    @property
    def available(self) -> bool:
        return not self.reasons

    def add(self, reason: RestrictionReason) -> ServiceRestrictions:
        return ServiceRestrictions(self.reasons | {reason})

    def remove_resolved(self, reason: RestrictionReason) -> ServiceRestrictions:
        return ServiceRestrictions(self.reasons - {reason})


def can_restore(restrictions: ServiceRestrictions, resolved_reason: RestrictionReason) -> bool:
    blocking = restrictions.reasons - {resolved_reason}
    return not blocking and resolved_reason in restrictions.reasons


@dataclass(frozen=True)
class FirstUseExpiry:
    state: FirstUseState
    duration: timedelta
    started_at: datetime | None = None
    calculated_expiry_at: datetime | None = None


def process_first_use(
    state: FirstUseExpiry,
    observation: UsageObservation,
    *,
    provider_verified_first_use_at: datetime | None = None,
    use_online_evidence: bool = False,
) -> FirstUseExpiry:
    if state.started_at is not None:
        return state
    evidence = provider_verified_first_use_at
    if (
        evidence is None
        and observation.combined_bytes is not None
        and observation.combined_bytes > 0
    ):
        evidence = observation.observed_at
    if evidence is None and use_online_evidence and observation.online is True:
        evidence = observation.observed_at
    if evidence is None:
        return state
    expiry = evidence + state.duration
    return FirstUseExpiry(FirstUseState.EXPIRY_CALCULATED, state.duration, evidence, expiry)


@dataclass(frozen=True)
class WorkerSchedulePolicy:
    min_interval: timedelta
    active_interval: timedelta
    near_limit_interval: timedelta
    unlimited_interval: timedelta
    suspended_interval: timedelta
    jitter_seconds: int

    def __post_init__(self) -> None:
        if self.min_interval < timedelta(minutes=5):
            raise UsageDomainError(
                UsageErrorCode.USAGE_POLICY_INVALID, "polling interval below safe minimum"
            )
        if self.jitter_seconds < 0:
            raise UsageDomainError(
                UsageErrorCode.USAGE_POLICY_INVALID, "jitter must be non-negative"
            )

    def next_interval(
        self, quota_state: QuotaState, allowance: UsageAllowance, restricted: bool
    ) -> timedelta:
        if restricted:
            return max(self.suspended_interval, self.min_interval)
        if allowance.unlimited:
            return max(self.unlimited_interval, self.min_interval)
        if quota_state in {
            QuotaState.WARNING,
            QuotaState.CRITICAL,
            QuotaState.EXHAUSTED_PENDING_CONFIRMATION,
        }:
            return max(self.near_limit_interval, self.min_interval)
        return max(self.active_interval, self.min_interval)


@dataclass(frozen=True)
class RollupPoint:
    service_id: UUID
    window_start: datetime
    window_end: datetime
    used_bytes: int
    latest_observed_at: datetime


def build_rollup(
    service_id: UUID,
    aggregates: Iterable[UsageAggregate],
    window_start: datetime,
    window_end: datetime,
) -> RollupPoint | None:
    in_window = [
        a
        for a in aggregates
        if a.latest_observed_at is not None
        and window_start <= a.latest_observed_at < window_end
        and a.used_bytes is not None
    ]
    if not in_window:
        return None
    latest = max(in_window, key=lambda a: a.latest_observed_at or datetime.min.replace(tzinfo=UTC))
    return RollupPoint(
        service_id,
        window_start,
        window_end,
        latest.used_bytes or 0,
        latest.latest_observed_at or window_start,
    )
