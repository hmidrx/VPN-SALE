from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.customer_support_runtime import (
    CreateTicketRequest,
    ReplyTicketRequest,
    create_ticket,
    reply_ticket,
    ticket_detail,
)
from platform_api.identity.models import CustomerSessionModel, UserModel
from platform_api.support_runtime_models import (
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


def _identity(
    db: Session, settings: Settings
) -> tuple[UserModel, CustomerSessionModel, str]:
    now = datetime.now(UTC)
    user = UserModel(id=str(uuid4()), status="ACTIVE", created_at=now, updated_at=now)
    db.add(user)
    db.flush()

    token_service = CustomerAuthService(db, settings).tokens
    csrf = token_service.generate()
    session = CustomerSessionModel(
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
    db.add(session)
    db.commit()
    return user, session, csrf


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
            delete(support_status_history).where(
                support_status_history.c.conversation_id.in_(conversation_ids)
            )
        )
        db.execute(
            delete(support_messages).where(
                support_messages.c.conversation_id.in_(conversation_ids)
            )
        )
        db.execute(
            delete(support_conversations).where(support_conversations.c.id.in_(conversation_ids))
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


def test_customer_web_support_enforces_csrf_ownership_and_idempotency() -> None:
    engine = create_engine(_postgres_url())
    settings = Settings(environment="test")
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner, owner_session, owner_csrf = _identity(db, settings)
            other, other_session, _ = _identity(db, settings)
            owner_id, other_id = owner.id, other.id

            with pytest.raises(HTTPException) as missing_csrf:
                create_ticket(
                    CreateTicketRequest(subject="پشتیبانی وب", message="این درخواست نباید ثبت شود."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-csrf-check",
                    None,
                )
            assert missing_csrf.value.status_code == 403
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_conversations)
                    .where(support_conversations.c.requester_user_id == owner.id)
                )
                == 0
            )

            first = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(
                        subject="پشتیبانی وب",
                        message="می‌خواهم بدون تلگرام از سایت پیگیری کنم.",
                    ),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-create-fixed",
                    owner_csrf,
                ),
            )
            repeated = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(
                        subject="پشتیبانی وب",
                        message="می‌خواهم بدون تلگرام از سایت پیگیری کنم.",
                    ),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-create-fixed",
                    owner_csrf,
                ),
            )
            reference = str(first["reference"])
            assert repeated["reference"] == reference
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
            assert conversation["requester_user_id"] == owner.id
            assert conversation["channel"] == "CUSTOMER_WEB"
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_messages)
                    .where(support_messages.c.conversation_id == conversation_id)
                )
                == 1
            )

            with pytest.raises(HTTPException) as changed_create:
                create_ticket(
                    CreateTicketRequest(
                        subject="موضوع متفاوت",
                        message="payload متفاوت با همان کلید",
                    ),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-create-fixed",
                    owner_csrf,
                )
            assert changed_create.value.status_code == 409

            with pytest.raises(HTTPException) as hidden_from_other:
                ticket_detail(reference, Response(), other_session, db)
            assert hidden_from_other.value.status_code == 404

            replied = cast(
                dict[str, Any],
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="اطلاعات تکمیلی از سایت ارسال شد."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-reply-fixed",
                    owner_csrf,
                ),
            )
            repeated_reply = cast(
                dict[str, Any],
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="اطلاعات تکمیلی از سایت ارسال شد."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-reply-fixed",
                    owner_csrf,
                ),
            )
            assert replied["reference"] == repeated_reply["reference"]
            assert len(cast(list[dict[str, Any]], repeated_reply["messages"])) == 2
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_messages)
                    .where(support_messages.c.conversation_id == conversation_id)
                )
                == 2
            )

            with pytest.raises(HTTPException) as changed_reply:
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="پاسخ متفاوت با همان کلید"),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-support-reply-fixed",
                    owner_csrf,
                )
            assert changed_reply.value.status_code == 409
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
