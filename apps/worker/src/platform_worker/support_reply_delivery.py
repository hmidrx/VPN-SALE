"""Crash-safe Telegram delivery for durable customer support reply notifications."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.notification_preferences import CustomerNotificationPreferenceModel
from platform_api.support_notification_models import support_reply_notification_outbox
from platform_api.support_runtime_models import support_conversations, support_messages

from .manual_topup_delivery import (
    DeliverySettings,
    TelegramDeliveryError,
    TelegramTransport,
    retry_delay,
)

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 6
BATCH_SIZE = 25
PROCESSING_TIMEOUT = timedelta(minutes=10)


class InvalidSupportNotification(RuntimeError):
    """Persisted identifiers no longer point at a deliverable public support reply."""


def _support_url(origin: str) -> str:
    query = urlencode({"source": "telegram"})
    return f"{origin.rstrip('/')}/support?{query}"


def _notification_text(reference: str) -> str:
    # Deliberately exclude reply bodies and ticket subjects from Telegram. The
    # durable support store remains the source of truth for message content.
    return f"پاسخ جدیدی برای درخواست پشتیبانی {reference} ثبت شد."


def claim(session: Session, now: datetime, batch_size: int = BATCH_SIZE) -> list[str]:
    stale = now - PROCESSING_TIMEOUT
    rows = (
        session.execute(
            select(support_reply_notification_outbox.c.id)
            .where(
                or_(
                    support_reply_notification_outbox.c.status == "PENDING",
                    and_(
                        support_reply_notification_outbox.c.status == "PROCESSING",
                        support_reply_notification_outbox.c.processing_started_at < stale,
                    ),
                ),
                support_reply_notification_outbox.c.available_at <= now,
            )
            .order_by(
                support_reply_notification_outbox.c.available_at,
                support_reply_notification_outbox.c.id,
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    for event_id in rows:
        session.execute(
            update(support_reply_notification_outbox)
            .where(support_reply_notification_outbox.c.id == event_id)
            .values(
                status="PROCESSING",
                processing_started_at=now,
                attempts=support_reply_notification_outbox.c.attempts + 1,
                last_error_category=None,
            )
        )
    session.flush()
    return [str(event_id) for event_id in rows]


class SupportReplyDeliveryWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        transport: TelegramTransport,
        settings: DeliverySettings,
    ) -> None:
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
            event = (
                db.execute(
                    select(support_reply_notification_outbox).where(
                        support_reply_notification_outbox.c.id == event_id
                    )
                )
                .mappings()
                .one_or_none()
            )
            if event is None or event["status"] != "PROCESSING":
                return
            conversation = (
                db.execute(
                    select(support_conversations).where(
                        support_conversations.c.id == event["conversation_id"]
                    )
                )
                .mappings()
                .one_or_none()
            )
            message = (
                db.execute(
                    select(support_messages).where(support_messages.c.id == event["message_id"])
                )
                .mappings()
                .one_or_none()
            )
            try:
                reference = self._validate(event, conversation, message)
            except InvalidSupportNotification:
                self._finish(
                    db,
                    event_id,
                    status="FAILED",
                    error="INVALID_EVENT_DATA",
                    now=now,
                )
                db.commit()
                self._log(str(event["event_reference"]), int(event["attempts"]), "FAILED")
                return

            telegram = db.scalar(
                select(TelegramAccountModel).where(
                    TelegramAccountModel.user_id == event["customer_id"]
                )
            )
            preference = db.scalar(
                select(CustomerNotificationPreferenceModel).where(
                    CustomerNotificationPreferenceModel.customer_id == event["customer_id"]
                )
            )
            skip_reason: str | None = None
            if not self.settings.bot_enabled:
                skip_reason = "BOT_DISABLED"
            elif telegram is None:
                skip_reason = "UNLINKED"
            elif not telegram.bot_started:
                skip_reason = "BOT_NOT_STARTED"
            elif telegram.blocked_bot:
                skip_reason = "BOT_BLOCKED"
            elif preference is not None and not preference.support_reply_enabled:
                skip_reason = "PREFERENCE_DISABLED"

            if skip_reason is not None:
                self._finish(db, event_id, status="SKIPPED", error=skip_reason, now=now)
                db.commit()
                self._log(str(event["event_reference"]), int(event["attempts"]), "SKIPPED")
                return

            assert telegram is not None
            telegram_user_id = telegram.telegram_user_id
            attempt = int(event["attempts"])
            event_reference = str(event["event_reference"])
            text = _notification_text(reference)
            url = _support_url(self.settings.public_app_origin)
            # Never hold a database transaction across the Telegram network call.
            db.rollback()

        try:
            self.transport.send(telegram_user_id, text, url)
        except TelegramDeliveryError:
            with self.factory.begin() as db:
                status = "PENDING" if attempt < MAX_ATTEMPTS else "FAILED"
                error = "TELEGRAM_TEMPORARY" if attempt < MAX_ATTEMPTS else "MAX_ATTEMPTS"
                db.execute(
                    update(support_reply_notification_outbox)
                    .where(support_reply_notification_outbox.c.id == event_id)
                    .values(
                        status=status,
                        processing_started_at=None,
                        last_error_category=error,
                        available_at=now + retry_delay(attempt),
                    )
                )
            self._log(event_reference, attempt, status)
            return

        with self.factory.begin() as db:
            self._finish(db, event_id, status="SENT", error=None, now=now)
        self._log(event_reference, attempt, "SENT")

    @staticmethod
    def _validate(
        event: RowMapping,
        conversation: RowMapping | None,
        message: RowMapping | None,
    ) -> str:
        if conversation is None or message is None:
            raise InvalidSupportNotification
        if (
            str(conversation["id"]) != str(event["conversation_id"])
            or str(conversation["requester_user_id"]) != str(event["customer_id"])
            or conversation["requester_type"] != "CUSTOMER"
            or str(message["id"]) != str(event["message_id"])
            or str(message["conversation_id"]) != str(event["conversation_id"])
            or message["sender_type"] != "SUPPORT_AGENT"
            or message["message_type"] != "AGENT_MESSAGE"
            or message["visibility"] != "PUBLIC"
            or message["redacted_at"] is not None
        ):
            raise InvalidSupportNotification
        return str(conversation["reference"])

    @staticmethod
    def _finish(
        db: Session,
        event_id: str,
        *,
        status: str,
        error: str | None,
        now: datetime,
    ) -> None:
        values: dict[str, object] = {
            "status": status,
            "processing_started_at": None,
            "last_error_category": error,
        }
        if status == "SENT":
            values["sent_at"] = now
        db.execute(
            update(support_reply_notification_outbox)
            .where(support_reply_notification_outbox.c.id == event_id)
            .values(**values)
        )

    @staticmethod
    def _log(event_reference: str, attempt: int, status: str) -> None:
        logger.info(
            "support_reply_delivery",
            extra={
                "event_reference": event_reference,
                "attempt": attempt,
                "safe_status": status,
                "correlation_id": event_reference,
            },
        )
