"""Durable Telegram reminders for customer services nearing expiry."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import String, cast, exists, func, literal, or_, select
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.notification_preferences import CustomerNotificationPreferenceModel
from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel

from .manual_topup_delivery import TelegramDeliveryError, retry_delay

logger = logging.getLogger(__name__)

EVENT_TYPE = "service_expiry.telegram_notification.v1"
BATCH_SIZE = 25
MAX_ATTEMPTS = 6
CLAIM_TIMEOUT = timedelta(minutes=10)
_WINDOW_24H = timedelta(hours=24)
_WINDOW_72H = timedelta(hours=72)
_STAGE_24H = "24H"
_STAGE_72H = "72H"
_STAGES = frozenset({_STAGE_24H, _STAGE_72H})
_CALLBACK_PREFIX = "b:v1:svc_open:"
_EVENT_KEY_PREFIX = "tg-svc-exp:"


class InvalidServiceExpiryNotification(RuntimeError):
    """Persisted reminder data cannot produce a customer-safe notification."""


class StaleServiceExpiryNotification(RuntimeError):
    """The service changed after the reminder was queued and must not be sent."""


class ServiceExpiryTelegramTransport(Protocol):
    def send_callback(
        self,
        telegram_user_id: int,
        text: str,
        button_text: str,
        callback_data: str,
    ) -> None: ...


@dataclass(frozen=True)
class ServiceExpiryNotificationTarget:
    service_reference: str
    customer_id: str
    stage: str


def _expiry_token(expires_at: datetime) -> str:
    if expires_at.tzinfo is None:
        raise InvalidServiceExpiryNotification("service expiry must be timezone-aware")
    return expires_at.astimezone(UTC).strftime("%Y%m%d%H%M%S")


def _event_key(service: ServiceModel, stage: str) -> str:
    if stage not in _STAGES or service.expires_at is None:
        raise InvalidServiceExpiryNotification("service reminder key is invalid")
    return f"{_EVENT_KEY_PREFIX}{service.id}:{stage}:{_expiry_token(service.expires_at)}"


def _callback_data(service_reference: str) -> str:
    data = f"{_CALLBACK_PREFIX}{service_reference}"
    if not service_reference or len(data.encode()) > 64:
        raise InvalidServiceExpiryNotification("service callback is invalid")
    return data


def _stage_for(expires_at: datetime, now: datetime) -> str | None:
    if expires_at <= now:
        return None
    remaining = expires_at - now
    if remaining <= _WINDOW_24H:
        return _STAGE_24H
    if remaining <= _WINDOW_72H:
        return _STAGE_72H
    return None


def _notification_text(target: ServiceExpiryNotificationTarget) -> str:
    if target.stage == _STAGE_24H:
        return (
            f"⚠️ کمتر از ۲۴ ساعت تا پایان سرویس {target.service_reference} باقی مانده است.\n"
            "برای جلوگیری از قطع سرویس، در صورت نیاز از بخش مدیریت سرویس تمدید را انجام دهید."
        )
    if target.stage == _STAGE_72H:
        return (
            f"⏳ کمتر از ۳ روز تا پایان سرویس {target.service_reference} باقی مانده است.\n"
            "اگر قصد ادامه استفاده دارید، می‌توانید از همین حالا سرویس را تمدید کنید."
        )
    raise InvalidServiceExpiryNotification("service reminder stage is invalid")


class ServiceExpiryNotificationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        transport: ServiceExpiryTelegramTransport,
        bot_enabled: bool,
    ) -> None:
        self.factory = factory
        self.transport = transport
        self.bot_enabled = bot_enabled

    @staticmethod
    def _enqueue_stage(
        db: Session,
        now: datetime,
        *,
        stage: str,
        lower_bound: timedelta,
        upper_bound: timedelta,
        limit: int,
    ) -> int:
        if limit <= 0:
            return 0
        expiry_token_expression = func.to_char(
            func.timezone("UTC", ServiceModel.expires_at),
            "YYYYMMDDHH24MISS",
        )
        event_key_expression = (
            literal(_EVENT_KEY_PREFIX)
            + cast(ServiceModel.id, String)
            + literal(f":{stage}:")
            + expiry_token_expression
        )
        already_enqueued = exists().where(
            TransactionalOutboxModel.event_key == event_key_expression
        )
        services = list(
            db.scalars(
                select(ServiceModel)
                .where(
                    ServiceModel.lifecycle == "ACTIVE",
                    ServiceModel.expires_at.is_not(None),
                    ServiceModel.expires_at > now + lower_bound,
                    ServiceModel.expires_at <= now + upper_bound,
                    ~already_enqueued,
                )
                .order_by(ServiceModel.expires_at, ServiceModel.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for service in services:
            if service.expires_at is None:
                continue
            db.add(
                TransactionalOutboxModel(
                    event_key=_event_key(service, stage),
                    event_type=EVENT_TYPE,
                    status="PENDING",
                    payload={
                        "service_id": service.id,
                        "stage": stage,
                        "expiry_token": _expiry_token(service.expires_at),
                    },
                    attempt_count=0,
                    available_at=now,
                )
            )
        db.flush()
        return len(services)

    @classmethod
    def _enqueue(cls, db: Session, now: datetime) -> int:
        urgent = cls._enqueue_stage(
            db,
            now,
            stage=_STAGE_24H,
            lower_bound=timedelta(0),
            upper_bound=_WINDOW_24H,
            limit=BATCH_SIZE,
        )
        if urgent >= BATCH_SIZE:
            return urgent
        upcoming = cls._enqueue_stage(
            db,
            now,
            stage=_STAGE_72H,
            lower_bound=_WINDOW_24H,
            upper_bound=_WINDOW_72H,
            limit=BATCH_SIZE - urgent,
        )
        return urgent + upcoming

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
    def _target(
        event: TransactionalOutboxModel,
        service: ServiceModel | None,
        now: datetime,
    ) -> ServiceExpiryNotificationTarget:
        service_id = event.payload.get("service_id")
        stage = event.payload.get("stage")
        expiry_token = event.payload.get("expiry_token")
        if (
            service is None
            or not isinstance(service_id, str)
            or service.id != service_id
            or not isinstance(stage, str)
            or stage not in _STAGES
            or not isinstance(expiry_token, str)
            or not expiry_token
        ):
            raise InvalidServiceExpiryNotification("service reminder scope is invalid")
        if (
            service.lifecycle != "ACTIVE"
            or service.expires_at is None
            or _expiry_token(service.expires_at) != expiry_token
        ):
            raise StaleServiceExpiryNotification("service reminder is stale")
        current_stage = _stage_for(service.expires_at, now)
        if current_stage is None:
            raise StaleServiceExpiryNotification("service reminder is no longer due")
        if stage == _STAGE_72H and current_stage != _STAGE_72H:
            raise StaleServiceExpiryNotification("72-hour reminder was superseded")
        return ServiceExpiryNotificationTarget(
            service_reference=service.public_reference,
            customer_id=service.beneficiary_customer_id,
            stage=stage,
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
            service = db.get(ServiceModel, service_id) if isinstance(service_id, str) else None
            try:
                target = self._target(event, service, now)
                text = _notification_text(target)
                callback_data = _callback_data(target.service_reference)
            except StaleServiceExpiryNotification:
                self._finish(
                    event,
                    now,
                    status="PROCESSED",
                    failure_category="STALE_SERVICE_STATE",
                )
                db.commit()
                self._log(event.event_key, event.attempt_count, "SKIPPED")
                return
            except InvalidServiceExpiryNotification:
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
            elif preference is not None and not preference.service_expiry_enabled:
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
            "service_expiry_notification_delivery",
            extra={
                "event_key": event_key,
                "attempt": attempt,
                "safe_status": safe_status,
            },
        )
