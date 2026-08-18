from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform_api.ops_models import TELEGRAM_PRODUCTION_WORKER_ROLE, WorkerHeartbeatModel


class WorkerHeartbeatRecorder:
    def __init__(
        self,
        factory: sessionmaker[Session],
        *,
        role: str = TELEGRAM_PRODUCTION_WORKER_ROLE,
        flush_interval_seconds: float = 10.0,
    ) -> None:
        if not role or len(role) > 48:
            raise ValueError("worker heartbeat role must be between 1 and 48 characters")
        if flush_interval_seconds <= 0:
            raise ValueError("worker heartbeat flush interval must be positive")
        self._factory = factory
        self._role = role
        self._flush_interval_seconds = flush_interval_seconds
        self._last_flush_monotonic: float | None = None
        self._successful_cycles = 0
        self._failed_cycles = 0
        self._consecutive_failures = 0
        self._had_success_since_flush = False
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None

    def record_cycle(
        self,
        *,
        success: bool,
        now: datetime | None = None,
        force: bool = False,
    ) -> bool:
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=UTC)

        if success:
            self._successful_cycles += 1
            self._consecutive_failures = 0
            self._had_success_since_flush = True
            self._last_success_at = observed_at
        else:
            self._failed_cycles += 1
            self._consecutive_failures += 1
            self._last_failure_at = observed_at

        monotonic_now = time.monotonic()
        if (
            not force
            and self._last_flush_monotonic is not None
            and monotonic_now - self._last_flush_monotonic < self._flush_interval_seconds
        ):
            return False

        self._flush(observed_at)
        self._last_flush_monotonic = monotonic_now
        return True

    def _update_values(self, observed_at: datetime) -> dict[str, object]:
        values: dict[str, object] = {"last_seen_at": observed_at}
        if self._successful_cycles:
            values["successful_cycles"] = (
                WorkerHeartbeatModel.successful_cycles + self._successful_cycles
            )
            values["last_success_at"] = self._last_success_at
        if self._failed_cycles:
            values["failed_cycles"] = WorkerHeartbeatModel.failed_cycles + self._failed_cycles
            values["last_failure_at"] = self._last_failure_at
        if self._had_success_since_flush:
            values["consecutive_failures"] = self._consecutive_failures
        elif self._failed_cycles:
            values["consecutive_failures"] = (
                WorkerHeartbeatModel.consecutive_failures + self._failed_cycles
            )
        return values

    def _insert_values(self, observed_at: datetime) -> dict[str, object]:
        return {
            "role": self._role,
            "last_seen_at": observed_at,
            "last_success_at": self._last_success_at,
            "last_failure_at": self._last_failure_at,
            "successful_cycles": self._successful_cycles,
            "failed_cycles": self._failed_cycles,
            "consecutive_failures": self._consecutive_failures,
        }

    def _flush(self, observed_at: datetime) -> None:
        if not self._successful_cycles and not self._failed_cycles:
            return

        with self._factory() as db:
            result = db.execute(
                update(WorkerHeartbeatModel)
                .where(WorkerHeartbeatModel.role == self._role)
                .values(**self._update_values(observed_at))
            )
            if result.rowcount == 0:
                try:
                    db.execute(
                        insert(WorkerHeartbeatModel).values(**self._insert_values(observed_at))
                    )
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    db.execute(
                        update(WorkerHeartbeatModel)
                        .where(WorkerHeartbeatModel.role == self._role)
                        .values(**self._update_values(observed_at))
                    )
                    db.commit()
            else:
                db.commit()

        self._successful_cycles = 0
        self._failed_cycles = 0
        self._had_success_since_flush = False
