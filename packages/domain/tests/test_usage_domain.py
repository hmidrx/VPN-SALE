from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from vpnsale_domain.providers import ProviderKind
from vpnsale_domain.usage import (
    CERTIFIED_COUNTER_SEMANTICS,
    AggregationPolicyVersion,
    AggregationStrategy,
    CounterAnomalyType,
    CounterCheckpoint,
    FirstUseExpiry,
    FirstUseState,
    ObservationConfidence,
    QuotaState,
    RestrictionReason,
    ServiceRestrictions,
    ThresholdEvent,
    ThresholdPolicy,
    UsageAllowance,
    UsageDomainError,
    UsageObservation,
    WorkerSchedulePolicy,
    aggregate_usage,
    calculate_remaining,
    can_restore,
    classify_counter_observation,
    evaluate_expiry,
    evaluate_quota,
    process_first_use,
)

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


def obs(
    service_id: UUID | None = None,
    attachment_id: UUID | None = None,
    scope: str = "scope",
    value: int | None = 100,
    minutes: int = 0,
    primary: bool = False,
    group: str | None = None,
) -> UsageObservation:
    return UsageObservation(
        observation_id=uuid4(),
        service_id=service_id or uuid4(),
        attachment_id=attachment_id or uuid4(),
        provider_kind=ProviderKind.SANAEI_3X_UI,
        contract_code="sanaei-3x-ui-read-v1",
        observed_at=NOW - timedelta(minutes=minutes),
        counter_scope_key=scope,
        combined_bytes=value,
        primary=primary,
        mirrored_group=group,
    )


def test_provider_specific_counter_semantics_are_not_collapsed() -> None:
    assert (
        CERTIFIED_COUNTER_SEMANTICS[ProviderKind.SANAEI_3X_UI].combined_counter_field == "up+down"
    )
    assert CERTIFIED_COUNTER_SEMANTICS[ProviderKind.ALIREZA_X_UI].combined_counter_field == "total"
    assert CERTIFIED_COUNTER_SEMANTICS[ProviderKind.PASARGUARD].supports_first_use_expiry is True
    assert len({s.counter_scope for s in CERTIFIED_COUNTER_SEMANTICS.values()}) == 3


def test_usage_snapshot_rejects_negative_and_naive_time() -> None:
    with pytest.raises(UsageDomainError):
        obs(value=-1)
    with pytest.raises(UsageDomainError):
        UsageObservation(
            uuid4(),
            uuid4(),
            uuid4(),
            ProviderKind.PASARGUARD,
            "pasarguard-read-v1",
            datetime(2026, 1, 1),
            "scope",
            1,
        )


def test_positive_and_unchanged_delta_preserve_lifetime() -> None:
    first = obs(value=100)
    initial = classify_counter_observation(None, first)
    second = obs(service_id=first.service_id, attachment_id=first.attachment_id, value=250)
    changed = classify_counter_observation(initial.checkpoint, second)
    assert changed.delta is not None
    assert changed.delta.delta_bytes == 150
    assert changed.checkpoint.lifetime_bytes == 150
    repeated = classify_counter_observation(changed.checkpoint, second)
    assert repeated.delta is None
    assert repeated.checkpoint.lifetime_bytes == 150


def test_confirmed_reset_starts_generation_without_erasing_lifetime() -> None:
    previous = CounterCheckpoint(uuid4(), "scope", 1, 900, 500, uuid4())
    result = classify_counter_observation(
        previous,
        obs(attachment_id=previous.attachment_id, value=10),
        reset_operation_confirmed=True,
    )
    assert result.starts_new_generation
    assert result.anomaly == CounterAnomalyType.COUNTER_RESET_CONFIRMED
    assert result.checkpoint.lifetime_bytes == 500
    assert result.delta is None


def test_unexplained_decrease_and_suspected_wrap_do_not_create_negative_delta() -> None:
    previous = CounterCheckpoint(uuid4(), "scope", 1, 1000, 800, uuid4())
    result = classify_counter_observation(
        previous, obs(attachment_id=previous.attachment_id, value=700)
    )
    assert result.delta is None
    assert result.anomaly == CounterAnomalyType.COUNTER_DECREASE_UNEXPLAINED
    wrapped = classify_counter_observation(
        CounterCheckpoint(previous.attachment_id, "scope", 1, 2**32 + 1, 800, uuid4()),
        obs(attachment_id=previous.attachment_id, value=2),
    )
    assert wrapped.anomaly == CounterAnomalyType.COUNTER_WRAP_SUSPECTED


def test_shared_identity_deduplicates_and_independent_sums() -> None:
    service = uuid4()
    shared = [obs(service, scope="global", value=100), obs(service, scope="global", value=100)]
    policy = AggregationPolicyVersion(uuid4(), 1, AggregationStrategy.SHARED_IDENTITY_DEDUPLICATED)
    assert aggregate_usage(shared, policy, NOW).used_bytes == 100
    independent = [obs(service, scope="a", value=100), obs(service, scope="b", value=75)]
    sum_policy = AggregationPolicyVersion(
        uuid4(), 1, AggregationStrategy.SUM_INDEPENDENT_IDENTITIES
    )
    assert aggregate_usage(independent, sum_policy, NOW).used_bytes == 175


def test_mirrored_migration_overlap_uses_max_per_group() -> None:
    service = uuid4()
    records = [
        obs(service, scope="source", value=500, group="move-1"),
        obs(service, scope="target", value=450, group="move-1"),
    ]
    policy = AggregationPolicyVersion(
        uuid4(), 1, AggregationStrategy.MIGRATION_OVERLAP_DEDUPLICATED
    )
    aggregate = aggregate_usage(records, policy, NOW)
    assert aggregate.used_bytes == 500
    assert aggregate.explanation_code == "MIRRORED_MAX_DEDUPLICATED"


