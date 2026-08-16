from __future__ import annotations

import asyncio
import io
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from PIL import Image, PngImagePlugin
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session
from starlette.requests import Request

from platform_api.config import Settings
from platform_api.identity.models import TelegramAccountModel, UserModel
from platform_api.support_attachments_runtime import upload_customer_support_attachment
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


def _png(seed: int, *, with_metadata: bool = True) -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (12, 8), (seed % 255, 40, 80))
    metadata = PngImagePlugin.PngInfo()
    if with_metadata:
        metadata.add_text("Comment", "sensitive-client-metadata")
    image.save(output, format="PNG", pnginfo=metadata)
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
            "path": "/support-attachment-test",
            "raw_path": b"/support-attachment-test",
            "query_string": b"",
            "headers": [(b"content-type", content_type.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        },
        receive,
    )


def _upload(
    db: Session,
    settings: Settings,
    telegram_id: int,
    reference: str,
    content: bytes,
    key: str,
    content_type: str = "image/png",
) -> dict[str, object]:
    return asyncio.run(
        upload_customer_support_attachment(
            reference,
            _request(content, content_type),
            Response(),
            None,
            db,
            telegram_id,
            settings,
            key,
        )
    )


def _cleanup(db: Session, user_ids: list[str]) -> None:
    conversation_ids = list(
        db.scalars(
            select(support_conversations.c.id).where(
                support_conversations.c.requester_user_id.in_(user_ids)
            )
        ).all()
    )
    if conversation_ids:
        db.execute(
            delete(support_attachments).where(
                support_attachments.c.conversation_id.in_(conversation_ids)
            )
        )
        db.execute(
            delete(support_status_history).where(
                support_status_history.c.conversation_id.in_(conversation_ids)
            )
        )
        db.execute(
            delete(support_messages).where(support_messages.c.conversation_id.in_(conversation_ids))
        )
        db.execute(
            delete(support_conversations).where(support_conversations.c.id.in_(conversation_ids))
        )
    db.execute(
        delete(support_idempotency_records).where(
            support_idempotency_records.c.scope.like("tg-att:%")
        )
    )
    for user_id in user_ids:
        db.execute(
            delete(support_idempotency_records).where(
                support_idempotency_records.c.scope == f"tg-ticket:{user_id}"
            )
        )
    db.query(TelegramAccountModel).filter(TelegramAccountModel.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


def test_support_image_attachment_is_private_sanitized_owned_and_idempotent() -> None:
    engine = create_engine(_postgres_url())
    owner_id = other_id = ""
    with TemporaryDirectory() as root, Session(engine, expire_on_commit=False) as db:
        settings = Settings(
            environment="test",
            support_private_upload_root=root,
            support_max_attachment_bytes=5 * 1024 * 1024,
            support_image_dimension_limit=8192,
        )
        try:
            owner_id, owner_telegram = _identity(db)
            other_id, other_telegram = _identity(db)
            created = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(subject="Attachment test", message="Initial body"),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "support-attachment-create",
                ),
            )
            reference = str(created["reference"])
            conversation_id = str(
                db.scalar(
                    select(support_conversations.c.id).where(
                        support_conversations.c.reference == reference
                    )
                )
            )
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(status="WAITING_FOR_CUSTOMER")
            )
            db.commit()

            source = _png(20)
            uploaded = _upload(
                db,
                settings,
                owner_telegram,
                reference,
                source,
                "support-attachment-upload-1",
            )
            asset_reference = str(uploaded["asset_reference"])
            assert asset_reference.startswith("SAT-")
            assert uploaded["message_sequence"] == 2
            assert uploaded["content_type"] == "image/png"

            stored_path = Path(root) / asset_reference
            assert stored_path.is_file()
            assert stat.S_IMODE(stored_path.stat().st_mode) == 0o600
            stored_bytes = stored_path.read_bytes()
            assert b"sensitive-client-metadata" not in stored_bytes
            with Image.open(io.BytesIO(stored_bytes)) as sanitized:
                sanitized.verify()

            row = db.execute(
                select(
                    support_attachments.c.message_id,
                    support_attachments.c.sha256,
                    support_attachments.c.state,
                ).where(support_attachments.c.asset_reference == asset_reference)
            ).one()
            assert row[0] is not None
            assert len(str(row[1])) == 64
            assert row[2] == "READY"
            assert (
                db.scalar(
                    select(support_conversations.c.status).where(
                        support_conversations.c.id == conversation_id
                    )
                )
                == "WAITING_FOR_SUPPORT"
            )

            replay = _upload(
                db,
                settings,
                owner_telegram,
                reference,
                source,
                "support-attachment-upload-1",
            )
            assert replay["asset_reference"] == asset_reference
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_attachments)
                    .where(support_attachments.c.conversation_id == conversation_id)
                )
                == 1
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_messages)
                    .where(
                        support_messages.c.conversation_id == conversation_id,
                        support_messages.c.message_type == "CUSTOMER_ATTACHMENT",
                    )
                )
                == 1
            )

            with pytest.raises(HTTPException) as conflict:
                _upload(
                    db,
                    settings,
                    owner_telegram,
                    reference,
                    _png(21),
                    "support-attachment-upload-1",
                )
            assert conflict.value.status_code == 409
            assert conflict.value.detail == "idempotency_conflict"

            with pytest.raises(HTTPException) as ownership:
                _upload(
                    db,
                    settings,
                    other_telegram,
                    reference,
                    source,
                    "support-attachment-other-user",
                )
            assert ownership.value.status_code == 404

            with pytest.raises(HTTPException) as invalid_type:
                _upload(
                    db,
                    settings,
                    owner_telegram,
                    reference,
                    source,
                    "support-attachment-invalid-type",
                    "application/octet-stream",
                )
            assert invalid_type.value.status_code == 415
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
