# pyright: reportPrivateUsage=false
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from inspect import getsource
from types import SimpleNamespace
from typing import cast

from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_worker import real_service_operation_executor, service_operation_execution
from platform_worker.main import build_service_operation_executor
from platform_worker.real_service_operation_executor import DatabaseSanaeiServiceOperationExecutor
from platform_worker.service_operation_execution import (
    BLOCKED_RETRY,
    DisabledServiceOperationExecutor,
    ServiceOperationExecutionWorker,
    _desired_state,
    _renewal_target,
    retry_delay,
)

_DAY = 24 * 60 * 60


def _service(
    *,
    expires_at: datetime | None,
    traffic: int = 10 * 1024**3,
    version: int = 4,
) -> ServiceModel:
    return cast(
        ServiceModel,
        SimpleNamespace(
            entitlement_snapshot={"traffic_quota_bytes": traffic, "device_limit": 2},
            expires_at=expires_at,
            version=version,
        ),
    )


def _operation(
    kind: str,
    *,
    traffic_delta: int = 0,
    duration_delta: int = 0,
) -> ServiceOperationModel:
    return cast(
        ServiceOperationModel,
        SimpleNamespace(
            operation_type=kind,
            desired_change={
                "traffic_delta_bytes": traffic_delta,
                "duration_delta_seconds": duration_delta,
            },
        ),
    )


def test_retry_is_bounded_and_blocked_provider_is_not_hammered() -> None:
    assert retry_delay(1) == timedelta(seconds=30)
    assert retry_delay(100) == timedelta(hours=1)
    assert BLOCKED_RETRY == timedelta(hours=6)


def test_active_renewal_adds_exact_purchased_whole_days() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expiry = now + timedelta(days=10, hours=3)
    operation = _operation("RENEW", duration_delta=30 * _DAY)

    desired = _desired_state(_service(expires_at=expiry), operation, now)

    assert desired["expires_at"] == (expiry + timedelta(days=30)).isoformat()
    assert desired["traffic_limit_bytes"] is None
    assert desired["service_version_base"] == 4


def test_expired_renewal_uses_whole_day_catch_up_without_losing_purchased_time() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    stale_expiry = now - timedelta(days=10, hours=6)
    target = _renewal_target(stale_expiry, now, 30 * _DAY)

    provider_delta = target - stale_expiry
    assert provider_delta.total_seconds() % _DAY == 0
    assert target >= now + timedelta(days=30)
    assert target < now + timedelta(days=31)


def test_renewal_rejects_non_whole_day_duration() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    operation = _operation("RENEW", duration_delta=30 * _DAY + 1)

    try:
        _desired_state(_service(expires_at=now + timedelta(days=2)), operation, now)
    except ValueError as exc:
        assert "whole days" in str(exc)
    else:
        raise AssertionError("non-whole-day renewal must be rejected")


def test_add_traffic_target_is_additive_and_does_not_target_expiry() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    service = _service(expires_at=None, traffic=25 * 1024**3)
    operation = _operation("ADD_TRAFFIC", traffic_delta=15 * 1024**3)

    desired = _desired_state(service, operation, now)

    assert desired["traffic_limit_bytes"] == 40 * 1024**3
    assert desired["expires_at"] is None


def test_worker_claim_is_postgres_safe_and_provider_io_is_outside_claim() -> None:
    source = getsource(ServiceOperationExecutionWorker)
    assert "with_for_update(skip_locked=True)" in source
    assert ".limit(MAX_BATCH)" in source
    assert source.index("self.executor.execute") > source.index("def _prepare")
    assert "ServiceOperationPaymentModel" in source
    assert "SERVICE_OPERATION_SERIALIZED" in source
    assert "COMPENSATION_REQUIRED" in source


def test_target_is_persisted_before_provider_execution_for_crash_safe_replay() -> None:
    source = getsource(ServiceOperationExecutionWorker)
    plan_write = source.index('result_snapshot={"desired_state": desired}')
    provider_call = source.index("self.executor.execute")
    assert plan_write < provider_call
    assert "uuid5(" in source
    assert "expected_snapshot_digest" in source


def test_success_requires_all_required_plans_and_unchanged_service_version() -> None:
    settle_source = getsource(ServiceOperationExecutionWorker._settle)
    expected = 'all(plan.status == "SUCCEEDED" and plan.verified for plan in required)'
    assert expected in settle_source
    complete_source = getsource(ServiceOperationExecutionWorker._complete_success)
    assert "service.version != base_version" in complete_source
    assert "service.version += 1" in complete_source
    assert 'self._set_operation_status(operation, "SUCCEEDED", now)' in complete_source
    assert 'event.status = "PROCESSED"' in complete_source


def test_success_applies_only_the_purchased_local_dimension() -> None:
    source = getsource(ServiceOperationExecutionWorker._complete_success)
    renewal_branch = source.index('if operation.operation_type == "RENEW"')
    traffic_branch = source.index('elif operation.operation_type == "ADD_TRAFFIC"')
    expiry_write = source.index("service.expires_at = expires_at")
    traffic_write = source.index('entitlement["traffic_quota_bytes"] = traffic')
    assert renewal_branch < expiry_write < traffic_branch < traffic_write


def test_real_executor_uses_certified_additive_adjustment_path() -> None:
    source = getsource(real_service_operation_executor.DatabaseSanaeiServiceOperationExecutor)
    assert "Sanaei3xUiV370Executor" in source
    assert "execute_v370_mutation" in source
    assert "connect_v370" in source
    assert "UPDATE_REMOTE_IDENTITY" in source
    assert "CREATE_REMOTE_IDENTITY" not in source


def test_real_executor_ignores_unpurchased_provider_dimension() -> None:
    source = getsource(real_service_operation_executor.DatabaseSanaeiServiceOperationExecutor)
    assert "RemoteTrafficLimit(None, unlimited=True)" in source
    assert "RemoteExpiryPolicy(None, no_expiry=True)" in source


def test_production_composition_reaches_real_executor_only_when_writes_enabled() -> None:
    factory = object()
    assert isinstance(
        build_service_operation_executor(factory, False),  # type: ignore[arg-type]
        DisabledServiceOperationExecutor,
    )
    assert isinstance(
        build_service_operation_executor(factory, True),  # type: ignore[arg-type]
        DatabaseSanaeiServiceOperationExecutor,
    )


def test_worker_does_not_perform_wallet_mutations_or_create_orders() -> None:
    source = getsource(service_operation_execution)
    assert "LedgerPostingModel" not in source
    assert "WalletReservationModel" not in source
    assert "OrderModel(" not in source
