from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, func, select, update
from sqlalchemy.orm import Session

from platform_api.identity.models import TelegramAccountModel, UserModel
from platform_api.support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_internal import (
    CreateTicketRequest,
    ReplyTicketRequest,
    create_ticket,
    reply_ticket,
    ticket_detail,
)


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
            delete(support_messages).where(support_messages.c.conversation_id.in_(conversation_ids))
        )
        db.execute(
            delete(support_conversations).where(support_conversations.c.id.in_(conversation_ids))
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


def test_native_support_is_idempotent_owned_and_hides_internal_notes() -> None:
    engine = create_engine(_postgres_url())
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner_id, owner_telegram = _identity(db)
            other_id, other_telegram = _identity(db)
            first = create_ticket(
                CreateTicketRequest(subject="مشکل اتصال", message="سرویس من وصل نمی‌شود."),
                Response(),
                None,
                db,
                owner_telegram,
                "tg-support-create-fixed",
            )
            repeated = create_ticket(
                CreateTicketRequest(subject="مشکل اتصال", message="سرویس من وصل نمی‌شود."),
                Response(),
                None,
                db,
                owner_telegram,
                "tg-support-create-fixed",
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
            snapshot = conversation["sla_policy_snapshot"]
            assert isinstance(snapshot, dict)
            assert snapshot["code"] == "telegram_normal"
            assert snapshot["first_response_minutes"] == 240
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_conversations)
                    .where(support_conversations.c.reference == reference)
                )
                == 1
            )
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_messages)
                    .where(support_messages.c.conversation_id == conversation_id)
                )
                == 1
            )

            with pytest.raises(HTTPException) as create_conflict:
                create_ticket(
                    CreateTicketRequest(
                        subject="موضوع متفاوت",
                        message="این payload نباید با همان کلید پذیرفته شود.",
                    ),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-support-create-fixed",
                )
            assert create_conflict.value.status_code == 409

            db.execute(
                support_messages.insert().values(
                    id=str(uuid4()),
                    conversation_id=conversation_id,
                    sequence=2,
                    sender_type="SUPPORT_AGENT",
                    sender_id=str(uuid4()),
                    channel="ADMIN_WEB",
                    message_type="INTERNAL_NOTE",
                    visibility="AGENT_ONLY",
                    body="internal-note-sentinel",
                    body_sha256=sha256(b"internal-note-sentinel").hexdigest(),
                    client_idempotency_key="internal-note-test",
                    created_at=datetime.now(UTC),
                )
            )
            db.commit()

            detail = ticket_detail(reference, Response(), None, db, owner_telegram)
            assert "internal-note-sentinel" not in repr(detail)
            assert len(detail["messages"]) == 1

            replied = reply_ticket(
                reference,
                ReplyTicketRequest(message="اطلاعات بیشتری ارسال شد."),
                Response(),
                None,
                db,
                owner_telegram,
                "tg-support-reply-fixed",
            )
            repeated_reply = reply_ticket(
                reference,
                ReplyTicketRequest(message="اطلاعات بیشتری ارسال شد."),
                Response(),
                None,
                db,
                owner_telegram,
                "tg-support-reply-fixed",
            )
            assert replied["reference"] == repeated_reply["reference"]
            assert len(replied["messages"]) == 2
            with pytest.raises(HTTPException) as reply_conflict:
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="متن متفاوت با همان کلید"),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-support-reply-fixed",
                )
            assert reply_conflict.value.status_code == 409

            for sequence in range(4, 109):
                body = f"bulk-{sequence}"
                db.execute(
                    support_messages.insert().values(
                        id=str(uuid4()),
                        conversation_id=conversation_id,
                        sequence=sequence,
                        sender_type="SUPPORT_AGENT",
                        sender_id=str(uuid4()),
                        channel="ADMIN_WEB",
                        message_type="AGENT_MESSAGE",
                        visibility="PUBLIC",
                        body=body,
                        body_sha256=sha256(body.encode()).hexdigest(),
                        client_idempotency_key=f"bulk-{sequence}",
                        created_at=datetime.now(UTC),
                    )
                )
            db.commit()
            latest = ticket_detail(reference, Response(), None, db, owner_telegram)
            latest_messages = latest["messages"]
            assert isinstance(latest_messages, list)
            assert len(latest_messages) == 100
            assert latest_messages[-1]["sequence"] == 108
            assert latest_messages[-1]["body"] == "bulk-108"
            assert all(message["body"] != "bulk-4" for message in latest_messages)

            now = datetime.now(UTC)
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(status="RESOLVED", resolved_at=now)
            )
            db.commit()
            reopened = reply_ticket(
                reference,
                ReplyTicketRequest(message="مشکل دوباره برگشته است."),
                Response(),
                None,
                db,
                owner_telegram,
                "tg-support-reopen-fixed",
            )
            assert reopened["status"] == "WAITING_FOR_SUPPORT"
            transitions = db.execute(
                select(
                    support_status_history.c.from_status,
                    support_status_history.c.to_status,
                )
                .where(support_status_history.c.conversation_id == conversation_id)
                .order_by(support_status_history.c.created_at.asc())
            ).all()
            assert ("RESOLVED", "REOPENED") in transitions
            assert ("REOPENED", "WAITING_FOR_SUPPORT") in transitions

            with pytest.raises(HTTPException) as forbidden:
                ticket_detail(reference, Response(), None, db, other_telegram)
            assert forbidden.value.status_code == 404
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
