from __future__ import annotations

import asyncio
import io
import os
from datetime import UTC, datetime, timedelta
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
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.customer_support_attachments import (
    download_customer_support_attachment,
    upload_customer_web_attachment,
)
from platform_api.customer_support_runtime import CreateTicketRequest, create_ticket, ticket_detail
from platform_api.identity.models import CustomerSessionModel, UserModel
from platform_api.support_runtime_models import (
    support_attachments,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _identity(db: Session, settings: Settings) -> tuple[UserModel, CustomerSessionModel, str]:
    now = datetime.now(UTC)
    user = UserModel(id=str(uuid4()), status="ACTIVE", created_at=now, updated_at=now)
    db.add(user)
    db.flush()
    token_service = CustomerAuthService(db, settings).tokens
    csrf = token_service.generate()
    customer_session = CustomerSessionModel(
        id=str(uuid4()),
        user_id=user.id,
        refresh_token_hash=token_service.hash(token_service.generate()),
        session_family_id=str(uuid4()),
        rotation_sequence=0,
        created_at=now,
        last_used_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=4),
        csrf_token_hash=token_service.hash(csrf),
    )
    db.add(customer_session)
    db.commit()
    return user, customer_session, csrf


def _png(seed: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (14, 10), (seed % 255, 80, 120)).save(output, format="PNG")
    return output.getvalue()


def _request(content: bytes, content_type: str = "image/png") -> Request:
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
            "scheme": "https",
            "path": "/customer-support-image-test",
            "raw_path": b"/customer-support-image-test",
            "query_string": b"",
            "headers": [(b"content-type", content_type.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 443),
        },
        receive,
    )


def _upload(
    db: Session,
    settings: Settings,
    customer_session: CustomerSessionModel,
    csrf: str | None,
    reference: str,
    content: bytes,
    key: str,
) -> dict[str, object]:
    return asyncio.run(
        upload_customer_web_attachment(
            reference,
            _request(content),
            Response(),
            customer_session,
            db,
            settings,
            key,
            csrf,
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
            support_idempotency_records.c.scope.like("web-att:%")
        )
    )
    for user_id in user_ids:
        db.execute(
            delete(support_idempotency_records).where(
                support_idempotency_records.c.scope == f"web-ticket:{user_id}"
            )
        )
    db.query(CustomerSessionModel).filter(CustomerSessionModel.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


def test_customer_web_images_are_private_sanitized_owned_and_idempotent() -> None:
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
            owner, owner_session, owner_csrf = _identity(db, settings)
            other, other_session, _ = _identity(db, settings)
            owner_id, other_id = owner.id, other.id
            created = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(subject="تصویر پشتیبانی", message="نیاز به ارسال اسکرین‌شات دارم."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-image-ticket-fixed",
                    owner_csrf,
                ),
            )
            reference = str(created["reference"])
            source = _png(42)

            with pytest.raises(HTTPException) as missing_csrf:
                _upload(
                    db,
                    settings,
                    owner_session,
                    None,
                    reference,
                    source,
                    "web-image-missing-csrf",
                )
            assert missing_csrf.value.status_code == 403

            uploaded = _upload(
                db,
                settings,
                owner_session,
                owner_csrf,
                reference,
                source,
                "web-image-fixed",
            )
            asset_reference = str(uploaded["asset_reference"])
            assert asset_reference.startswith("SAT-")
            stored_path = Path(root, asset_reference)
            assert stored_path.is_file()
            assert stored_path.read_bytes() != b""

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
            attachment = (
                db.execute(
                    select(support_attachments).where(
                        support_attachments.c.asset_reference == asset_reference
                    )
                )
                .mappings()
                .one()
            )
            assert attachment["state"] == "READY"
            assert attachment["content_type"] == "image/png"
            assert len(str(attachment["sha256"])) == 64
            message = (
                db.execute(
                    select(support_messages).where(
                        support_messages.c.id == attachment["message_id"]
                    )
                )
                .mappings()
                .one()
            )
            assert message["sender_type"] == "CUSTOMER"
            assert message["channel"] == "CUSTOMER_WEB"
            assert message["message_type"] == "CUSTOMER_ATTACHMENT"
            assert message["visibility"] == "PUBLIC"

            repeated = _upload(
                db,
                settings,
                owner_session,
                owner_csrf,
                reference,
                source,
                "web-image-fixed",
            )
            assert repeated["asset_reference"] == asset_reference
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_attachments)
                    .where(support_attachments.c.conversation_id == conversation_id)
                )
                == 1
            )

            with pytest.raises(HTTPException) as changed_payload:
                _upload(
                    db,
                    settings,
                    owner_session,
                    owner_csrf,
                    reference,
                    _png(43),
                    "web-image-fixed",
                )
            assert changed_payload.value.status_code == 409

            detail = cast(
                dict[str, Any], ticket_detail(reference, Response(), owner_session, db)
            )
            messages = cast(list[dict[str, Any]], detail["messages"])
            attachment_messages = [item for item in messages if item["message_type"] == "CUSTOMER_ATTACHMENT"]
            assert len(attachment_messages) == 1
            projected = cast(list[dict[str, Any]], attachment_messages[0]["attachments"])
            assert projected[0]["asset_reference"] == asset_reference

            owner_download = download_customer_support_attachment(
                reference, asset_reference, owner_session, db, settings
            )
            assert owner_download.media_type == "image/png"
            assert owner_download.headers["cache-control"] == "private, no-store"

            with pytest.raises(HTTPException) as hidden_from_other:
                download_customer_support_attachment(
                    reference, asset_reference, other_session, db, settings
                )
            assert hidden_from_other.value.status_code == 404
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
