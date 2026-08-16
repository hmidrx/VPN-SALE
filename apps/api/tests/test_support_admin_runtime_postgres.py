from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import Request, Response
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session
from vpnsale_domain.support import SupportStatus

from platform_api.identity.models import (
    AdminModel,
    AuditLogModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.support_admin_runtime import (
    AgentMessageRequest,
    ClaimRequest,
    StatusChangeRequest,
    add_internal_note,
    change_status,
    claim_conversation,
    conversation_detail,
    inbox,
    internal_notes,
    reply_conversation,
)
from platform_api.support_runtime_models import (
    support_assignments,
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_internal import CreateTicketRequest, create_ticket, ticket_detail


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


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


def _test_password_hash() -> str:
    return sha256(b"support-admin-test-fixture").hexdigest()


def _admin(db: Session) -> AdminModel:
    admin = AdminModel(
        id=str(uuid4()),
        normalized_email=f"support-{uuid4().hex}@example.test",
        password_hash=_test_password_hash(),
        status="ACTIVE",
        failed_login_count=0,
    )
    db.add(admin)
    db.commit()
    return admin


def _cleanup(db: Session, user_id: str, admin_id: str, conversation_id: str) -> None:
    db.execute(
        delete(AuditLogModel).where(
            AuditLogModel.target_type == "support_conversation",
            AuditLogModel.target_id == conversation_id,
        )
    )
    db.execute(
        delete(support_assignments).where(support_assignments.c.conversation_id == conversation_id)
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
            support_idempotency_records.c.scope == f"tg-ticket:{user_id}"
        )
    )
    db.query(TelegramAccountModel).filter(TelegramAccountModel.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id == user_id).delete(synchronize_session=False)
    db.query(AdminModel).filter(AdminModel.id == admin_id).delete(synchronize_session=False)
    db.commit()


def test_telegram_ticket_round_trips_through_durable_admin_inbox() -> None:
    engine = create_engine(_postgres_url())
    user_id = admin_id = conversation_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            user_id, telegram_id = _identity(db)
            admin = _admin(db)
            admin_id = admin.id
            created = create_ticket(
                CreateTicketRequest(
                    subject="اختلال اتصال",
                    message="سرویس از چند دقیقه قبل متصل نمی‌شود.",
                ),
                Response(),
                None,
                db,
                telegram_id,
                "tg-support-admin-e2e-create",
            )
            reference = str(created["reference"])
            conversation_id = str(
                db.scalar(
                    select(support_conversations.c.id).where(
                        support_conversations.c.reference == reference
                    )
                )
            )
            assert conversation_id

            queue = cast(dict[str, Any], inbox(Response(), admin, db, None, 50))
            items = cast(list[dict[str, Any]], queue["items"])
            assert any(item["reference"] == reference for item in items)

            detail = cast(dict[str, Any], conversation_detail(reference, Response(), admin, db))
            assert detail["status"] == "NEW"
            messages = cast(list[dict[str, Any]], detail["messages"])
            assert messages[0]["body"] == "سرویس از چند دقیقه قبل متصل نمی‌شود."

            claimed = cast(
                dict[str, Any],
                claim_conversation(
                    reference,
                    ClaimRequest(expected_version=int(detail["version"])),
                    _request(),
                    admin,
                    db,
                ),
            )
            assert claimed["assigned_to_me"] is True
            assert claimed["status"] == "ASSIGNED"

            notes_result = cast(
                dict[str, Any],
                add_internal_note(
                    reference,
                    AgentMessageRequest(
                        body="لاگ داخلی بررسی شد؛ این متن نباید به مشتری برسد.",
                        expected_version=int(claimed["version"]),
                    ),
                    _request(),
                    admin,
                    db,
                    "admin-support-note-fixed",
                ),
            )
            note_items = cast(list[dict[str, Any]], notes_result["items"])
            assert note_items[-1]["message_type"] == "INTERNAL_NOTE"

            after_note = cast(dict[str, Any], conversation_detail(reference, Response(), admin, db))
            public_repr = repr(after_note["messages"])
            assert "این متن نباید به مشتری برسد" not in public_repr
            private = cast(dict[str, Any], internal_notes(reference, Response(), admin, db))
            assert "این متن نباید به مشتری برسد" in repr(private["items"])

            replied = cast(
                dict[str, Any],
                reply_conversation(
                    reference,
                    AgentMessageRequest(
                        body="بررسی انجام شد. لطفاً اکنون اتصال را دوباره امتحان کنید.",
                        expected_version=int(after_note["version"]),
                    ),
                    _request(),
                    admin,
                    db,
                    "admin-support-reply-fixed",
                ),
            )
            replied_messages = cast(list[dict[str, Any]], replied["messages"])
            assert replied_messages[-1]["sender_type"] == "SUPPORT_AGENT"

            customer_view = cast(
                dict[str, Any], ticket_detail(reference, Response(), None, db, telegram_id)
            )
            assert "لطفاً اکنون اتصال را دوباره امتحان کنید" in repr(customer_view["messages"])
            assert "این متن نباید به مشتری برسد" not in repr(customer_view["messages"])

            status_changed = cast(
                dict[str, Any],
                change_status(
                    reference,
                    StatusChangeRequest(
                        status=SupportStatus.IN_PROGRESS,
                        reason="Agent started active investigation",
                        expected_version=int(replied["version"]),
                    ),
                    _request(),
                    admin,
                    db,
                ),
            )
            assert status_changed["status"] == "IN_PROGRESS"
            history = [
                tuple(row)
                for row in db.execute(
                    select(
                        support_status_history.c.from_status,
                        support_status_history.c.to_status,
                    ).where(support_status_history.c.conversation_id == conversation_id)
                ).all()
            ]
            assert ("NEW", "ASSIGNED") in history
            assert ("ASSIGNED", "IN_PROGRESS") in history
        finally:
            if user_id and admin_id and conversation_id:
                _cleanup(db, user_id, admin_id, conversation_id)
    engine.dispose()
