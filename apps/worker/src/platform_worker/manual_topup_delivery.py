"""Crash-safe post-commit delivery for manual top-up notification events."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.manual_topup_models import (
    ManualTopupMessageModel,
    ManualTopupNotificationOutboxModel,
    ManualTopupRequestModel,
)
from platform_api.notification_preferences import CustomerNotificationPreferenceModel

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 6
BATCH_SIZE = 25
PROCESSING_TIMEOUT = timedelta(minutes=10)


class TelegramDeliveryError(RuntimeError):
    """A categorized transport failure safe for retry handling."""


class InvalidNotificationData(RuntimeError):
    """Persisted event data cannot produce a customer-safe notification."""


class TelegramTransport(Protocol):
    def send(self, telegram_user_id: int, text: str, mini_app_url: str) -> None: ...


@dataclass(frozen=True)
class DeliverySettings:
    bot_enabled: bool
    public_app_origin: str


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * (2 ** max(0, attempt - 1))))


def _fa_number(value: int) -> str:
    grouped = f"{value:,}"
    return grouped.translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))


def _text(
    db: Session, event: ManualTopupNotificationOutboxModel, request: ManualTopupRequestModel
) -> str:
    if event.event_type == "RECEIPT_SUBMITTED":
        return "فیش شما دریافت شد و در انتظار بررسی است."
    if event.event_type == "APPROVED":
        if request.total_credited_amount_rial is None:
            raise InvalidNotificationData("approved notification is missing its settled total")
        return (
            f"فیش شما تأیید شد و {_fa_number(request.total_credited_amount_rial // 10)} تومان "
            "به کیف پول شما اضافه شد."
        )
    if event.event_type in {"NEEDS_RESUBMISSION", "REJECTED"}:
        return (
            "فیش شما نیاز به ارسال مجدد دارد: "
            if event.event_type == "NEEDS_RESUBMISSION"
            else "فیش شما تأیید نشد: "
        ) + (request.customer_message or "برای جزئیات، درخواست را مشاهده کنید.")
    message = db.scalar(
        select(ManualTopupMessageModel)
        .where(
            ManualTopupMessageModel.request_id == request.id,
            ManualTopupMessageModel.visibility == "CUSTOMER",
        )
        .order_by(ManualTopupMessageModel.created_at.desc())
    )
    return message.body if message else "پیام جدیدی درباره درخواست کارت‌به‌کارت شما ثبت شد."


def claim(session: Session, now: datetime, batch_size: int = BATCH_SIZE) -> list[str]:
    stale = now - PROCESSING_TIMEOUT
    rows = session.scalars(
        select(ManualTopupNotificationOutboxModel)
        .where(
            or_(
                ManualTopupNotificationOutboxModel.status == "PENDING",
                (ManualTopupNotificationOutboxModel.status == "PROCESSING")
                & (ManualTopupNotificationOutboxModel.processing_started_at < stale),
            ),
            ManualTopupNotificationOutboxModel.available_at <= now,
        )
        .order_by(
            ManualTopupNotificationOutboxModel.available_at, ManualTopupNotificationOutboxModel.id
        )
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        row.status = "PROCESSING"
        row.processing_started_at = now
        row.attempts += 1
        row.last_error_category = None
    session.flush()
    return [row.id for row in rows]


class ManualTopupDeliveryWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        transport: TelegramTransport,
        settings: DeliverySettings,
    ):
        self.factory = factory
        self.transport = transport
        self.settings = settings

    def run_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        with self.factory.begin() as db:
            ids = claim(db, now)
        for event_id in ids:
            self._deliver(event_id, now)
        return len(ids)

    def _deliver(self, event_id: str, now: datetime) -> None:
        with self.factory() as db:
            event = db.get(ManualTopupNotificationOutboxModel, event_id)
            request = db.get(ManualTopupRequestModel, event.request_id) if event else None
            if event is None or request is None or event.status != "PROCESSING":
                return
            telegram = db.scalar(
                select(TelegramAccountModel).where(
                    TelegramAccountModel.user_id == event.customer_id
                )
            )
            preference = db.scalar(
                select(CustomerNotificationPreferenceModel).where(
                    CustomerNotificationPreferenceModel.customer_id == event.customer_id
                )
            )
            if (
                not self.settings.bot_enabled
                or telegram is None
                or (preference is not None and not preference.payment_enabled)
            ):
                event.status = "SKIPPED"
                event.last_error_category = (
                    "BOT_DISABLED"
                    if not self.settings.bot_enabled
                    else "UNLINKED"
                    if telegram is None
                    else "PREFERENCE_DISABLED"
                )
                event.processing_started_at = None
                db.commit()
                self._log(event, "SKIPPED")
                return
            try:
                text = _text(db, event, request)
            except InvalidNotificationData:
                event.status = "FAILED"
                event.last_error_category = "INVALID_EVENT_DATA"
                event.processing_started_at = None
                db.commit()
                self._log(event, "FAILED")
                return
            url = (
                f"{self.settings.public_app_origin.rstrip('/')}/wallet/top-up/manual/"
                f"{request.reference}?{urlencode({'source': 'telegram'})}"
            )
            telegram_id = telegram.telegram_user_id
            attempt = event.attempts
            db.rollback()
        try:
            self.transport.send(telegram_id, text, url)
        except TelegramDeliveryError:
            with self.factory.begin() as db:
                event = db.get(ManualTopupNotificationOutboxModel, event_id)
                if event is None:
                    return
                event.processing_started_at = None
                event.last_error_category = (
                    "TELEGRAM_TEMPORARY" if attempt < MAX_ATTEMPTS else "MAX_ATTEMPTS"
                )
                event.status = "PENDING" if attempt < MAX_ATTEMPTS else "FAILED"
                event.available_at = now + retry_delay(attempt)
                self._log(event, event.status)
            return
        with self.factory.begin() as db:
            event = db.get(ManualTopupNotificationOutboxModel, event_id)
            if event is None:
                return
            event.status = "SENT"
            event.sent_at = now
            event.processing_started_at = None
            event.last_error_category = None
            self._log(event, "SENT")

    @staticmethod
    def _log(event: ManualTopupNotificationOutboxModel, status: str) -> None:
        logger.info(
            "manual_topup_delivery",
            extra={
                "event_reference": event.event_reference,
                "event_type": event.event_type,
                "attempt": event.attempts,
                "safe_status": status,
                "correlation_id": event.event_reference,
            },
        )