def test_stale_partial_unlimited_zero_and_unknown_remaining() -> None:
    policy = AggregationPolicyVersion(
        uuid4(), 1, AggregationStrategy.SINGLE_ATTACHMENT, max_staleness=timedelta(minutes=5)
    )
    stale = aggregate_usage([obs(minutes=10)], policy, NOW)
    assert stale.confidence == ObservationConfidence.LOW
    assert calculate_remaining(UsageAllowance(0), 0).remaining_bytes == 0
    assert calculate_remaining(UsageAllowance(None, unlimited=True), 999).remaining_bytes is None
    assert calculate_remaining(UsageAllowance(None), None).used_bytes is None


def test_quota_thresholds_confirmation_and_stale_blocking() -> None:
    service = uuid4()
    aggregate = aggregate_usage(
        [obs(service, value=96)],
        AggregationPolicyVersion(uuid4(), 1, AggregationStrategy.SINGLE_ATTACHMENT),
        NOW,
    )
    policy = ThresholdPolicy(uuid4(), 1)
    assert (
        evaluate_quota(calculate_remaining(UsageAllowance(100), 96), aggregate, policy, 2, 1)
        == QuotaState.CRITICAL
    )
    exhausted = aggregate_usage(
        [obs(service, value=101)],
        AggregationPolicyVersion(uuid4(), 1, AggregationStrategy.SINGLE_ATTACHMENT),
        NOW,
    )
    assert (
        evaluate_quota(calculate_remaining(UsageAllowance(100), 101), exhausted, policy, 2, 1)
        == QuotaState.EXHAUSTED_PENDING_CONFIRMATION
    )
    assert (
        evaluate_quota(calculate_remaining(UsageAllowance(100), 101), exhausted, policy, 2, 2)
        == QuotaState.EXHAUSTED_CONFIRMED
    )
    stale = aggregate_usage(
        [obs(service, value=101, minutes=240)],
        AggregationPolicyVersion(
            uuid4(), 1, AggregationStrategy.SINGLE_ATTACHMENT, max_staleness=timedelta(minutes=1)
        ),
        NOW,
    )
    assert (
        evaluate_quota(calculate_remaining(UsageAllowance(100), None), stale, policy, 1, 1)
        == QuotaState.UNKNOWN
    )


def test_expiry_first_use_and_unreliable_online_rejection() -> None:
    policy = ThresholdPolicy(uuid4(), 1)
    assert evaluate_expiry(None, NOW, policy, timedelta(), 1, 1).value == "NO_EXPIRY"
    assert (
        evaluate_expiry(NOW + timedelta(hours=12), NOW, policy, timedelta(), 1, 1).value
        == "CRITICAL"
    )
    assert (
        evaluate_expiry(NOW - timedelta(days=2), NOW, policy, timedelta(), 1, 1).value
        == "EXPIRED_CONFIRMED"
    )
    state = FirstUseExpiry(FirstUseState.NOT_STARTED, timedelta(days=30))
    online_only = obs(value=0)
    online_only = UsageObservation(
        observation_id=online_only.observation_id,
        service_id=online_only.service_id,
        attachment_id=online_only.attachment_id,
        provider_kind=online_only.provider_kind,
        contract_code=online_only.contract_code,
        observed_at=online_only.observed_at,
        counter_scope_key=online_only.counter_scope_key,
        combined_bytes=online_only.combined_bytes,
        upload_bytes=online_only.upload_bytes,
        download_bytes=online_only.download_bytes,
        remote_limit_bytes=online_only.remote_limit_bytes,
        remote_expiry_at=online_only.remote_expiry_at,
        remote_enabled=online_only.remote_enabled,
        online=True,
        generation_number=online_only.generation_number,
        confidence=online_only.confidence,
        mirrored_group=online_only.mirrored_group,
        primary=online_only.primary,
    )
    assert process_first_use(state, online_only).started_at is None
    started = process_first_use(state, obs(value=1))
    assert started.calculated_expiry_at == NOW + timedelta(days=30)


def test_notification_dedup_and_restoration_restrictions() -> None:
    event = ThresholdEvent(uuid4(), uuid4(), uuid4(), 1, "TRAFFIC_80", "DOWN", 1)
    assert event.deduplication_key == event.deduplication_key
    restrictions = ServiceRestrictions(frozenset({RestrictionReason.TRAFFIC_EXHAUSTED}))
    assert can_restore(restrictions, RestrictionReason.TRAFFIC_EXHAUSTED)
    blocked = restrictions.add(RestrictionReason.SECURITY_HOLD)
    assert not can_restore(blocked, RestrictionReason.TRAFFIC_EXHAUSTED)


def test_worker_schedule_safe_minimums() -> None:
    with pytest.raises(UsageDomainError):
        WorkerSchedulePolicy(
            timedelta(seconds=1),
            timedelta(minutes=5),
            timedelta(minutes=5),
            timedelta(hours=6),
            timedelta(hours=12),
            60,
        )
    policy = WorkerSchedulePolicy(
        timedelta(minutes=5),
        timedelta(minutes=30),
        timedelta(minutes=10),
        timedelta(hours=6),
        timedelta(hours=12),
        60,
    )
    assert policy.next_interval(QuotaState.WARNING, UsageAllowance(100), False) == timedelta(
        minutes=10
    )
