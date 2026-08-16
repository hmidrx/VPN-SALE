"""Crash-safe Telegram delivery for durable customer support reply notifications."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlencode

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel
from platform_api.notification_preferences import CustomerNotificationPreferenceModel
from platform_api.support_attachment_storage import (
    ALLOWED_SUPPORT_IMAGE_TYPES,
    MAX_SUPPORT_ATTACHMENT_BYTES,
    InvalidSupportAttachment,
    LocalPrivateSupportAttachmentStorage,
)
from platform_api.support_notification_models import support_reply_notification_outbox
from platform_api.support_runtime_models import (
    support_attachments,
    support_conversations,
    support_messages,
)

from .manual_topup_delivery import TelegramDeliveryError, retry_delay

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 6
BATCH_SIZE = 25
PROCESSING_TIMEOUT = timedelta(minutes=10)


class InvalidSupportNotification(RuntimeError):
    """Persisted identifiers no longer point at a deliverable public support reply."""


class SupportTelegramTransport(Protocol):
    def send(self, telegram_user_id: int, text: str, mini_app_url: str) -> None: ...

    def send_photo(
        self,
        telegram_user_id: int,
        photo: bytes,
        filename: str,
        media_type: str,
        caption: str,
        mini_app_url: str,
    ) -> None: ...


@dataclass(frozen=True)
class SupportDeliverySettings:
    bot_enabled: bool
    public_app_origin: str
    support_private_upload_root: str = "/var/lib/vpnsale/private/support"


@dataclass(frozen=True)
class AgentAttachmentPayload:
    asset_reference: str
    filename: str
    content_type: str
    byte_size: int
    sha256: str


def _support_url(origin: str) -> str:
    query = urlencode({"source": "telegram"})
    return f"{origin.rstrip('/')}/support?{query}"


def _notification_text(reference: str) -> str:
    # Deliberately exclude reply bodies and ticket subjects from Telegram. The
    # durable support store remains the source of truth for message content.
    return f"پاسخ جدیدی برای درخواست پشتیبانی {reference} ثبت شد."


def _attachment_caption(reference: str) -> str:
    return f"تصویر جدیدی برای درخواست پشتیبانی {reference} ارسال شد."


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
        transport: SupportTelegramTransport,
        settings: SupportDeliverySettings,
    ) -> None:
        self.factory = factory
        self.transport = transport
        self.settings = settings
        self.storage = LocalPrivateSupportAttachmentStorage(
            Path(settings.support_private_upload_root),
            maximum_bytes=MAX_SUPPORT_ATTACHMENT_BYTES,
            prepare_root=False,
        )

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
            attachment = None
            if message is not None and message["message_type"] == "AGENT_ATTACHMENT":
                attachment = (
                    db.execute(
                        select(support_attachments).where(
                            support_attachments.c.message_id == event["message_id"]
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            try:
                reference, attachment_payload = self._validate(
                    event, conversation, message, attachment
                )
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
            url = _support_url(self.settings.public_app_origin)
            # Never hold a database transaction across filesystem verification
            # or the Telegram network call.
            db.rollback()

        photo: bytes | None = None
        if attachment_payload is not None:
            try:
                photo = self._read_attachment(attachment_payload)
            except InvalidSupportNotification:
                with self.factory.begin() as db:
                    self._finish(
                        db,
                        event_id,
                        status="FAILED",
                        error="INVALID_EVENT_DATA",
                        now=now,
                    )
                self._log(event_reference, attempt, "FAILED")
                return

        try:
            if attachment_payload is None:
                self.transport.send(telegram_user_id, _notification_text(reference), url)
            else:
                assert photo is not None
                self.transport.send_photo(
                    telegram_user_id,
                    photo,
                    attachment_payload.filename,
                    attachment_payload.content_type,
                    _attachment_caption(reference),
                    url,
                )
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

    def _read_attachment(self, attachment: AgentAttachmentPayload) -> bytes:
        try:
            with self.storage.open(attachment.asset_reference) as source:
                payload = source.read(MAX_SUPPORT_ATTACHMENT_BYTES + 1)
        except (OSError, InvalidSupportAttachment) as exc:
            raise InvalidSupportNotification from exc
        if (
            not payload
            or len(payload) > MAX_SUPPORT_ATTACHMENT_BYTES
            or len(payload) != attachment.byte_size
            or hashlib.sha256(payload).hexdigest() != attachment.sha256
        ):
            raise InvalidSupportNotification
        return payload

    @staticmethod
    def _validate(
        event: RowMapping,
        conversation: RowMapping | None,
        message: RowMapping | None,
        attachment: RowMapping | None,
    ) -> tuple[str, AgentAttachmentPayload | None]:
        if conversation is None or message is None:
            raise InvalidSupportNotification
        message_type = str(message["message_type"])
        if (
            str(conversation["id"]) != str(event["conversation_id"])
            or str(conversation["requester_user_id"]) != str(event["customer_id"])
            or conversation["requester_type"] != "CUSTOMER"
            or str(message["id"]) != str(event["message_id"])
            or str(message["conversation_id"]) != str(event["conversation_id"])
            or message["sender_type"] != "SUPPORT_AGENT"
            or message_type not in {"AGENT_MESSAGE", "AGENT_ATTACHMENT"}
            or message["visibility"] != "PUBLIC"
            or message["redacted_at"] is not None
        ):
            raise InvalidSupportNotification
        if message_type == "AGENT_MESSAGE":
            if attachment is not None:
                raise InvalidSupportNotification
            return str(conversation["reference"]), None
        if attachment is None:
            raise InvalidSupportNotification
        content_type = str(attachment["content_type"])
        byte_size = int(attachment["byte_size"])
        digest = str(attachment["sha256"])
        if (
            str(attachment["conversation_id"]) != str(event["conversation_id"])
            or str(attachment["message_id"]) != str(event["message_id"])
            or attachment["state"] != "READY"
            or content_type not in ALLOWED_SUPPORT_IMAGE_TYPES
            or byte_size <= 0
            or byte_size > MAX_SUPPORT_ATTACHMENT_BYTES
            or len(digest) != 64
        ):
            raise InvalidSupportNotification
        return str(conversation["reference"]), AgentAttachmentPayload(
            asset_reference=str(attachment["asset_reference"]),
            filename=str(attachment["normalized_filename"]),
            content_type=content_type,
            byte_size=byte_size,
            sha256=digest,
        )

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
