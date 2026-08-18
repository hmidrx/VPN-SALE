"""Durable Telegram notifications for authoritative service traffic transitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, aliased, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.notification_preferences import CustomerNotificationPreferenceModel
from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel
from platform_api.usage_models import ServiceUsageAccountModel, ServiceUsageAggregateModel

from .manual_topup_delivery import TelegramDeliveryError, retry_delay

logger = logging.getLogger(__name__)

EVENT_TYPE = "service_traffic.telegram_notification.v1"
BATCH_SIZE = 25
MAX_ATTEMPTS = 6
CLAIM_TIMEOUT = timedelta(minutes=10)
FRESHNESS_LIMIT = timedelta(hours=2)
_CALLBACK_PREFIX = "b:v1:svc_open:"
_EVENT_KEY_PREFIX = "tg-svc-traffic:"
_STAGE_WARNING = "WARNING"
_STAGE_CRITICAL = "CRITICAL"
_STAGE_EXHAUSTED = "EXHAUSTED"
_STAGES = frozenset({_STAGE_WARNING, _STAGE_CRITICAL, _STAGE_EXHAUSTED})


class InvalidServiceTrafficNotification(RuntimeError):
    """Persisted usage data cannot produce a customer-safe notification."""


class StaleServiceTrafficNotification(RuntimeError):
    """The authoritative usage state changed after a notification was queued."""


class ServiceTrafficTelegramTransport(Protocol):
    def send_callback(
        self,
        telegram_user_id: int,
        text: str,
        button_text: str,
        callback_data: str,
    ) -> None: ...


@dataclass(frozen=True)
class ServiceTrafficNotificationTarget:
    service_reference: str
    customer_id: str
    stage: str
    remaining_bytes: int | None
    consumed_percent: int | None


def _stage_for_state(state: str) -> str | None:
    if state == "WARNING":
        return _STAGE_WARNING
    if state == "CRITICAL":
        return _STAGE_CRITICAL
    if state == "EXHAUSTED_CONFIRMED":
        return _STAGE_EXHAUSTED
    return None


def _state_rank(state: str) -> int:
    if state == "WARNING":
        return 1
    if state in {"CRITICAL", "EXHAUSTED_PENDING_CONFIRMATION"}:
        return 2
    if state in {
        "EXHAUSTED_CONFIRMED",
        "ENFORCEMENT_PENDING",
        "ENFORCED",
        "ENFORCEMENT_FAILED",
    }:
        return 3
    return 0


def _should_notify(current_state: str, previous_state: str | None) -> bool:
    return _stage_for_state(current_state) is not None and _state_rank(current_state) > _state_rank(
        previous_state or "UNKNOWN"
    )


def _event_key(aggregate: ServiceUsageAggregateModel, stage: str) -> str:
    if stage not in _STAGES or not aggregate.id:
        raise InvalidServiceTrafficNotification("traffic event key is invalid")
    key = f"{_EVENT_KEY_PREFIX}{aggregate.id}:{stage}"
    if len(key) > 120:
        raise InvalidServiceTrafficNotification("traffic event key is too long")
    return key


def _callback_data(service_reference: str) -> str:
    data = f"{_CALLBACK_PREFIX}{service_reference}"
    if not service_reference or len(data.encode()) > 64:
        raise InvalidServiceTrafficNotification("service callback is invalid")
    return data


def _remaining_text(value: int | None) -> str:
    if value is None:
        return "نامشخص"
    value = max(0, value)
    gib = 1024**3
    mib = 1024**2
    if value >= gib:
        amount = value / gib
        return f"{amount:.1f}".rstrip("0").rstrip(".") + " گیگابایت"
    return f"{max(0, round(value / mib)):,} مگابایت"


def _notification_text(target: ServiceTrafficNotificationTarget) -> str:
    if target.stage == _STAGE_WARNING:
        return (
            f"⚠️ حجم سرویس {target.service_reference} رو به اتمام است.\n"
            f"حجم باقی‌مانده: {_remaining_text(target.remaining_bytes)}\n"
            "برای جلوگیری از قطع سرویس، در صورت نیاز از بخش مدیریت سرویس حجم اضافه تهیه کنید."
        )
    if target.stage == _STAGE_CRITICAL:
        return (
            f"🟠 حجم سرویس {target.service_reference} تقریباً تمام شده است.\n"
            f"حجم باقی‌مانده: {_remaining_text(target.remaining_bytes)}\n"
            "اگر قصد ادامه استفاده دارید، بهتر است حجم اضافه تهیه کنید."
        )
    if target.stage == _STAGE_EXHAUSTED:
        return (
            f"🔴 حجم سرویس {target.service_reference} تمام شده است.\n"
            "برای ادامه استفاده، سرویس را باز کنید و در صورت امکان حجم اضافه تهیه کنید."
        )
    raise InvalidServiceTrafficNotification("traffic notification stage is invalid")


class ServiceTrafficNotificationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        transport: ServiceTrafficTelegramTransport,
        bot_enabled: bool,
    ) -> None:
        self.factory = factory
        self.transport = transport
        self.bot_enabled = bot_enabled

    @staticmethod
    def _previous(
        db: Session, aggregate: ServiceUsageAggregateModel
    ) -> ServiceUsageAggregateModel | None:
        return db.scalar(
            select(ServiceUsageAggregateModel)
            .where(
                ServiceUsageAggregateModel.usage_account_id == aggregate.usage_account_id,
                or_(
                    ServiceUsageAggregateModel.calculated_at < aggregate.calculated_at,
                    and_(
                        ServiceUsageAggregateModel.calculated_at == aggregate.calculated_at,
                        ServiceUsageAggregateModel.id < aggregate.id,
                    ),
                ),
            )
            .order_by(
                ServiceUsageAggregateModel.calculated_at.desc(),
                ServiceUsageAggregateModel.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _enqueue(db: Session, now: datetime) -> int:
        newer = aliased(ServiceUsageAggregateModel)
        newer_exists = exists().where(
            newer.usage_account_id == ServiceUsageAggregateModel.usage_account_id,
            or_(
                newer.calculated_at > ServiceUsageAggregateModel.calculated_at,
                and_(
                    newer.calculated_at == ServiceUsageAggregateModel.calculated_at,
                    newer.id > ServiceUsageAggregateModel.id,
                ),
            ),
        )
        aggregates = list(
            db.scalars(
                select(ServiceUsageAggregateModel)
                .join(
                    ServiceUsageAccountModel,
                    ServiceUsageAccountModel.id == ServiceUsageAggregateModel.usage_account_id,
                )
                .join(ServiceModel, ServiceModel.id == ServiceUsageAccountModel.service_id)
                .where(
                    ServiceModel.lifecycle == "ACTIVE",
                    ServiceUsageAggregateModel.quota_state.in_(
                        ("WARNING", "CRITICAL", "EXHAUSTED_CONFIRMED")
                    ),
                    ServiceUsageAggregateModel.confidence.in_(("HIGH", "MEDIUM")),
                    ServiceUsageAggregateModel.latest_observed_at.is_not(None),
                    ServiceUsageAggregateModel.latest_observed_at >= now - FRESHNESS_LIMIT,
                    ~newer_exists,
                )
                .order_by(
                    ServiceUsageAggregateModel.calculated_at,
                    ServiceUsageAggregateModel.id,
                )
                .limit(BATCH_SIZE * 3)
                .with_for_update(skip_locked=True)
            )
        )
        enqueued = 0
        for aggregate in aggregates:
            stage = _stage_for_state(aggregate.quota_state)
            if stage is None:
                continue
            previous = ServiceTrafficNotificationWorker._previous(db, aggregate)
            if not _should_notify(
                aggregate.quota_state,
                previous.quota_state if previous is not None else None,
            ):
                continue
            event_key = _event_key(aggregate, stage)
            already_enqueued = db.scalar(
                select(TransactionalOutboxModel.id).where(
                    TransactionalOutboxModel.event_key == event_key
                )
            )
            if already_enqueued is not None:
                continue
            account = db.get(ServiceUsageAccountModel, aggregate.usage_account_id)
            if account is None:
                continue
            db.add(
                TransactionalOutboxModel(
                    event_key=event_key,
                    event_type=EVENT_TYPE,
                    status="PENDING",
                    payload={
                        "service_id": account.service_id,
                        "usage_account_id": account.id,
                        "aggregate_id": aggregate.id,
                        "stage": stage,
                    },
                    attempt_count=0,
                    available_at=now,
                )
            )
            enqueued += 1
            if enqueued >= BATCH_SIZE:
                break
        db.flush()
        return enqueued

    @staticmethod
    def _claim(db: Session, now: datetime) -> list[str]:
        stale = now - CLAIM_TIMEOUT
        events = list(
            db.scalars(
                select(TransactionalOutboxModel)
                .where(
                    TransactionalOutboxModel.event_type == EVENT_TYPE,
                    TransactionalOutboxModel.available_at <= now,
                    or_(
                        TransactionalOutboxModel.status == "PENDING",
                        (TransactionalOutboxModel.status == "CLAIMED")
                        & (TransactionalOutboxModel.claimed_at < stale),
                    ),
                )
                .order_by(
                    TransactionalOutboxModel.available_at,
                    TransactionalOutboxModel.created_at,
                )
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )
        for event in events:
            event.status = "CLAIMED"
            event.claimed_at = now
            event.attempt_count += 1
            event.failure_category = None
        db.flush()
        return [event.id for event in events]

    def run_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        with self.factory.begin() as db:
            self._enqueue(db, now)
            ids = self._claim(db, now)
        for event_id in ids:
            self._deliver(event_id, now)
        return len(ids)

    @staticmethod
    def _latest(
        db: Session, usage_account_id: str
    ) -> ServiceUsageAggregateModel | None:
        return db.scalar(
            select(ServiceUsageAggregateModel)
            .where(ServiceUsageAggregateModel.usage_account_id == usage_account_id)
            .order_by(
                ServiceUsageAggregateModel.calculated_at.desc(),
                ServiceUsageAggregateModel.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _target(
        event: TransactionalOutboxModel,
        service: ServiceModel | None,
        account: ServiceUsageAccountModel | None,
        source: ServiceUsageAggregateModel | None,
        latest: ServiceUsageAggregateModel | None,
        now: datetime,
    ) -> ServiceTrafficNotificationTarget:
        service_id = event.payload.get("service_id")
        usage_account_id = event.payload.get("usage_account_id")
        aggregate_id = event.payload.get("aggregate_id")
        stage = event.payload.get("stage")
        if (
            service is None
            or account is None
            or source is None
            or latest is None
            or not isinstance(service_id, str)
            or service.id != service_id
            or not isinstance(usage_account_id, str)
            or account.id != usage_account_id
            or account.service_id != service.id
            or not isinstance(aggregate_id, str)
            or source.id != aggregate_id
            or source.usage_account_id != account.id
            or latest.usage_account_id != account.id
            or not isinstance(stage, str)
            or stage not in _STAGES
            or _stage_for_state(source.quota_state) != stage
        ):
            raise InvalidServiceTrafficNotification("traffic notification scope is invalid")
        if service.lifecycle != "ACTIVE":
            raise StaleServiceTrafficNotification("service is no longer active")
        if (
            latest.latest_observed_at is None
            or latest.latest_observed_at.tzinfo is None
            or now - latest.latest_observed_at > FRESHNESS_LIMIT
            or latest.confidence not in {"HIGH", "MEDIUM"}
        ):
            raise StaleServiceTrafficNotification("usage observation is no longer fresh")
        current_stage = _stage_for_state(latest.quota_state)
        if current_stage != stage:
            raise StaleServiceTrafficNotification("traffic notification was superseded")
        if latest.remaining_bytes is not None and latest.remaining_bytes < 0:
            raise InvalidServiceTrafficNotification("remaining traffic is invalid")
        if latest.consumed_percent is not None and not 0 <= latest.consumed_percent <= 100:
            raise InvalidServiceTrafficNotification("consumed percent is invalid")
        return ServiceTrafficNotificationTarget(
            service_reference=service.public_reference,
            customer_id=service.beneficiary_customer_id,
            stage=stage,
            remaining_bytes=latest.remaining_bytes,
            consumed_percent=latest.consumed_percent,
        )

    @staticmethod
    def _finish(
        event: TransactionalOutboxModel,
        now: datetime,
        *,
        status: str,
        failure_category: str | None,
    ) -> None:
        event.status = status
        event.claimed_at = None
        event.failure_category = failure_category
        event.processed_at = now if status in {"PROCESSED", "FAILED"} else None

    def _deliver(self, event_id: str, now: datetime) -> None:
        with self.factory() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            if event is None or event.event_type != EVENT_TYPE or event.status != "CLAIMED":
                return
            service_id = event.payload.get("service_id")
            account_id = event.payload.get("usage_account_id")
            aggregate_id = event.payload.get("aggregate_id")
            service = db.get(ServiceModel, service_id) if isinstance(service_id, str) else None
            account = (
                db.get(ServiceUsageAccountModel, account_id)
                if isinstance(account_id, str)
                else None
            )
            source = (
                db.get(ServiceUsageAggregateModel, aggregate_id)
                if isinstance(aggregate_id, str)
                else None
            )
            latest = self._latest(db, account.id) if account is not None else None
            try:
                target = self._target(event, service, account, source, latest, now)
                text = _notification_text(target)
                callback_data = _callback_data(target.service_reference)
            except StaleServiceTrafficNotification:
                self._finish(
                    event,
                    now,
                    status="PROCESSED",
                    failure_category="STALE_USAGE_STATE",
                )
                db.commit()
                self._log(event.event_key, event.attempt_count, "SKIPPED")
                return
            except InvalidServiceTrafficNotification:
                self._finish(
                    event,
                    now,
                    status="FAILED",
                    failure_category="INVALID_EVENT_DATA",
                )
                db.commit()
                self._log(event.event_key, event.attempt_count, "FAILED")
                return

            telegram = db.scalar(
                select(TelegramAccountModel).where(
                    TelegramAccountModel.user_id == target.customer_id
                )
            )
            preference = db.scalar(
                select(CustomerNotificationPreferenceModel).where(
                    CustomerNotificationPreferenceModel.customer_id == target.customer_id
                )
            )
            skip_reason: str | None = None
            if not self.bot_enabled:
                skip_reason = "BOT_DISABLED"
            elif telegram is None:
                skip_reason = "UNLINKED"
            elif not telegram.bot_started:
                skip_reason = "BOT_NOT_STARTED"
            elif telegram.blocked_bot:
                skip_reason = "BOT_BLOCKED"
            elif preference is not None and not preference.low_traffic_enabled:
                skip_reason = "PREFERENCE_DISABLED"

            if skip_reason is not None:
                self._finish(
                    event,
                    now,
                    status="PROCESSED",
                    failure_category=skip_reason,
                )
                db.commit()
                self._log(event.event_key, event.attempt_count, "SKIPPED")
                return

            assert telegram is not None
            telegram_user_id = telegram.telegram_user_id
            attempt = event.attempt_count
            event_key = event.event_key
            db.rollback()

        try:
            self.transport.send_callback(
                telegram_user_id,
                text,
                "مدیریت سرویس",
                callback_data,
            )
        except TelegramDeliveryError:
            with self.factory.begin() as db:
                event = db.get(TransactionalOutboxModel, event_id)
                if event is None:
                    return
                if attempt < MAX_ATTEMPTS:
                    event.status = "PENDING"
                    event.available_at = now + retry_delay(attempt)
                    event.claimed_at = None
                    event.failure_category = "TELEGRAM_TEMPORARY"
                    event.processed_at = None
                    final_status = "PENDING"
                else:
                    self._finish(
                        event,
                        now,
                        status="FAILED",
                        failure_category="MAX_ATTEMPTS",
                    )
                    final_status = "FAILED"
            self._log(event_key, attempt, final_status)
            return

        with self.factory.begin() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            if event is None:
                return
            self._finish(event, now, status="PROCESSED", failure_category=None)
        self._log(event_key, attempt, "SENT")

    @staticmethod
    def _log(event_key: str, attempt: int, safe_status: str) -> None:
        logger.info(
            "service_traffic_notification_delivery",
            extra={
                "event_key": event_key,
                "attempt": attempt,
                "safe_status": safe_status,
            },
        )
