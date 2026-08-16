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
from platform_api.support_productivity_runtime import (
    CannedResponseDefinition,
    CannedResponseRevision,
    MacroDefinition,
    MacroPreviewRequest,
    MacroRevision,
    RenderCannedResponseRequest,
    ReplyDraftAction,
    StatusDraftAction,
    create_canned_response,
    create_macro,
    list_canned_responses,
    preview_macro,
    render_canned_response,
    revise_canned_response,
    revise_macro,
)
from platform_api.support_runtime_models import (
    support_canned_responses,
    support_conversations,
    support_idempotency_records,
    support_macros,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_internal import CreateTicketRequest, create_ticket


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


def _admin(db: Session) -> AdminModel:
    admin = AdminModel(
        id=str(uuid4()),
        normalized_email=f"support-productivity-{uuid4().hex}@example.test",
        password_hash=sha256(b"support-productivity-test-fixture").hexdigest(),
        status="ACTIVE",
        failed_login_count=0,
    )
    db.add(admin)
    db.commit()
    return admin


def _cleanup(
    db: Session,
    *,
    user_id: str,
    admin_id: str,
    conversation_id: str,
    canned_code: str,
    macro_code: str,
) -> None:
    db.execute(
        delete(AuditLogModel).where(
            AuditLogModel.target_type.in_({"support_canned_response", "support_macro"})
        )
    )
    db.execute(delete(support_macros).where(support_macros.c.code == macro_code))
    db.execute(
        delete(support_canned_responses).where(support_canned_responses.c.code == canned_code)
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


def test_canned_response_and_macro_preview_are_durable_but_non_mutating() -> None:
    engine = create_engine(_postgres_url())
    user_id = admin_id = conversation_id = ""
    canned_code = f"connect_{uuid4().hex[:10]}"
    macro_code = f"triage_{uuid4().hex[:10]}"
    with Session(engine, expire_on_commit=False) as db:
        try:
            user_id, telegram_id = _identity(db)
            admin = _admin(db)
            admin_id = admin.id
            created_ticket = create_ticket(
                CreateTicketRequest(
                    subject="اختلال اتصال",
                    message="از صبح اتصال من برقرار نمی‌شود.",
                ),
                Response(),
                None,
                db,
                telegram_id,
                f"support-productivity-ticket-{uuid4().hex}",
            )
            reference = str(created_ticket["reference"])
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
            original_status = str(conversation["status"])

            canned = create_canned_response(
                CannedResponseDefinition(
                    code=canned_code,
                    title="راهنمای اتصال",
                    body=("برای تیکت {{ticket_reference}} لطفاً {{device_hint}} را بررسی کنید."),
                    locale="fa",
                    queue_id=conversation["queue_id"],
                    category_id=conversation["category_id"],
                    placeholders=["ticket_reference", "device_hint"],
                ),
                _request(),
                admin,
                db,
            )
            assert canned["version"] == 1
            assert canned["usage_count"] == 0

            listed = cast(
                dict[str, Any],
                list_canned_responses(Response(), admin, db, reference, "fa", False),
            )
            listed_items = cast(list[dict[str, Any]], listed["items"])
            assert any(item["code"] == canned_code for item in listed_items)

            rendered = render_canned_response(
                reference,
                canned_code,
                RenderCannedResponseRequest(
                    locale="fa",
                    values={"device_hint": "خاموش و روشن کردن برنامه"},
                ),
                Response(),
                _request(),
                admin,
                db,
            )
            assert reference in str(rendered["body"])
            assert "خاموش و روشن کردن برنامه" in str(rendered["body"])
            usage = db.scalar(
                select(support_canned_responses.c.usage_count).where(
                    support_canned_responses.c.code == canned_code,
                    support_canned_responses.c.version == 1,
                )
            )
            assert usage == 1

            revised = revise_canned_response(
                canned_code,
                CannedResponseRevision(
                    title="راهنمای اتصال به‌روزشده",
                    body="تیکت {{ticket_reference}} در حال بررسی است.",
                    locale="fa",
                    queue_id=conversation["queue_id"],
                    category_id=conversation["category_id"],
                    placeholders=["ticket_reference"],
                ),
                _request(),
                admin,
                db,
            )
            assert revised["version"] == 2
            assert revised["usage_count"] == 0

            macro = create_macro(
                MacroDefinition(
                    code=macro_code,
                    title="شروع بررسی اتصال",
                    actions=[
                        ReplyDraftAction(
                            type="reply_draft",
                            body="تیکت {{ticket_reference}} دریافت شد و در حال بررسی است.",
                        ),
                        StatusDraftAction(
                            type="status_draft",
                            status=SupportStatus.OPEN,
                            reason="شروع بررسی تیکت {{ticket_reference}}",
                        ),
                    ],
                ),
                _request(),
                admin,
                db,
            )
            assert macro["version"] == 1

            preview = preview_macro(
                reference,
                macro_code,
                MacroPreviewRequest(expected_version=original_version),
                Response(),
                _request(),
                admin,
                db,
            )
            draft = cast(dict[str, Any], preview["draft"])
            assert reference in str(draft["reply_body"])
            assert draft["status"] == "OPEN"
            assert reference in str(draft["status_reason"])

            after_preview = (
                db.execute(
                    select(support_conversations).where(
                        support_conversations.c.id == conversation_id
                    )
                )
                .mappings()
                .one()
            )
            assert int(after_preview["version"]) == original_version
            assert str(after_preview["status"]) == original_status

            macro_revision = revise_macro(
                macro_code,
                MacroRevision(
                    title="شروع بررسی اتصال غیرفعال",
                    actions=[ReplyDraftAction(type="reply_draft", body="این نسخه غیرفعال است.")],
                    active=False,
                ),
                _request(),
                admin,
                db,
            )
            assert macro_revision["version"] == 2
            assert macro_revision["active"] is False
        finally:
            if user_id and admin_id and conversation_id:
                _cleanup(
                    db,
                    user_id=user_id,
                    admin_id=admin_id,
                    conversation_id=conversation_id,
                    canned_code=canned_code,
                    macro_code=macro_code,
                )
    engine.dispose()
