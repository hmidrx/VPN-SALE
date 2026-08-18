from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_operation_guard import SERVICE_OPERATION_UNRESOLVED_STATES
from platform_worker.service_operation_notification import (
    CLAIM_TIMEOUT,
    EVENT_TYPE,
    ServiceOperationNotificationWorker,
)
from platform_worker.service_usage_sync import build_safe_usage_projection

_GIB = 1024**3


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    TransactionalOutboxModel.__table__.create(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _event(
    *,
    status: str,
    now: datetime,
    claimed_at: datetime | None = None,
    event_type: str = EVENT_TYPE,
) -> TransactionalOutboxModel:
    return TransactionalOutboxModel(
        id=str(uuid4()),
        event_key=f"drill:{uuid4()}",
        event_type=event_type,
        status=status,
        payload={"operation_id": str(uuid4()), "terminal_status": "SUCCEEDED"},
        attempt_count=1 if claimed_at is not None else 0,
        available_at=now - timedelta(minutes=1),
        claimed_at=claimed_at,
        failure_category="PREVIOUS_FAILURE" if status in {"PENDING", "CLAIMED"} else "MAX_ATTEMPTS",
        created_at=now - timedelta(minutes=30),
    )


def test_stale_claim_is_recovered_but_fresh_claim_and_terminal_failure_are_not() -> None:
    factory = _factory()
    now = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
    stale = _event(status="CLAIMED", now=now, claimed_at=now - CLAIM_TIMEOUT - timedelta(seconds=1))
    fresh = _event(status="CLAIMED", now=now, claimed_at=now - CLAIM_TIMEOUT + timedelta(seconds=1))
    failed = _event(status="FAILED", now=now)

    with factory.begin() as db:
        db.add_all((stale, fresh, failed))

    with factory.begin() as db:
        claimed_ids = ServiceOperationNotificationWorker._claim(db, now)

    assert claimed_ids == [stale.id]
    with factory() as db:
        recovered = db.get(TransactionalOutboxModel, stale.id)
        untouched_fresh = db.get(TransactionalOutboxModel, fresh.id)
        untouched_failed = db.get(TransactionalOutboxModel, failed.id)
        assert recovered is not None
        assert recovered.status == "CLAIMED"
        assert recovered.attempt_count == 2
        assert recovered.failure_category is None
        assert untouched_fresh is not None
        assert untouched_fresh.attempt_count == 1
        assert untouched_failed is not None
        assert untouched_failed.status == "FAILED"
        assert untouched_failed.attempt_count == 0
        assert untouched_failed.failure_category == "MAX_ATTEMPTS"


def test_recovery_contract_keeps_all_unresolved_paid_states_blocking() -> None:
    assert SERVICE_OPERATION_UNRESOLVED_STATES == {
        "PARTIALLY_APPLIED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "MANUAL_REVIEW",
    }


def test_provider_counter_failure_remains_unknown_during_recovery() -> None:
    now = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
    projection = build_safe_usage_projection(
        service_id="11111111-1111-4111-8111-111111111111",
        attachment_id="22222222-2222-4222-8222-222222222222",
        allowance_bytes=100 * _GIB,
        combined_bytes=None,
        previous_combined_bytes=70 * _GIB,
        observed_at=now,
        expires_at=now + timedelta(days=30),
    )

    assert projection.used_bytes is None
    assert projection.remaining_bytes is None
    assert projection.quota_state == "UNKNOWN"
    assert projection.explanation_code == "COUNTER_UNAVAILABLE"
