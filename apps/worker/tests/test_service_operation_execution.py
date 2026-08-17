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
    retry_delay,
)


def _service(*, expires_at: datetime, traffic: int = 10 * 1024**3, version: int = 4):
    return cast(
        ServiceModel,
        SimpleNamespace(
            entitlement_snapshot={"traffic_quota_bytes": traffic, "device_limit": 2},
            expires_at=expires_at,
            version=version,
        ),
    )


def _operation(kind: str, *, traffic_delta: int = 0, duration_delta: int = 0):
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


def test_expired_renewal_target_starts_from_now_not_stale_expiry() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    service = _service(expires_at=now - timedelta(days=10))
    operation = _operation("RENEW", duration_delta=30 * 24 * 60 * 60)

    desired = _desired_state(service, operation, now)

    assert desired["expires_at"] == (now + timedelta(days=30)).isoformat()
    assert desired["traffic_limit_bytes"] == 10 * 1024**3
    assert desired["service_version_base"] == 4


def test_add_traffic_target_is_additive_and_preserves_expiry() -> None:
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    expiry = now + timedelta(days=20)
    service = _service(expires_at=expiry, traffic=25 * 1024**3)
    operation = _operation("ADD_TRAFFIC", traffic_delta=15 * 1024**3)

    desired = _desired_state(service, operation, now)

    assert desired["traffic_limit_bytes"] == 40 * 1024**3
    assert desired["expires_at"] == expiry.isoformat()


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


def test_success_updates_service_version_only_after_all_required_plans_verify() -> None:
    source = getsource(ServiceOperationExecutionWorker._settle)
    all_verified = source.index('all(plan.status == "SUCCEEDED" and plan.verified for plan in required)')
    complete = source.index("self._complete_success")
    assert all_verified < complete
    complete_source = getsource(ServiceOperationExecutionWorker._complete_success)
    assert "service.version += 1" in complete_source
    assert 'operation.status = "SUCCEEDED"' in complete_source
    assert 'event.status = "PROCESSED"' in complete_source


def test_real_executor_uses_certified_additive_adjustment_path() -> None:
    source = getsource(real_service_operation_executor.DatabaseSanaeiServiceOperationExecutor)
    assert "SanaeiAdjustExecutor" in source
    assert "execute_certified_sanaei_adjust" in source
    assert "SanaeiAuthenticatedTransport.authenticate" in source
    assert "UPDATE_REMOTE_IDENTITY" in source
    assert "CREATE_REMOTE_IDENTITY" not in source


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
