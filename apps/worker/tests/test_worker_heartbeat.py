from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.ops_models import TELEGRAM_PRODUCTION_WORKER_ROLE, WorkerHeartbeatModel
from platform_worker.heartbeat import WorkerHeartbeatRecorder


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    WorkerHeartbeatModel.__table__.create(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def test_worker_heartbeat_persists_cycle_outcomes_without_instance_dimensions() -> None:
    factory = _factory()
    recorder = WorkerHeartbeatRecorder(factory)
    started = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    assert recorder.record_cycle(success=True, now=started, force=True) is True
    assert (
        recorder.record_cycle(
            success=False,
            now=started + timedelta(seconds=5),
            force=True,
        )
        is True
    )

    with factory() as db:
        heartbeat = db.get(WorkerHeartbeatModel, TELEGRAM_PRODUCTION_WORKER_ROLE)
        assert heartbeat is not None
        assert heartbeat.successful_cycles == 1
        assert heartbeat.failed_cycles == 1
        assert heartbeat.consecutive_failures == 1
        assert _as_utc(heartbeat.last_seen_at) == started + timedelta(seconds=5)
        assert _as_utc(heartbeat.last_success_at) == started
        assert _as_utc(heartbeat.last_failure_at) == started + timedelta(seconds=5)


def test_duplicate_role_recorders_share_one_safe_row_and_success_clears_streak() -> None:
    factory = _factory()
    first = WorkerHeartbeatRecorder(factory)
    second = WorkerHeartbeatRecorder(factory)
    started = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    first.record_cycle(success=False, now=started, force=True)
    second.record_cycle(success=False, now=started + timedelta(seconds=1), force=True)
    second.record_cycle(success=True, now=started + timedelta(seconds=2), force=True)

    with factory() as db:
        rows = db.query(WorkerHeartbeatModel).all()
        assert len(rows) == 1
        heartbeat = rows[0]
        assert heartbeat.role == TELEGRAM_PRODUCTION_WORKER_ROLE
        assert heartbeat.successful_cycles == 1
        assert heartbeat.failed_cycles == 2
        assert heartbeat.consecutive_failures == 0
        assert _as_utc(heartbeat.last_seen_at) == started + timedelta(seconds=2)
