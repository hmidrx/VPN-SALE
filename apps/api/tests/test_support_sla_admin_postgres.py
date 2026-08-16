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

from platform_api.identity.models import (
    AdminModel,
    AuditLogModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_messages,
)
from platform_api.support_sla_admin import (
    AcknowledgeEscalationRequest,
    ManualEscalationRequest,
    acknowledge_sla_escalation,
    conversation_sla_escalations,
    list_sla_escalations,
    manually_escalate,
)
from platform_api.support_sla_models import support_notifications, support_sla_escalations
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
        normalized_email=f"sla-{uuid4().hex}@example.test",
        password_hash=sha256(b"support-sla-admin-fixture").hexdigest(),
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
        delete(support_notifications).where(support_notifications.c.conversation_id == conversation_id)
    )
    db.execute(
        delete(support_sla_escalations).where(
            support_sla_escalations.c.conversation_id == conversation_id
        )
    )
    db.execute(delete(support_messages).where(support_messages.c.conversation_id == conversation_id))
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


def test_manual_escalation_can_be_listed_and_acknowledged() -> None:
    engine = create_engine(_postgres_url())
    user_id = admin_id = conversation_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            user_id, telegram_id = _identity(db)
            admin = _admin(db)
            admin_id = admin.id
            ticket = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(
                        subject="Manual escalation fixture",
                        message="Customer needs an operator decision.",
                    ),
                    Response(),
                    None,
                    db,
                    telegram_id,
                    "sla-admin-create-fixed",
                ),
            )
            reference = str(ticket["reference"])
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

            created = cast(
                dict[str, Any],
                manually_escalate(
                    reference,
                    ManualEscalationRequest(
                        reason="Needs manager review",
                        expected_version=int(conversation["version"]),
                    ),
                    _request(),
                    admin,
                    db,
                ),
            )
            assert created["source"] == "MANUAL"
            assert created["phase"] == "MANUAL"
            assert created["status"] == "OPEN"
            escalation_reference = str(created["reference"])

            open_result = cast(
                dict[str, Any], list_sla_escalations(Response(), admin, db, "OPEN", 50)
            )
            open_items = cast(list[dict[str, Any]], open_result["items"])
            assert any(item["reference"] == escalation_reference for item in open_items)

            ticket_result = cast(
                dict[str, Any],
                conversation_sla_escalations(reference, Response(), admin, db),
            )
            ticket_items = cast(list[dict[str, Any]], ticket_result["items"])
            assert ticket_items[0]["ticket_reference"] == reference

            acknowledged = cast(
                dict[str, Any],
                acknowledge_sla_escalation(
                    escalation_reference,
                    AcknowledgeEscalationRequest(note="Manager took ownership"),
                    _request(),
                    admin,
                    db,
                ),
            )
            assert acknowledged["status"] == "ACKNOWLEDGED"
            assert acknowledged["acknowledged_at"] is not None
            repeated = cast(
                dict[str, Any],
                acknowledge_sla_escalation(
                    escalation_reference,
                    AcknowledgeEscalationRequest(note="ignored duplicate acknowledgement"),
                    _request(),
                    admin,
                    db,
                ),
            )
            assert repeated["status"] == "ACKNOWLEDGED"

            notification = (
                db.execute(
                    select(support_notifications).where(
                        support_notifications.c.conversation_id == conversation_id
                    )
                )
                .mappings()
                .one()
            )
            assert notification["event_type"] == "SUPPORT_MANUAL_ESCALATION"
            payload = notification["safe_payload"]
            assert "Customer needs" not in repr(payload)
            assert "Manual escalation fixture" not in repr(payload)
        finally:
            if user_id and admin_id and conversation_id:
                _cleanup(db, user_id, admin_id, conversation_id)
    engine.dispose()
