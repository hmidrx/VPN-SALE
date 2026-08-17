"""Durable Telegram notifications for paid service-operation terminal outcomes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.notification_preferences import CustomerNotificationPreferenceModel
from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel

from .manual_topup_delivery import TelegramDeliveryError, retry_delay

logger = logging.getLogger(__name__)

EVENT_TYPE = "service_operation.telegram_notification.v1"
BATCH_SIZE = 25
MAX_ATTEMPTS = 6
CLAIM_TIMEOUT = timedelta(minutes=10)
_SUPPORTED_OPERATIONS = frozenset({"RENEW", "ADD_TRAFFIC"})
_TERMINAL_STATUSES = frozenset(
    {
        "SUCCEEDED",
        "PARTIALLY_APPLIED",
        "FAILED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "COMPENSATED",
        "MANUAL_REVIEW",
        "CANCELLED",
        "EXPIRED",
    }
)
_PAYMENT_STATUSES = frozenset({"CAPTURED", "REFUNDED"})
_CALLBACK_PREFIX = "b:v1:svst:"


class InvalidServiceOperationNotification(RuntimeError):
    """Persisted data cannot produce a customer-safe operation notification."""


class ServiceOperationTelegramTransport(Protocol):
    def send_callback(
        self,
        telegram_user_id: int,
        text: str,
        button_text: str,
        callback_data: str,
    ) -> None: ...


@dataclass(frozen=True)
class ServiceOperationNotificationTarget:
    operation_reference: str
    service_reference: str
    operation_type: str
    status: str
    customer_id: str


def _event_key(operation: ServiceOperationModel) -> str:
    return f"tg-svc-op:{operation.id}:{operation.status}"


def _callback_data(operation_reference: str) -> str:
    data = f"{_CALLBACK_PREFIX}{operation_reference}"
    if not operation_reference or len(data.encode()) > 64:
        raise InvalidServiceOperationNotification("operation callback is invalid")
    return data


def _notification_text(target: ServiceOperationNotificationTarget) -> str:
    label = "تمدید سرویس" if target.operation_type == "RENEW" else "افزایش حجم سرویس"
    reference = target.service_reference
    if target.status == "SUCCEEDED":
        return f"✅ {label} با موفقیت انجام شد.\nسرویس: {reference}"
    if target.status == "PARTIALLY_APPLIED":
        return (
            f"⚠️ {label} برای سرویس {reference} به‌صورت کامل تأیید نشد و نیاز به بررسی دارد.\n"
            "تا مشخص‌شدن نتیجه نهایی، دوباره پرداخت نکنید."
        )
    if target.status == "UNCERTAIN":
        return (
            f"⚠️ نتیجه نهایی {label} برای سرویس {reference} هنوز قطعی نیست.\n"
            "درخواست در حال بررسی است؛ دوباره پرداخت نکنید."
        )
    if target.status == "COMPENSATION_REQUIRED":
        return (
            f"⚠️ {label} برای سرویس {reference} نیاز به بررسی و جبران دارد.\n"
            "برای جلوگیری از برداشت تکراری، دوباره پرداخت نکنید."
        )
    if target.status == "COMPENSATED":
        return (
            f"ℹ️ وضعیت {label} برای سرویس {reference} جبران شد.\n"
            "پیش از اقدام دوباره، وضعیت سرویس و کیف پول را بررسی کنید."
        )
    if target.status == "MANUAL_REVIEW":
        return (
            f"🕓 {label} برای سرویس {reference} وارد بررسی دستی شد.\n"
            "تا پایان بررسی، دوباره پرداخت نکنید."
        )
    if target.status == "FAILED":
        return (
            f"❌ {label} برای سرویس {reference} با خطا متوقف شد.\n"
            "چون پرداخت قبلاً ثبت شده، دوباره پرداخت نکنید و وضعیت را پیگیری کنید."
        )
    if target.status == "CANCELLED":
        return (
            f"ℹ️ {label} برای سرویس {reference} لغو شد.\n"
            "پیش از ثبت درخواست جدید، وضعیت مالی را بررسی کنید."
        )
    if target.status == "EXPIRED":
        return (
            f"⌛ مهلت {label} برای سرویس {reference} پایان یافته است.\n"
            "پیش از اقدام دوباره، وضعیت عملیات و کیف پول را بررسی کنید."
        )
    raise InvalidServiceOperationNotification("operation status is not notifiable")


class ServiceOperationNotificationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        transport: ServiceOperationTelegramTransport,
        bot_enabled: bool,
    ) -> None:
        self.factory = factory
        self.transport = transport
        self.bot_enabled = bot_enabled

    @staticmethod
    def _enqueue(db: Session, now: datetime) -> int:
        operations = list(
            db.scalars(
                select(ServiceOperationModel)
                .join(
                    ServiceOperationPaymentModel,
                    ServiceOperationPaymentModel.operation_id == ServiceOperationModel.id,
                )
                .join(ServiceModel, ServiceModel.id == ServiceOperationModel.service_id)
                .where(
                    ServiceOperationModel.operation_type.in_(_SUPPORTED_OPERATIONS),
                    ServiceOperationModel.status.in_(_TERMINAL_STATUSES),
                    ServiceOperationModel.requester_type == "CUSTOMER",
                    ServiceOperationPaymentModel.status.in_(_PAYMENT_STATUSES),
                    ServiceOperationPaymentModel.customer_id == ServiceOperationModel.requester_id,
                    ServiceModel.beneficiary_customer_id == ServiceOperationModel.requester_id,
                )
                .order_by(ServiceOperationModel.updated_at, ServiceOperationModel.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )
        added = 0
        for operation in operations:
            key = _event_key(operation)
            existing = db.scalar(
                select(TransactionalOutboxModel.id).where(
                    TransactionalOutboxModel.event_key == key
                )
            )
            if existing is not None:
                continue
            db.add(
                TransactionalOutboxModel(
                    event_key=key,
                    event_type=EVENT_TYPE,
                    status="PENDING",
                    payload={
                        "operation_id": operation.id,
                        "terminal_status": operation.status,
                    },
                    attempt_count=0,
                    available_at=now,
                )
            )
            added += 1
        db.flush()
        return added

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
        operation: ServiceOperationModel | None,
        service: ServiceModel | None,
        payment: ServiceOperationPaymentModel | None,
    ) -> ServiceOperationNotificationTarget:
        operation_id = event.payload.get("operation_id")
        terminal_status = event.payload.get("terminal_status")
        if (
            operation is None
            or service is None
            or payment is None
            or not isinstance(operation_id, str)
            or operation.id != operation_id
            or not isinstance(terminal_status, str)
            or operation.status != terminal_status
            or operation.status not in _TERMINAL_STATUSES
            or operation.operation_type not in _SUPPORTED_OPERATIONS
            or operation.requester_type != "CUSTOMER"
            or payment.operation_id != operation.id
            or payment.status not in _PAYMENT_STATUSES
            or payment.customer_id != operation.requester_id
            or service.id != operation.service_id
            or service.beneficiary_customer_id != operation.requester_id
        ):
            raise InvalidServiceOperationNotification("operation notification scope is invalid")
        return ServiceOperationNotificationTarget(
            operation_reference=operation.id,
            service_reference=service.public_reference,
            operation_type=operation.operation_type,
            status=operation.status,
            customer_id=operation.requester_id,
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
            operation_id = event.payload.get("operation_id")
            operation = (
                db.get(ServiceOperationModel, operation_id)
                if isinstance(operation_id, str)
                else None
            )
            service = db.get(ServiceModel, operation.service_id) if operation is not None else None
            payment = db.scalar(
                select(ServiceOperationPaymentModel).where(
                    ServiceOperationPaymentModel.operation_id == operation.id
                )
            ) if operation is not None else None
            try:
                target = self._target(event, operation, service, payment)
                text = _notification_text(target)
                callback_data = _callback_data(target.operation_reference)
            except InvalidServiceOperationNotification:
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
                select(TelegramAccountModel).where(TelegramAccountModel.user_id == target.customer_id)
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
            elif preference is not None and not preference.payment_enabled:
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
                "پیگیری وضعیت",
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
            "service_operation_notification_delivery",
            extra={
                "event_key": event_key,
                "attempt": attempt,
                "safe_status": safe_status,
            },
        )
