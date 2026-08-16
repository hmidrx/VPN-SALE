from __future__ import annotations

import asyncio
import io
import os
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from PIL import Image
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from platform_api.config import Settings
from platform_api.identity.models import (
    AdminModel,
    AuditLogModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.support_attachments_runtime import upload_agent_support_attachment
from platform_api.support_notification_models import support_reply_notification_outbox
from platform_api.support_runtime_models import (
    support_attachments,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_internal import CreateTicketRequest, create_ticket


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _png(seed: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (12, 8), (seed % 255, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def _request(content: bytes, content_type: str) -> Request:
    delivered = False

    async def receive() -> dict[str, object]:
        nonlocal delivered
        if delivered:
            return {"type": "http.request", "body": b"", "more_body": False}
        delivered = True
        return {"type": "http.request", "body": content, "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/support-agent-attachment-test",
            "raw_path": b"/support-agent-attachment-test",
            "query_string": b"",
            "headers": [(b"content-type", content_type.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        },
        receive,
    )


def _identity(db: Session) -> tuple[str, int]:
    user_id = str(uuid4())
    telegram_id = int(uuid4().hex[:12], 16)
    now = datetime.now(UTC)
    db.add(UserModel(id=user_id, status="ACTIVE"))
    db.flush()
    db.add(
        TelegramAccountModel(
            telegram_user_id=telegram_id,
            user_id=user_id,
            first_seen_at=now,
            last_seen_at=now,
            bot_started=True,
            blocked_bot=False,
        )
    )
    db.commit()
    return user_id, telegram_id


def _admin(db: Session) -> AdminModel:
    admin = AdminModel(
        id=str(uuid4()),
        normalized_email=f"agent-image-{uuid4().hex}@example.test",
        password_hash="test-only-not-a-real-password-hash",  # noqa: S106
        status="ACTIVE",
        failed_login_count=0,
    )
    db.add(admin)
    db.commit()
    return admin


def _upload(
    db: Session,
    settings: Settings,
    admin: AdminModel,
    reference: str,
    content: bytes,
    expected_version: int,
    key: str,
) -> dict[str, object]:
    return asyncio.run(
        upload_agent_support_attachment(
            reference,
            _request(content, "image/png"),
            Response(),
            expected_version,
            admin,
            admin,
            db,
            settings,
            key,
        )
    )


def _cleanup(db: Session, user_id: str, admin_id: str, conversation_id: str) -> None:
    db.execute(
        delete(AuditLogModel).where(
            AuditLogModel.target_type == "support_conversation",
            AuditLogModel.target_id == conversation_id,
        )
    )
    db.execute(
        delete(support_reply_notification_outbox).where(
            support_reply_notification_outbox.c.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(support_attachments).where(support_attachments.c.conversation_id == conversation_id)
    )
    db.execute(
        delete(support_status_history).where(
            support_status_history.c.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(support_messages).where(support_messages.c.conversation_id == conversation_id)
    )
    db.execute(delete(support_conversations).where(support_conversations.c.id == conversation_id))
    db.execute(
        delete(support_idempotency_records).where(
            support_idempotency_records.c.scope.like("admin-att:%")
        )
    )
    db.execute(
        delete(support_idempotency_records).where(
            support_idempotency_records.c.scope == f"tg-ticket:{user_id}"
        )
    )
    db.query(TelegramAccountModel).filter(TelegramAccountModel.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id == user_id).delete(synchronize_session=False)
    db.query(AdminModel).filter(AdminModel.id == admin_id).delete(synchronize_session=False)
    db.commit()


def test_agent_image_is_public_idempotent_and_enqueues_delivery() -> None:
    engine = create_engine(_postgres_url())
    user_id = admin_id = conversation_id = ""
    with TemporaryDirectory() as root, Session(engine, expire_on_commit=False) as db:
        settings = Settings(
            environment="test",
            support_private_upload_root=root,
            support_max_attachment_bytes=5 * 1024 * 1024,
            support_image_dimension_limit=8192,
        )
        try:
            user_id, telegram_id = _identity(db)
            admin = _admin(db)
            admin_id = admin.id
            created = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(subject="Agent image", message="Please show me"),
                    Response(),
                    None,
                    db,
                    telegram_id,
                    f"support-agent-image-ticket-{uuid4().hex}",
                ),
            )
            reference = str(created["reference"])
            conversation = (
                db.execute(
                    select(support_conversations).where(
                        support_conversations.c.reference == reference
                    )
                )
                .mappings()
                .one()
            )
            conversation_id = str(conversation["id"])
            original_version = int(conversation["version"])
            source = _png(42)

            uploaded = _upload(
                db,
                settings,
                admin,
                reference,
                source,
                original_version,
                "agent-image-idempotency-1",
            )
            asset_reference = str(uploaded["asset_reference"])
            assert asset_reference.startswith("SAT-")
            assert Path(root, asset_reference).is_file()

            message = (
                db.execute(
                    select(support_messages).where(
                        support_messages.c.conversation_id == conversation_id,
                        support_messages.c.message_type == "AGENT_ATTACHMENT",
                    )
                )
                .mappings()
                .one()
            )
            assert message["sender_type"] == "SUPPORT_AGENT"
            assert message["visibility"] == "PUBLIC"
            assert message["body"] == "📎 تصویر از پشتیبانی ارسال شد."

            attachment = (
                db.execute(
                    select(support_attachments).where(
                        support_attachments.c.asset_reference == asset_reference
                    )
                )
                .mappings()
                .one()
            )
            assert str(attachment["message_id"]) == str(message["id"])
            assert attachment["state"] == "READY"
            assert len(str(attachment["sha256"])) == 64

            event = (
                db.execute(
                    select(support_reply_notification_outbox).where(
                        support_reply_notification_outbox.c.message_id == message["id"]
                    )
                )
                .mappings()
                .one()
            )
            assert event["status"] == "PENDING"
            assert str(event["customer_id"]) == user_id

            version_after_upload = int(
                db.scalar(
                    select(support_conversations.c.version).where(
                        support_conversations.c.id == conversation_id
                    )
                )
                or 0
            )
            assert version_after_upload == original_version + 1

            replay = _upload(
                db,
                settings,
                admin,
                reference,
                source,
                original_version,
                "agent-image-idempotency-1",
            )
            assert replay["asset_reference"] == asset_reference
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_messages)
                    .where(
                        support_messages.c.conversation_id == conversation_id,
                        support_messages.c.message_type == "AGENT_ATTACHMENT",
                    )
                )
                == 1
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_reply_notification_outbox)
                    .where(support_reply_notification_outbox.c.conversation_id == conversation_id)
                )
                == 1
            )

            with pytest.raises(HTTPException) as conflict:
                _upload(
                    db,
                    settings,
                    admin,
                    reference,
                    _png(43),
                    version_after_upload,
                    "agent-image-idempotency-1",
                )
            assert conflict.value.status_code == 409
        finally:
            if user_id and admin_id and conversation_id:
                _cleanup(db, user_id, admin_id, conversation_id)
    engine.dispose()
