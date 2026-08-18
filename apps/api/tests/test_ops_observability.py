from __future__ import annotations

from datetime import UTC, datetime

from fastapi.routing import APIRoute

from platform_api.management import current_admin
from platform_api.ops_observability import (
    FulfillmentHealth,
    OperationsHealthSnapshot,
    OutboxHealth,
    ServiceOperationHealth,
    UsageSyncHealth,
    WorkerHealth,
    classify_operations_health,
    render_prometheus,
    router,
)


def _healthy_parts() -> (
    tuple[
        WorkerHealth,
        OutboxHealth,
        FulfillmentHealth,
        ServiceOperationHealth,
        UsageSyncHealth,
    ]
):
    return (
        WorkerHealth(
            state="RUNNING",
            last_seen_age_seconds=5,
            successful_cycles=20,
            failed_cycles=0,
            consecutive_failures=0,
            last_failure_age_seconds=None,
        ),
        OutboxHealth(
            pending_due=0,
            retrying=0,
            failed=0,
            stale_claims=0,
            oldest_due_age_seconds=0,
        ),
        FulfillmentHealth(retry_pending=0, blocked=0, operator_review=0, failed=0),
        ServiceOperationHealth(in_progress=0, review_required=0),
        UsageSyncHealth(
            latest_status="SUCCESS",
            latest_run_age_seconds=30,
            last_success_age_seconds=30,
            degraded_runs_last_hour=0,
            stale_active_accounts=0,
        ),
    )


def test_health_classification_distinguishes_degraded_from_operator_action() -> None:
    worker, outbox, fulfillment, service_operations, usage_sync = _healthy_parts()
    status, signals = classify_operations_health(
        worker=worker,
        outbox=outbox.model_copy(update={"retrying": 2}),
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )
    assert status == "DEGRADED"
    assert signals == ["OUTBOX_RETRYING"]

    status, signals = classify_operations_health(
        worker=worker,
        outbox=outbox,
        fulfillment=fulfillment,
        service_operations=service_operations.model_copy(update={"review_required": 1}),
        usage_sync=usage_sync,
    )
    assert status == "ACTION_REQUIRED"
    assert signals == ["SERVICE_OPERATION_REVIEW_REQUIRED"]


def test_worker_liveness_distinguishes_missing_stale_and_failure_streaks() -> None:
    worker, outbox, fulfillment, service_operations, usage_sync = _healthy_parts()
    for state, expected_signal in (
        ("MISSING", "WORKER_HEARTBEAT_MISSING"),
        ("STALE", "WORKER_HEARTBEAT_STALE"),
    ):
        status, signals = classify_operations_health(
            worker=worker.model_copy(update={"state": state}),
            outbox=outbox,
            fulfillment=fulfillment,
            service_operations=service_operations,
            usage_sync=usage_sync,
        )
        assert status == "ACTION_REQUIRED"
        assert signals == [expected_signal]

    status, signals = classify_operations_health(
        worker=worker.model_copy(
            update={"state": "DEGRADED", "failed_cycles": 1, "consecutive_failures": 1}
        ),
        outbox=outbox,
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )
    assert status == "DEGRADED"
    assert signals == ["WORKER_RECENT_CYCLE_FAILURE"]

    status, signals = classify_operations_health(
        worker=worker.model_copy(
            update={"state": "DEGRADED", "failed_cycles": 3, "consecutive_failures": 3}
        ),
        outbox=outbox,
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )
    assert status == "ACTION_REQUIRED"
    assert signals == ["WORKER_CYCLE_FAILURE_STREAK"]


def test_prometheus_output_is_bounded_and_contains_no_sensitive_dimensions() -> None:
    worker, outbox, fulfillment, service_operations, usage_sync = _healthy_parts()
    snapshot = OperationsHealthSnapshot(
        generated_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        status="DEGRADED",
        signals=["OUTBOX_RETRYING"],
        worker=worker,
        outbox=outbox.model_copy(update={"retrying": 1, "oldest_due_age_seconds": 75}),
        fulfillment=fulfillment,
        service_operations=service_operations,
        usage_sync=usage_sync,
    )

    body = render_prometheus(snapshot)

    assert 'vpnsale_ops_health_state{state="DEGRADED"} 1' in body
    assert 'vpnsale_ops_worker_state{state="RUNNING"} 1' in body
    assert "vpnsale_ops_worker_successful_cycles 20" in body
    assert "vpnsale_ops_worker_last_seen_age_seconds 5" in body
    assert "vpnsale_ops_outbox_retrying 1" in body
    assert "vpnsale_ops_outbox_oldest_due_age_seconds 75" in body
    for forbidden in (
        "customer_id",
        "telegram_user_id",
        "panel_id",
        "remote_identity",
        "credential",
        "password",
        "token",
        "secret",
        "hostname",
        "instance_id",
    ):
        assert forbidden not in body.lower()


def test_operational_health_routes_require_authenticated_admin_dependency() -> None:
    routes = {route.path: route for route in router.routes if isinstance(route, APIRoute)}
    for path in (
        "/api/v1/admin/management/operations/health",
        "/api/v1/admin/management/operations/metrics",
    ):
        dependency_calls = {dependency.call for dependency in routes[path].dependant.dependencies}
        assert current_admin in dependency_calls
